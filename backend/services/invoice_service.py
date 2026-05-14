"""GST invoice generation service.

Generates per-session tax invoices for ALL completed charging sessions.
Supplier = VoltLync (single GST merchant-of-record). The franchisee operator
of the station is snapshotted onto each invoice and rendered as an
"Operated by:" block on the PDF, per Razorpay's linked-account disclosure
requirement. Invoice numbering is per-(franchisee, series, FY) — each
franchisee operates as a substore with its own running sequence; VoltLync-
owned stations share a NULL-franchisee sequence.
"""

import io
import os
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from num2words import num2words
from tortoise.transactions import atomic

from models import (
    Transaction,
    Charger,
    Connector,
    ChargingStation,
    Franchisee,
    GSTInvoice,
    GSTInvoiceCounter,
    QRPayment,
    User,
    UserRoleEnum,
)
from services.wallet_service import WalletService
from services.monitoring_service import MetricsCollector

logger = logging.getLogger("ocpp-server")

TWO_DP = Decimal("0.01")

# VoltLync is the supplier on every customer-facing invoice (merchant-of-record
# under Razorpay Route). Franchisee operator details are snapshotted onto the
# invoice separately and rendered as the "Operated by" block on the PDF.
VOLTLYNC_NAME = os.getenv("VOLTLYNC_BUSINESS_NAME", "VOLTLYNC PRIVATE LIMITED")
VOLTLYNC_GSTIN = os.getenv("VOLTLYNC_GSTIN", "")
VOLTLYNC_ADDRESS = os.getenv("VOLTLYNC_ADDRESS", "")
VOLTLYNC_STATE = os.getenv("VOLTLYNC_STATE", "Kerala")
VOLTLYNC_STATE_CODE = os.getenv("VOLTLYNC_STATE_CODE", "32")

# Roles whose charging sessions are internal/operational (admin test-charges,
# franchisee remote-starts on their own stations) and not customer sales —
# generate_invoice skips these so they don't pollute the GST liability or
# the per-franchisee invoice sequence.
INTERNAL_ROLES = {UserRoleEnum.ADMIN, UserRoleEnum.FRANCHISEE}


def _get_financial_year(dt: datetime) -> str:
    """Return FY string like '2026-27'. Indian FY runs Apr-Mar."""
    year = dt.year
    month = dt.month
    if month < 4:
        return f"{year - 1}-{str(year)[-2:]}"
    return f"{year}-{str(year + 1)[-2:]}"


def _amount_in_words(amount: Decimal) -> str:
    """Convert amount to words (Indian English)."""
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    words = num2words(rupees, lang="en_IN")
    if paise > 0:
        return f"{words} and {num2words(paise, lang='en_IN')} paise"
    return words


def _format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return ""
    h, remainder = divmod(seconds, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h:02d}h{m:02d}m:{s:02d}"
    return f"{m:02d}m:{s:02d}"


class InvoiceService:

    @staticmethod
    @atomic()
    async def get_next_invoice_number(
        franchisee_id: Optional[int],
        series: str,
        financial_year: str,
    ) -> str:
        """Atomic counter increment using SELECT FOR UPDATE.

        Per-(franchisee, series, FY) sequence. Each franchisee is a substore
        with its own running counter; VoltLync-owned stations (franchisee_id
        IS NULL) share a single sequence per (series, FY).

        Number format:
          VL/F{franchisee_id}/{SERIES}/{FY_NODASH}/{SEQ:05d}   for franchisee-owned
          VL/{SERIES}/{FY_NODASH}/{SEQ:05d}                     for VoltLync-owned
        """
        counter = await GSTInvoiceCounter.filter(
            franchisee_id=franchisee_id,
            series=series,
            financial_year=financial_year,
        ).select_for_update().first()

        if counter:
            counter.last_number += 1
            await counter.save()
            seq = counter.last_number
        else:
            counter = await GSTInvoiceCounter.create(
                franchisee_id=franchisee_id,
                series=series,
                financial_year=financial_year,
                last_number=1,
            )
            seq = 1

        fy_short = financial_year.replace("-", "")
        prefix = f"VL/F{franchisee_id}" if franchisee_id else "VL"
        return f"{prefix}/{series}/{fy_short}/{seq:05d}"

    @staticmethod
    def determine_gst_split(
        supplier_state_code: Optional[str],
        station_state_code: Optional[str],
        energy_taxable: Decimal,
        energy_tax: Decimal,
        gateway_taxable: Decimal,
        gateway_tax: Decimal,
        gst_rate: Decimal,
    ) -> dict:
        """Split pre-computed tax amounts across CGST+SGST (intra-state) or IGST (inter-state).

        Inputs are the stored taxable values and tax amounts; we only decide
        which buckets to put them in.
        """
        is_inter = (
            supplier_state_code
            and station_state_code
            and supplier_state_code != station_state_code
        )

        total_tax = energy_tax + gateway_tax

        if is_inter:
            return {
                "is_inter_state": True,
                "cgst_rate": None, "cgst_amount": None,
                "sgst_rate": None, "sgst_amount": None,
                "igst_rate": gst_rate, "igst_amount": total_tax,
                "total_tax": total_tax,
            }

        half_rate = (gst_rate / 2).quantize(TWO_DP, ROUND_HALF_UP)
        half_tax = (total_tax / 2).quantize(TWO_DP, ROUND_HALF_UP)
        # Keep paise balance: SGST absorbs any 1-paise residual from /2 rounding
        sgst_amount = total_tax - half_tax
        return {
            "is_inter_state": False,
            "cgst_rate": half_rate, "cgst_amount": half_tax,
            "sgst_rate": half_rate, "sgst_amount": sgst_amount,
            "igst_rate": None, "igst_amount": None,
            "total_tax": total_tax,
        }

    @staticmethod
    @atomic()
    async def generate_invoice(
        transaction_id: int,
    ) -> Optional[GSTInvoice]:
        """Generate a GST invoice for a completed transaction.

        Wrapped in @atomic() and locks the Transaction row to serialise
        concurrent callers — prevents duplicate invoices and gaps in the
        per-(franchisee, series, FY) invoice number sequence.
        """

        # Lock the transaction row first so concurrent callers serialise here.
        txn = await Transaction.filter(
            id=transaction_id
        ).select_for_update().first()
        if not txn:
            return None

        # Idempotency check (now race-free under the row lock).
        existing = await GSTInvoice.filter(
            transaction_id=transaction_id
        ).first()
        if existing:
            return existing

        energy = txn.energy_consumed_kwh or 0
        if energy <= 0:
            return None

        # Skip invoicing for internal-role sessions (admin test-charges or
        # franchisee remote-starts on their own stations). These deduct from
        # the initiator's wallet but are operational, not customer sales —
        # issuing a customer-facing GST invoice would inflate liability and
        # consume an invoice number for an internal event.
        user = await User.filter(id=txn.user_id).first()
        if user and user.role in INTERNAL_ROLES:
            logger.info(
                "GST invoice skipped for txn %s: %s-initiated session",
                transaction_id, user.role.value,
            )
            MetricsCollector.increment_counter("Custom/Invoice/InternalRoleSkipped")
            return None

        # Resolve charger -> station -> franchisee
        charger = await Charger.filter(id=txn.charger_id).first()
        if not charger:
            return None
        station = await ChargingStation.filter(
            id=charger.station_id
        ).first()
        if not station:
            return None

        # Supplier (GST merchant-of-record) is always VoltLync. The franchisee
        # operating the station is captured separately as a snapshot for the
        # "Operated by" disclosure block on the PDF (Razorpay requirement).
        franchisee_id = station.franchisee_id
        franchisee = (
            await Franchisee.filter(id=franchisee_id).first()
            if franchisee_id else None
        )

        supplier_name = VOLTLYNC_NAME
        supplier_gstin = VOLTLYNC_GSTIN
        supplier_address = VOLTLYNC_ADDRESS
        supplier_state = VOLTLYNC_STATE
        supplier_state_code = VOLTLYNC_STATE_CODE

        # Franchisee operator snapshot. All NULL for VoltLync-owned stations
        # — the PDF then omits the "Operated by" block entirely.
        franchisee_business_name = franchisee.business_name if franchisee else None
        franchisee_gstin = franchisee.gstin if franchisee else None
        franchisee_address = franchisee.address if franchisee else None
        franchisee_state = franchisee.state if franchisee else None
        franchisee_state_code = franchisee.state_code if franchisee else None

        # Compliance guard: a tax invoice without supplier GSTIN is invalid
        # under CGST Rule 46. Skip issuance until VoltLync has a GSTIN
        # configured via the VOLTLYNC_GSTIN env var.
        if not supplier_gstin:
            logger.error(
                "GST invoice NOT issued for txn %s: VOLTLYNC_GSTIN not configured",
                transaction_id,
            )
            MetricsCollector.increment_counter("Custom/Invoice/GstinMissing")
            return None

        # Customer details (user already fetched above for the role-skip guard)
        qr_payment = await QRPayment.filter(
            transaction_id=transaction_id
        ).first()

        if qr_payment:
            payment_method = "UPI"
            # QR customers identify by VPA — use it as the name fallback
            customer_name = (
                qr_payment.customer_name
                or qr_payment.customer_vpa
                or qr_payment.customer_contact
            )
            customer_identifier = qr_payment.customer_vpa or qr_payment.customer_contact
            # `transaction_amount` is the gross UPI payment; `refund_amount`
            # captures whatever was returned to the customer. Rendered as
            # two separate lines on the PDF.
            transaction_amount = qr_payment.amount_paid or Decimal("0")
            refund_amount = qr_payment.refund_amount or Decimal("0")
            gateway_taxable = qr_payment.razorpay_commission or Decimal("0")
            gateway_tax = qr_payment.razorpay_gst or Decimal("0")
            series = "QR"
        else:
            payment_method = "WALLET"
            customer_name = user.full_name if user else None
            customer_identifier = user.email if user else None
            transaction_amount = txn.total_billed
            refund_amount = None
            gateway_taxable = Decimal("0")
            gateway_tax = Decimal("0")
            series = "WAL"

        # Use stored taxable values directly — no reverse-calc, no /1.18.
        energy_taxable = txn.energy_charge or Decimal("0")
        energy_tax = txn.gst_amount or Decimal("0")
        total_taxable = energy_taxable + gateway_taxable
        gst_rate = txn.gst_rate_percent or Decimal("18.00")

        # GST split (just buckets — totals come from stored values)
        gst_split = InvoiceService.determine_gst_split(
            supplier_state_code=supplier_state_code,
            station_state_code=station.state_code,
            energy_taxable=energy_taxable,
            energy_tax=energy_tax,
            gateway_taxable=gateway_taxable,
            gateway_tax=gateway_tax,
            gst_rate=gst_rate,
        )

        total_amount = total_taxable + gst_split["total_tax"]

        # Tariff (needed both for HSN/SAC and for deriving billable_kwh on QR
        # invoices, where `txn.energy_charge` may be capped at the budget).
        tariff = await WalletService.get_applicable_tariff(charger.id)
        hsn_sac_code = (tariff.hsn_sac_code if tariff else None) or "996749"

        # Billable kWh — what the customer is being billed for. For QR sessions
        # this can be less than `txn.energy_consumed_kwh` when the charger
        # over-delivered past the budget cap; the over-delivery is absorbed by
        # the operator and doesn't appear on the customer's invoice.
        # For WAL sessions `energy_charge = actual_kwh × rate`, so this equals
        # the actual reading.
        if tariff and tariff.rate_per_kwh and energy_taxable > 0:
            billable_kwh = (energy_taxable / tariff.rate_per_kwh).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
        else:
            billable_kwh = energy if isinstance(energy, Decimal) else Decimal(str(energy or 0))

        # Tax-inclusive tariff rate for display — derived from billable_kwh so
        # the line-item math reconciles (rate × kWh = total).
        tariff_rate_incl = (
            ((energy_taxable + energy_tax) / billable_kwh).quantize(
                TWO_DP, ROUND_HALF_UP
            )
            if billable_kwh > 0 else Decimal("0")
        )

        # Connector type
        connector = await Connector.filter(charger_id=charger.id).first()
        connector_type = connector.connector_type if connector else None

        # Duration
        duration_seconds = None
        if txn.start_time and txn.end_time:
            duration_seconds = int(
                (txn.end_time - txn.start_time).total_seconds()
            )

        # Financial year and invoice number
        now = datetime.utcnow()
        fy = _get_financial_year(now)
        invoice_number = await InvoiceService.get_next_invoice_number(
            franchisee_id=franchisee_id,
            series=series,
            financial_year=fy,
        )

        invoice = await GSTInvoice.create(
            invoice_number=invoice_number,
            series=series,
            financial_year=fy,
            transaction=txn,
            franchisee_id=franchisee_id,
            user=user,
            supplier_name=supplier_name,
            supplier_gstin=supplier_gstin,
            supplier_address=supplier_address,
            supplier_state=supplier_state,
            supplier_state_code=supplier_state_code,
            franchisee_business_name=franchisee_business_name,
            franchisee_gstin=franchisee_gstin,
            franchisee_address=franchisee_address,
            franchisee_state=franchisee_state,
            franchisee_state_code=franchisee_state_code,
            customer_name=customer_name,
            customer_identifier=customer_identifier,
            station_name=station.name,
            station_location=f"{station.address or ''}, {station.state or ''}".strip(", "),
            place_of_supply_state_code=station.state_code,
            charger_id_str=charger.charge_point_string_id,
            connector_type=connector_type,
            energy_consumed_kwh=billable_kwh,
            tariff_rate_incl_tax=tariff_rate_incl,
            charged_on=txn.start_time,
            duration_seconds=duration_seconds,
            hsn_sac_code=hsn_sac_code,
            gst_rate_percent=gst_rate,
            energy_taxable_value=energy_taxable,
            gateway_charges=gateway_taxable,
            gateway_gst=(qr_payment.razorpay_gst if qr_payment else None),
            total_taxable_value=total_taxable,
            is_inter_state=gst_split["is_inter_state"],
            cgst_rate=gst_split["cgst_rate"],
            cgst_amount=gst_split["cgst_amount"],
            sgst_rate=gst_split["sgst_rate"],
            sgst_amount=gst_split["sgst_amount"],
            igst_rate=gst_split["igst_rate"],
            igst_amount=gst_split["igst_amount"],
            total_tax=gst_split["total_tax"],
            total_amount=total_amount,
            amount_in_words=_amount_in_words(total_amount),
            payment_method=payment_method,
            transaction_amount=transaction_amount,
            refund_amount=refund_amount,
        )

        logger.info(
            "GST invoice generated: %s for txn %s",
            invoice_number, transaction_id,
        )
        MetricsCollector.increment_counter("Custom/Invoice/Issued")
        MetricsCollector.record_metric(
            "Custom/Invoice/TotalAmount", float(total_amount)
        )
        return invoice

    @staticmethod
    def generate_pdf(invoice: GSTInvoice) -> bytes:
        """Generate a PDF matching the sample invoice layout."""
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
        )
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15*mm, bottomMargin=15*mm)
        styles = getSampleStyleSheet()
        elements = []

        title_style = ParagraphStyle("InvTitle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#2E7D32"))
        subtitle_style = ParagraphStyle("InvSub", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
        bold_style = ParagraphStyle("Bold", parent=styles["Normal"], fontSize=9, fontName="Helvetica-Bold")
        normal_style = ParagraphStyle("Norm", parent=styles["Normal"], fontSize=9)
        small_style = ParagraphStyle("Small", parent=styles["Normal"], fontSize=7, textColor=colors.grey)

        # Header
        elements.append(Paragraph("TAX INVOICE", title_style))
        elements.append(Spacer(1, 3*mm))

        # Invoice meta
        inv_date = invoice.invoice_date.strftime("%d %B %Y") if invoice.invoice_date else ""
        meta_data = [
            [Paragraph(f"<b>Invoice#:</b> {invoice.invoice_number}", normal_style),
             Paragraph(f"<b>Date:</b> {inv_date}", normal_style)],
        ]
        t = Table(meta_data, colWidths=[250, 250])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(t)
        elements.append(Spacer(1, 4*mm))

        # Supplier / Billed To
        supplier_text = f"<b>{invoice.supplier_name}</b><br/>"
        if invoice.supplier_address:
            supplier_text += f"{invoice.supplier_address}<br/>"
        if invoice.supplier_gstin:
            supplier_text += f"GSTIN: {invoice.supplier_gstin}"

        customer_text = ""
        if invoice.customer_name:
            customer_text += f"{invoice.customer_name}<br/>"
        if invoice.customer_identifier:
            id_label = "UPI ID" if invoice.payment_method == "UPI" else "Email"
            customer_text += f"{id_label}: {invoice.customer_identifier}<br/>"
        customer_text += "ADDRESS: NA"

        party_data = [
            [Paragraph(supplier_text, normal_style),
             Paragraph(f"<b>BILLED TO:</b><br/>{customer_text}", normal_style)],
        ]
        t = Table(party_data, colWidths=[250, 250])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 2*mm))

        # "Operated by" block — Razorpay linked-account disclosure. Renders
        # only when this invoice is tied to a franchisee-operated station.
        if invoice.franchisee_business_name:
            operator_text = f"<b>Operated by:</b> {invoice.franchisee_business_name}<br/>"
            if invoice.franchisee_address:
                operator_text += f"{invoice.franchisee_address}<br/>"
            if invoice.franchisee_gstin:
                operator_text += f"GSTIN: {invoice.franchisee_gstin}"
            operator_data = [[Paragraph(operator_text, normal_style), Paragraph("", normal_style)]]
            t = Table(operator_data, colWidths=[250, 250])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 2*mm))
        elements.append(Spacer(1, 2*mm))

        # Station / Charger
        station_text = f"<b>STATION:</b> {invoice.station_name or ''}<br/>{invoice.station_location or ''}"
        charger_text = f"<b>CHARGER ID:</b> {invoice.charger_id_str or ''}<br/><b>CONNECTOR TYPE:</b> {invoice.connector_type or ''}"
        loc_data = [[Paragraph(station_text, normal_style), Paragraph(charger_text, normal_style)]]
        t = Table(loc_data, colWidths=[250, 250])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 4*mm))

        # Line items table
        charged_on_str = invoice.charged_on.strftime("%d/%m/%Y, %I:%M %p") if invoice.charged_on else ""
        duration_str = _format_duration(invoice.duration_seconds)

        header = ["HSN CODE", "ENERGY BILLED\n(kWh)", "TARIFF / kWh\n(Including Taxes)", "CHARGED ON", "DURATION", "AMOUNT (INR)"]
        rows = [header]
        rows.append([
            str(invoice.hsn_sac_code),
            f"{invoice.energy_consumed_kwh:.1f}",
            str(invoice.tariff_rate_incl_tax),
            charged_on_str,
            duration_str,
            f"{invoice.energy_taxable_value:.2f}",
        ])
        if invoice.gateway_charges and invoice.gateway_charges > 0:
            rows.append([
                str(invoice.gateway_hsn_code), "", "", "", "Gateway Charges",
                f"{invoice.gateway_charges:.2f}",
            ])

        t = Table(rows, colWidths=[60, 70, 80, 90, 70, 80])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3*mm))

        # Tax breakdown
        tax_rows = []
        if not invoice.is_inter_state and invoice.cgst_rate:
            tax_rows.append([f"CGST {invoice.cgst_rate}%:", f"{invoice.cgst_amount:.2f}"])
            tax_rows.append([f"SGST {invoice.sgst_rate}%:", f"{invoice.sgst_amount:.2f}"])
        elif invoice.igst_rate:
            tax_rows.append([f"IGST {invoice.igst_rate}%:", f"{invoice.igst_amount:.2f}"])

        tax_rows.append(["TOTAL", f"{invoice.total_amount:.2f}"])

        t = Table(tax_rows, colWidths=[370, 80])
        style_cmds = [
            ("ALIGN", (0, 0), (0, -1), "RIGHT"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
        t.setStyle(TableStyle(style_cmds))
        elements.append(t)
        elements.append(Spacer(1, 3*mm))

        # Amount in words
        if invoice.amount_in_words:
            elements.append(Paragraph(
                f"<b>Amount in words:</b> {invoice.amount_in_words}",
                normal_style,
            ))
            elements.append(Spacer(1, 3*mm))

        # Payment info — `transaction_amount` is the gross UPI payment;
        # `refund_amount` is whatever was returned to the customer.
        pay_text = f"<b>Payment Method:</b> {invoice.payment_method or ''}"
        if invoice.transaction_amount:
            pay_text += f"&nbsp;&nbsp;&nbsp;&nbsp;<b>Transaction Amount:</b> {invoice.transaction_amount:.2f}"
        elements.append(Paragraph(pay_text, normal_style))

        if invoice.refund_amount and invoice.refund_amount > 0:
            elements.append(Paragraph(
                f"<b>Refund Amount:</b> {invoice.refund_amount:.2f}",
                normal_style,
            ))
            elements.append(Paragraph(
                "Refund processing: Takes 3-5 working days. Amount will be "
                "credited to customer's bank account within 5-7 working days "
                "after the refund has processed.",
                small_style,
            ))

        elements.append(Spacer(1, 8*mm))

        # Legal footer
        elements.append(Paragraph(
            "The courts, tribunals, legal establishment in Cochin, Kerala, "
            "shall have exclusive jurisdiction in respect of all or any of "
            "disputes, differences, claims or otherwise arising out of this document.",
            small_style,
        ))
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(
            "<b>THIS IS A COMPUTER GENERATED INVOICE</b>",
            ParagraphStyle("Footer", parent=small_style, alignment=1),
        ))

        doc.build(elements)
        return buf.getvalue()
