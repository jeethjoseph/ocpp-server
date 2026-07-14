"""Tests for the GST invoice generation flow after the schema cleanup."""

import os
from decimal import Decimal, ROUND_HALF_UP

import pytest

from models import (
    Charger,
    ChargingStation,
    Connector,
    GSTInvoice,
    QRPayment,
    QRPaymentStatusEnum,
    Tariff,
    Transaction,
    TransactionStatusEnum,
    User,
    UserRoleEnum,
)
from services import invoice_service as _svc
from services.invoice_service import InvoiceService


@pytest.fixture(autouse=True)
def _voltlync_supplier(monkeypatch):
    """Provide a valid VoltLync GSTIN for every test that doesn't opt out.

    Module-level constants are captured at import time, so env-var tricks
    after import don't take effect — we patch the constants directly.
    """
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "32ABCDE1234F1Z5")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE_CODE", "32")
    monkeypatch.setattr(_svc, "VOLTLYNC_STATE", "Kerala")


async def _make_session(
    rate=Decimal("20.00"),
    gst_percent=Decimal("18.00"),
    energy_kwh=1.0,
    station_state_code="32",
    with_qr=False,
    franchisee=None,
):
    """Create a station+charger+transaction+(qr_payment) fixture inline."""
    station = await ChargingStation.create(
        name="Test Station",
        state="Kerala",
        state_code=station_state_code,
        franchisee=franchisee,
    )
    import uuid as _uuid
    charger = await Charger.create(
        charge_point_string_id=f"chg-{_uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Available",
    )
    await Connector.create(charger=charger, connector_id=1, connector_type="Type2")
    await Tariff.create(
        charger=charger,
        rate_per_kwh=rate,
        rate_gst_included=(rate * (Decimal("1") + gst_percent / Decimal("100"))).quantize(Decimal("0.0001")),
        gst_percent=gst_percent,
        is_global=False,
        hsn_sac_code="996749",
    )
    user = await User.create(
        email=f"u-{_uuid.uuid4().hex[:8]}@v.test",
        phone_number=f"9{_uuid.uuid4().int % 1000000000:09d}",
    )

    energy_charge = (Decimal(str(energy_kwh)) * rate).quantize(Decimal("0.01"))
    gst_amount = (energy_charge * gst_percent / Decimal("100")).quantize(Decimal("0.01"))

    txn = await Transaction.create(
        user=user,
        charger=charger,
        energy_consumed_kwh=energy_kwh,
        energy_charge=energy_charge,
        gst_amount=gst_amount,
        gst_rate_percent=gst_percent,
        total_billed=energy_charge + gst_amount,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )

    qr_payment = None
    if with_qr:
        from models import ChargerQRCode
        qr_code = await ChargerQRCode.create(
            charger=charger,
            razorpay_qr_code_id=f"qr_{_uuid.uuid4().hex[:8]}",
            image_url=f"https://r/{_uuid.uuid4().hex[:6]}.png",
            is_active=True,
        )
        # platform_fee / razorpay_commission / razorpay_gst on the row are the
        # ACTUAL Razorpay fee (₹0.24 = commission ₹0.20 + GST ₹0.04) per ADR
        # 0026. refund_amount is computed against that ACTUAL fee so the prepaid
        # invariant total_amount + refund_amount == amount_paid holds against
        # the invoice (whose gateway line now uses the actual Razorpay fee).
        qr_payment = await QRPayment.create(
            razorpay_payment_id=f"pay_{_uuid.uuid4().hex[:10]}",
            razorpay_qr_code_id=qr_code.razorpay_qr_code_id,
            charger=charger,
            charger_qr_code=qr_code,
            user=user,
            transaction=txn,
            customer_vpa="testpayer@oksbi",
            amount_paid=Decimal("20.00"),
            energy_cost=energy_charge,
            gst_amount=gst_amount,
            platform_fee=Decimal("0.24"),
            razorpay_commission=Decimal("0.20"),
            razorpay_gst=Decimal("0.04"),
            refund_amount=(
                Decimal("20.00") - energy_charge - gst_amount - Decimal("0.24")
            ),
            status=QRPaymentStatusEnum.REFUNDED,
        )

    return station, charger, txn, user, qr_payment


# ─── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wallet_invoice_uses_stored_taxable_values(client):
    """Energy taxable value should equal txn.energy_charge — no /1.18 reverse-calc."""
    _, _, txn, _, _ = await _make_session(energy_kwh=2.0)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.energy_taxable_value == txn.energy_charge
    assert invoice.gateway_charges == Decimal("0")
    assert invoice.total_taxable_value == txn.energy_charge
    # CGST and SGST are independent equal halves; their sum + round_off
    # reconciles to the billing tax (ADR 0017).
    assert invoice.cgst_amount == invoice.sgst_amount
    assert invoice.total_tax + invoice.round_off == txn.gst_amount
    assert invoice.total_amount == txn.energy_charge + txn.gst_amount
    assert invoice.gst_rate_percent == Decimal("18.00")
    assert invoice.hsn_sac_code == "996749"
    assert invoice.series == "WAL"


@pytest.mark.asyncio
async def test_qr_invoice_uses_vpa_as_customer_name(client):
    """For QR sessions without a customer name, fall back to the VPA."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.customer_name == qr_payment.customer_vpa
    assert invoice.payment_method == "UPI"
    assert invoice.series == "QR"


@pytest.mark.asyncio
async def test_qr_invoice_shows_gross_payment_and_refund_separately(client):
    """For QR sessions: transaction_amount is the gross UPI payment;
    refund_amount is the absolute amount returned to the customer.
    Mirrors the substore PDF mockup which shows both as separate lines."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice.transaction_amount == qr_payment.amount_paid
    assert invoice.refund_amount == qr_payment.refund_amount


@pytest.mark.asyncio
async def test_invoice_snapshots_operator_set_all_in_tariff(client):
    """generate_invoice snapshots the operator's `rate_gst_included` onto
    the GSTInvoice row at issuance so the PDF can show the customer the same
    rate they saw on the QR / stations screen when they paid — even if the
    operator later changes the tariff. See ADR 0026 (column renamed from
    tariff_per_kwh_all_in) and the 2026-05-19 invoice-display fix."""
    # _make_session sets the Tariff with rate=20 and gst=18, so rate_gst_included
    # is auto-computed by the helper as rate × 1.18 = 23.6000.
    _, _, txn, _, _ = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.rate_gst_included == Decimal("23.6000"), (
        "Invoice should snapshot Tariff.rate_gst_included verbatim "
        "(not derived from amounts)."
    )


@pytest.mark.asyncio
async def test_qr_invoice_gateway_line_uses_actual_razorpay_fee(client):
    """Gateway line on the invoice is the ACTUAL Razorpay fee stored on the
    QRPayment row (razorpay_commission = taxable, razorpay_gst = tax), NOT a
    synthetic 2% of amount_paid. See ADR 0026.

    For this fixture: commission=₹0.20, GST=₹0.04 (actual fee ₹0.24).
    """
    _, _, txn, _, qr_payment = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    # Invoice gateway line == actual Razorpay fee from the QRPayment row.
    assert invoice.gateway_charges == qr_payment.razorpay_commission
    assert invoice.gateway_charges == Decimal("0.20")
    assert invoice.gateway_gst == qr_payment.razorpay_gst
    assert invoice.gateway_gst == Decimal("0.04")
    assert (
        invoice.total_taxable_value
        == txn.energy_charge + Decimal("0.20")
    )
    assert invoice.cgst_amount == invoice.sgst_amount  # equal halves (ADR 0017)
    assert invoice.total_tax + invoice.round_off == txn.gst_amount + Decimal("0.04")


@pytest.mark.asyncio
async def test_cgst_sgst_independent_equal_with_round_off(client):
    """ADR 0017: intra-state CGST and SGST are each computed independently from
    the taxable value (= round(total_taxable × 9%)), so they're EQUAL — never
    the old asymmetric halve-the-total. The Round Off line absorbs the paisa
    residual so the invoice still reconciles exactly:
    total_taxable + total_tax + round_off == total_amount."""
    _, _, txn, _, _ = await _make_session(with_qr=True)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice.is_inter_state is False
    # Two equal, independently-derived levies.
    assert invoice.cgst_amount == invoice.sgst_amount
    expected_half = (
        invoice.total_taxable_value * Decimal("9") / Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert invoice.cgst_amount == expected_half
    assert invoice.total_tax == invoice.cgst_amount + invoice.sgst_amount
    # Reconciliation invariant — Round Off makes the totals add up exactly.
    assert (
        invoice.total_taxable_value + invoice.total_tax + invoice.round_off
        == invoice.total_amount
    )
    # Residual is sub-rupee.
    assert abs(invoice.round_off) <= Decimal("0.02")


@pytest.mark.asyncio
async def test_missing_gstin_blocks_issuance(client, monkeypatch):
    """Without a supplier GSTIN, no invoice is issued (CGST Rule 46)."""
    monkeypatch.setattr(_svc, "VOLTLYNC_GSTIN", "")

    _, _, txn, _, _ = await _make_session()
    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRoleEnum.ADMIN, UserRoleEnum.FRANCHISEE])
async def test_internal_role_session_skips_invoice(client, role):
    """ADMIN and FRANCHISEE-initiated sessions are operational, not sales —
    no GST invoice is issued and no invoice number is consumed."""
    _, _, txn, user, _ = await _make_session()
    user.role = role
    await user.save()

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_idempotent_generation(client):
    """Calling generate_invoice twice for the same txn yields the same row."""
    _, _, txn, _, _ = await _make_session()

    first = await InvoiceService.generate_invoice(txn.id)
    second = await InvoiceService.generate_invoice(txn.id)

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 1


@pytest.mark.asyncio
async def test_place_of_supply_frozen_on_invoice(client):
    """place_of_supply_state_code captures the station's state at issue time."""
    _, _, txn, _, _ = await _make_session(station_state_code="29")

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice.place_of_supply_state_code == "29"
    # supplier is VoltLync default state_code=32 → inter-state
    assert invoice.is_inter_state is True
    assert invoice.igst_amount == invoice.total_tax
    assert invoice.round_off == Decimal("0")  # single IGST component, no residual (ADR 0017)
    assert invoice.cgst_amount is None
    assert invoice.sgst_amount is None


@pytest.mark.asyncio
async def test_qr_invoice_kwh_is_billable_not_actual(client):
    """When QR over-consumption was capped, the invoice shows the billable
    kWh (capped), not the actual meter reading. Line-item math reconciles.

    The transaction's energy_consumed_kwh stays as the meter reading; the
    invoice's energy_consumed_kwh is derived from energy_charge / rate so
    that `kWh × rate = total_amount`.
    """
    # rate 20, energy_charge capped at 16.75 (as if process_qr_session_billing
    # capped it). Actual meter reading was 5.0 kWh.
    rate = Decimal("20.00")
    actual_kwh = 5.0
    capped_energy_charge = Decimal("16.75")
    capped_gst = Decimal("3.02")  # 16.75 * 18% rounded

    _, _, txn, _, _ = await _make_session(
        rate=rate, energy_kwh=actual_kwh, with_qr=True
    )
    # Overwrite the txn billing fields to simulate the cap having run.
    await Transaction.filter(id=txn.id).update(
        energy_charge=capped_energy_charge,
        gst_amount=capped_gst,
        total_billed=capped_energy_charge + capped_gst,
    )

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    # billable_kwh = 16.75 / 20 = 0.838 (rounded to 3dp)
    assert float(invoice.energy_consumed_kwh) == pytest.approx(0.838, abs=0.001)
    # Actual meter reading on the transaction is preserved.
    await txn.refresh_from_db()
    assert float(txn.energy_consumed_kwh) == pytest.approx(actual_kwh, abs=0.001)
    # Energy line-item math reconciles: billable_kwh × rate_incl_tax should
    # equal the energy taxable + GST (excluding the separate gateway line).
    energy_incl_tax = capped_energy_charge + capped_gst
    reconciled = invoice.energy_consumed_kwh * invoice.tariff_rate_incl_tax
    assert abs(reconciled - energy_incl_tax) < Decimal("0.05")


async def _make_franchisee(business_name="Some Franchisee Pvt Ltd",
                            gstin="29ZZZZZ9999Z1Z5", state_code="29"):
    """Create a Franchisee fixture for the substore tests."""
    from datetime import date
    from decimal import Decimal as D
    from models import Franchisee, FranchiseeStatusEnum
    import uuid as _uuid
    suffix = _uuid.uuid4().hex[:6]
    return await Franchisee.create(
        business_name=business_name,
        contact_name=f"Contact {suffix}",
        contact_email=f"{suffix}@franchisee.test",
        contact_phone=f"9{_uuid.uuid4().int % 1000000000:09d}",
        gstin=gstin,
        address=f"Test address {suffix}",
        state="Karnataka" if state_code == "29" else "Kerala",
        state_code=state_code,
        commission_percent=D("20.00"),
        tds_rate_percent=D("10.00"),
        commission_effective_from=date.today(),
        status=FranchiseeStatusEnum.ACTIVE,
    )


@pytest.mark.asyncio
async def test_franchisee_owned_station_invoice_has_voltlync_supplier(client):
    """Sessions at franchisee-owned stations: VoltLync remains the GST supplier,
    the franchisee is snapshotted as the operator (for the 'Operated by' block),
    and the invoice number carries the F{franchisee_id} segment."""
    franchisee = await _make_franchisee()

    _, _, txn, _, _ = await _make_session(franchisee=franchisee)
    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    # Supplier = VoltLync (GST merchant-of-record), NOT the franchisee
    assert invoice.supplier_name == "VOLTLYNC PRIVATE LIMITED"
    assert invoice.supplier_gstin == "32ABCDE1234F1Z5"
    assert invoice.supplier_state_code == "32"
    # Franchisee identity snapshotted for the "Operated by" disclosure
    assert invoice.franchisee_id == franchisee.id
    assert invoice.franchisee_business_name == "Some Franchisee Pvt Ltd"
    assert invoice.franchisee_gstin == "29ZZZZZ9999Z1Z5"
    assert invoice.franchisee_state_code == "29"
    # Invoice number carries the F{id} segment per substore model
    assert invoice.invoice_number.startswith(f"VL/F{franchisee.id}/WAL/")


@pytest.mark.asyncio
async def test_voltlync_owned_station_invoice_no_franchisee_block(client):
    """VoltLync-owned stations: franchisee snapshot columns are NULL; invoice
    number has no F-segment. The PDF then omits the 'Operated by' block."""
    _, _, txn, _, _ = await _make_session(franchisee=None)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert invoice.franchisee_id is None
    assert invoice.franchisee_business_name is None
    assert invoice.franchisee_gstin is None
    assert invoice.invoice_number.startswith("VL/WAL/")
    assert "/F" not in invoice.invoice_number


@pytest.mark.asyncio
async def test_per_franchisee_counter_isolation(client):
    """Each franchisee has its own running sequence per (series, FY).
    Two invoices from franchisee A and one from franchisee B should give
    A: 00001, 00002 and B: 00001 independently."""
    franchisee_a = await _make_franchisee(
        business_name="A Pvt Ltd", gstin="29AAAAA1111A1Z1", state_code="29"
    )
    franchisee_b = await _make_franchisee(
        business_name="B Pvt Ltd", gstin="32BBBBB2222B1Z2", state_code="32"
    )

    _, _, txn_a1, _, _ = await _make_session(franchisee=franchisee_a)
    inv_a1 = await InvoiceService.generate_invoice(txn_a1.id)
    _, _, txn_a2, _, _ = await _make_session(franchisee=franchisee_a)
    inv_a2 = await InvoiceService.generate_invoice(txn_a2.id)
    _, _, txn_b1, _, _ = await _make_session(franchisee=franchisee_b)
    inv_b1 = await InvoiceService.generate_invoice(txn_b1.id)

    assert inv_a1.invoice_number.endswith("/00001")
    assert inv_a2.invoice_number.endswith("/00002")
    assert inv_b1.invoice_number.endswith("/00001")
    assert f"/F{franchisee_a.id}/" in inv_a1.invoice_number
    assert f"/F{franchisee_b.id}/" in inv_b1.invoice_number


@pytest.mark.asyncio
async def test_invoice_total_plus_refund_equals_amount_paid(client):
    """Prepaid invariant: for QR invoices, total_amount + refund_amount
    equals the gross UPI payment (transaction_amount = amount_paid). Holds
    once the MINIMUM_REFUND_AMOUNT threshold is gone — every paisa is
    accounted for either as billed line items or as a refund."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True, energy_kwh=0.5)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    reconciled = (invoice.total_amount or Decimal("0")) + (invoice.refund_amount or Decimal("0"))
    assert abs(reconciled - invoice.transaction_amount) <= Decimal("0.02")
    assert invoice.transaction_amount == qr_payment.amount_paid


@pytest.mark.asyncio
async def test_fault_refund_session_issues_no_invoice(client):
    """Regression (invoice 61 / VL/F3/QR/202627/00061): a QR session that
    ended FAILED after delivering 0 < energy < 0.5 kWh is fully refunded and
    its billing breakdown is never written (energy_charge stays 0, per the
    ADR 0013 fault-refund band in QRPaymentService._refund_if_non_billable).

    No GST invoice should be issued for a fully-refunded, non-billed session —
    issuing one asserts a taxable supply (the synthetic gateway fee + GST) that
    was in fact returned to the customer. The pre-existing `energy <= 0` guard
    in generate_invoice protects the zero-energy full-refund band but NOT this
    fault-refund band, because it checks *metered* kWh (0.19 > 0) rather than
    the *billed* amount (energy_charge == 0)."""
    rate = Decimal("25.00")
    _, _, txn, _, qr_payment = await _make_session(
        rate=rate, energy_kwh=0.19, with_qr=True
    )
    # Simulate the fault-refund outcome: FAILED, billing skipped (energy_charge
    # / gst zeroed), and the full ₹50 payment refunded to the customer.
    await Transaction.filter(id=txn.id).update(
        transaction_status=TransactionStatusEnum.FAILED,
        energy_charge=Decimal("0"),
        gst_amount=Decimal("0"),
        total_billed=Decimal("0"),
    )
    await QRPayment.filter(id=qr_payment.id).update(
        amount_paid=Decimal("50.00"),
        refund_amount=Decimal("50.00"),
        energy_cost=Decimal("0"),
        gst_amount=Decimal("0"),
        status=QRPaymentStatusEnum.REFUNDED,
    )

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None, (
        "A fully-refunded fault session must not produce a GST invoice — "
        "it asserts a taxable gateway supply that was refunded."
    )
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_goodwill_full_refund_of_billed_session_issues_no_invoice(client):
    """Net-retained guard (stricter than energy_charge alone): a QR session that
    DID bill energy but was later fully refunded (e.g. a goodwill/admin refund)
    has net retained = amount_paid - refund_amount = 0, so no invoice is issued.
    This is the case the net-retained form catches that a bare `energy_charge > 0`
    guard would not."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True, energy_kwh=0.5)
    # energy_charge stays > 0 (real billing happened), but the whole payment is
    # returned — net retained collapses to zero.
    await QRPayment.filter(id=qr_payment.id).update(
        refund_amount=qr_payment.amount_paid,
        status=QRPaymentStatusEnum.REFUNDED,
    )

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None, (
        "A fully-refunded billed session (net retained == 0) must not produce "
        "a GST invoice, even though energy_charge > 0."
    )
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_wallet_zero_billed_session_issues_no_invoice(client):
    """Wallet sessions (no QRPayment) gate on total_billed: a metered session
    that somehow billed nothing (total_billed == 0) issues no invoice."""
    _, _, txn, _, _ = await _make_session(energy_kwh=1.0)
    await Transaction.filter(id=txn.id).update(
        energy_charge=Decimal("0"),
        gst_amount=Decimal("0"),
        total_billed=Decimal("0"),
    )

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is None
    assert await GSTInvoice.filter(transaction_id=txn.id).count() == 0


@pytest.mark.asyncio
async def test_partial_refund_session_still_issues_invoice(client):
    """Guardrail: a normal partially-refunded QR session (net retained > 0) still
    issues an invoice, and the prepaid invariant holds. Ensures the net-retained
    guard doesn't over-suppress."""
    _, _, txn, _, qr_payment = await _make_session(with_qr=True, energy_kwh=0.5)

    invoice = await InvoiceService.generate_invoice(txn.id)

    assert invoice is not None
    assert qr_payment.refund_amount < qr_payment.amount_paid  # partial refund
    reconciled = (invoice.total_amount or Decimal("0")) + (
        invoice.refund_amount or Decimal("0")
    )
    assert abs(reconciled - invoice.transaction_amount) <= Decimal("0.02")


@pytest.mark.asyncio
async def test_invoice_gateway_gst_uses_actual_razorpay_gst(client):
    """generate_invoice writes gateway_gst from the ACTUAL Razorpay fee on the
    QRPayment row (qr_payment.razorpay_gst), NOT a synthetic 2% split. Wallet
    sessions (no qr_payment) leave gateway_gst NULL. See ADR 0026."""
    _, _, qr_txn, _, qr_payment = await _make_session(with_qr=True)
    qr_invoice = await InvoiceService.generate_invoice(qr_txn.id)

    assert qr_invoice is not None
    # Invoice gateway_gst == actual Razorpay GST from the QRPayment row (₹0.04)
    assert qr_invoice.gateway_gst == qr_payment.razorpay_gst
    assert qr_invoice.gateway_gst == Decimal("0.04")

    _, _, wallet_txn, _, _ = await _make_session()
    wallet_invoice = await InvoiceService.generate_invoice(wallet_txn.id)

    assert wallet_invoice is not None
    assert wallet_invoice.gateway_gst is None


# ============================================================================
# IST invoice date / financial year (ADR 0012)
# ============================================================================

@pytest.mark.asyncio
async def test_line_items_intra_state_allocation_sums_to_stored(client):
    """ADR 0024: per-line SGST/CGST are a display allocation of the stored
    total-level tax. Each head must sum back to the stored amount (gateway line
    absorbs the residual), and the line totals reconcile to the grand total."""
    from services.invoice_service import build_invoice_line_items

    _, _, txn, _, _ = await _make_session(with_qr=True, energy_kwh=1.0)
    invoice = await InvoiceService.generate_invoice(txn.id)
    items = build_invoice_line_items(invoice)

    assert [i["label"] for i in items] == ["Energy", "Gateway charges"]
    # Tax heads intra-state are SGST + CGST on every line.
    assert [name for name, _, _ in items[0]["taxes"]] == ["SGST", "CGST"]

    def head_sum(head):
        return sum(amt for i in items for name, _, amt in i["taxes"] if name == head)

    assert head_sum("SGST") == invoice.sgst_amount
    assert head_sum("CGST") == invoice.cgst_amount
    # Energy rate is derived taxable ÷ qty (== rate_per_kwh), 2 dp.
    assert items[0]["rate"] == (
        invoice.energy_taxable_value / invoice.energy_consumed_kwh
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)
    # Line total = taxable + its allocated tax; sum reconciles to grand total.
    for i in items:
        assert i["line_total"] == i["taxable"] + sum(a for _, _, a in i["taxes"])
    sub_total = sum(i["line_total"] for i in items)
    assert sub_total + (invoice.round_off or Decimal("0")) == invoice.total_amount


def test_line_items_gateway_absorbs_rounding_residual():
    """The residual-absorption is load-bearing, not incidental: pick taxable
    values where naive per-line rounding would NOT sum to the stored total, and
    assert the gateway line absorbs the difference so the head still sums exactly.

    energy=0.05, gateway=0.05 @ 9%: naive round(0.05×9%)=0.00 on BOTH lines → 0.00,
    but the stored total is round(0.10×9%)=0.01. Gateway must carry the 0.01."""
    from types import SimpleNamespace
    from services.invoice_service import build_invoice_line_items

    inv = SimpleNamespace(
        is_inter_state=False,
        sgst_rate=Decimal("9.00"), sgst_amount=Decimal("0.01"),
        cgst_rate=Decimal("9.00"), cgst_amount=Decimal("0.01"),
        igst_rate=None, igst_amount=None,
        energy_taxable_value=Decimal("0.05"), gateway_charges=Decimal("0.05"),
        energy_consumed_kwh=Decimal("0.010"),
        hsn_sac_code="996749", gateway_hsn_code="997158",
    )
    energy, gateway = build_invoice_line_items(inv)
    # Energy rounds to 0.00; gateway absorbs the full 0.01 residual.
    assert dict((n, a) for n, _, a in energy["taxes"]) == {"SGST": Decimal("0.00"), "CGST": Decimal("0.00")}
    assert dict((n, a) for n, _, a in gateway["taxes"]) == {"SGST": Decimal("0.01"), "CGST": Decimal("0.01")}
    # Heads still sum exactly to the stored totals.
    assert energy["taxes"][0][2] + gateway["taxes"][0][2] == inv.sgst_amount
    assert energy["taxes"][1][2] + gateway["taxes"][1][2] == inv.cgst_amount


@pytest.mark.asyncio
async def test_line_items_inter_state_uses_single_igst_head(client):
    """Inter-state invoices allocate a single IGST head per line, summing to the
    stored igst_amount."""
    from services.invoice_service import build_invoice_line_items

    _, _, txn, _, _ = await _make_session(with_qr=True, station_state_code="29")
    invoice = await InvoiceService.generate_invoice(txn.id)
    assert invoice.is_inter_state is True
    items = build_invoice_line_items(invoice)

    assert all([name for name, _, _ in i["taxes"]] == ["IGST"] for i in items)
    igst_sum = sum(amt for i in items for _, _, amt in i["taxes"])
    assert igst_sum == invoice.igst_amount


@pytest.mark.asyncio
async def test_line_items_wallet_has_single_energy_line(client):
    """Wallet sessions have no gateway line — a single Energy item."""
    from services.invoice_service import build_invoice_line_items

    _, _, txn, _, _ = await _make_session(energy_kwh=2.0)  # no QR → wallet
    invoice = await InvoiceService.generate_invoice(txn.id)
    items = build_invoice_line_items(invoice)

    assert len(items) == 1
    assert items[0]["label"] == "Energy"


@pytest.mark.asyncio
async def test_itemised_pdf_renders_for_all_variants(client):
    """generate_pdf produces a valid PDF for intra-state QR, inter-state QR, and
    wallet invoices with the new itemised table."""
    intra_txn = (await _make_session(with_qr=True))[2]
    inter_txn = (await _make_session(with_qr=True, station_state_code="29"))[2]
    wallet_txn = (await _make_session())[2]
    for txn in (intra_txn, inter_txn, wallet_txn):
        invoice = await InvoiceService.generate_invoice(txn.id)
        pdf = InvoiceService.generate_pdf(invoice)
        assert pdf[:4] == b"%PDF"


def test_energy_billed_kwh_renders_at_milli_precision():
    """Regression (invoice 60): the "ENERGY BILLED (kWh)" cell must render at 3
    decimals. A sub-0.1 kWh session previously rendered "0.0" (1 dp) next to a
    non-zero amount, which reads as "billed for zero energy". Milli-precision
    also keeps `tariff × kWh = amount` reconciling on the page."""
    from services.invoice_service import _format_energy_billed_kwh

    # The exact invoice-60 case: 0.02 kWh must not collapse to "0.0".
    assert _format_energy_billed_kwh(Decimal("0.02")) == "0.020"
    assert _format_energy_billed_kwh(Decimal("0.188")) == "0.188"
    # Always 3 decimal places, even for whole/large values.
    assert _format_energy_billed_kwh(Decimal("2")) == "2.000"
    assert _format_energy_billed_kwh(Decimal("15.5")) == "15.500"


def test_to_ist_treats_naive_as_utc_and_crosses_day():
    from datetime import datetime, timezone
    from utils import to_ist

    # 2026-03-31 20:00 UTC == 2026-04-01 01:30 IST
    naive = datetime(2026, 3, 31, 20, 0, 0)
    ist = to_ist(naive)
    assert ist.strftime("%Y-%m-%d") == "2026-04-01"
    assert ist.utcoffset().total_seconds() == 5.5 * 3600

    aware = datetime(2026, 3, 31, 20, 0, 0, tzinfo=timezone.utc)
    assert to_ist(aware).strftime("%Y-%m-%d") == "2026-04-01"
    assert to_ist(None) is None


def test_financial_year_rolls_at_ist_midnight_not_utc():
    from datetime import datetime
    from utils import to_ist
    from services.invoice_service import _get_financial_year

    # Issued 2026-03-31 20:00 UTC. In UTC that's still FY 2025-26; in IST it's
    # 2026-04-01 01:30 -> FY 2026-27. The fix derives FY from IST.
    boundary = datetime(2026, 3, 31, 20, 0, 0)
    assert _get_financial_year(boundary) == "2025-26"            # old UTC behaviour
    assert _get_financial_year(to_ist(boundary)) == "2026-27"    # new IST behaviour

    # A pre-IST-midnight instant stays in the old FY either way.
    before = datetime(2026, 3, 31, 17, 0, 0)  # IST 22:30, still 31 Mar
    assert _get_financial_year(to_ist(before)) == "2025-26"


@pytest.mark.asyncio
async def test_csv_export_renders_invoice_date_in_ist(client_admin):
    """The GSTR-1 CSV must emit the IST calendar date, not the stored UTC one."""
    from datetime import datetime
    from models import GSTInvoice

    _, _, txn, _, _ = await _make_session(energy_kwh=2.0)
    invoice = await InvoiceService.generate_invoice(txn.id)
    assert invoice is not None

    # Force a boundary issue instant: 2026-04-30 20:00 UTC == 2026-05-01 01:30 IST
    await GSTInvoice.filter(id=invoice.id).update(
        invoice_date=datetime(2026, 4, 30, 20, 0, 0),
    )

    resp = await client_admin.get("/api/admin/invoices/export.csv")
    assert resp.status_code == 200
    body = resp.text
    # Legal (IST) date is 2026-05-01, and no raw UTC instant leaks into the column.
    assert "2026-05-01" in body
    assert "2026-04-30T20:00:00" not in body
