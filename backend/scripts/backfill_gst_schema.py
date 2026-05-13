"""Backfill existing GST invoices and tariffs after migrations 27 + 28.

Migration 27 added new columns and inline-backfilled series + financial_year.
Migration 28 renumbered invoices and normalized supplier_name/state/state_code.
This script handles what those migrations can't (env-var-dependent values and
multi-table joins):

  1. place_of_supply_state_code  ← station.state_code (via txn → charger → station)
  2. transaction_amount          ← amount_paid - refund_amount  (QR rows only)
  3. energy_taxable_value        ← txn.energy_charge            (no /1.18 reverse-calc)
  4. gateway_charges             ← qr_payment.razorpay_commission
  5. total_taxable_value         ← energy_taxable + gateway_taxable
  6. cgst/sgst/igst amounts      ← from txn.gst_amount + qr_payment.razorpay_gst
  7. total_tax, total_amount     ← recomputed
  8. hsn_sac_code                ← '996749' (corrected SAC)
  9. supplier_gstin              ← VOLTLYNC_GSTIN env var (migration 28 can't read env)
 10. supplier_name/state/state_code ← env vars (redundant with migration 28; safety net)
 11. supplier_address            ← VOLTLYNC_ADDRESS env var
 12. tariff.hsn_sac_code         ← '996749' where NULL

Usage:
  docker exec ocpp-backend python -m backend.scripts.backfill_gst_schema [--dry-run]
"""

import asyncio
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

from tortoise import Tortoise

# Allow running via `python -m backend.scripts.backfill_gst_schema`
sys.path.insert(0, "/app")

from scripts._db import build_tortoise_config
from models import (
    Charger,
    ChargingStation,
    Franchisee,
    GSTInvoice,
    QRPayment,
    Tariff,
    Transaction,
)

TWO_DP = Decimal("0.01")
CORRECTED_HSN = "996749"

VOLTLYNC_NAME = os.getenv("VOLTLYNC_BUSINESS_NAME", "VOLTLYNC PRIVATE LIMITED")
VOLTLYNC_GSTIN = os.getenv("VOLTLYNC_GSTIN", "")
VOLTLYNC_ADDRESS = os.getenv("VOLTLYNC_ADDRESS", "")
VOLTLYNC_STATE = os.getenv("VOLTLYNC_STATE", "Kerala")
VOLTLYNC_STATE_CODE = os.getenv("VOLTLYNC_STATE_CODE", "32")


def _split_tax(total_tax: Decimal, is_inter: bool) -> dict:
    if is_inter:
        return {
            "cgst_amount": None, "sgst_amount": None,
            "igst_amount": total_tax,
        }
    half = (total_tax / 2).quantize(TWO_DP, ROUND_HALF_UP)
    return {
        "cgst_amount": half,
        "sgst_amount": total_tax - half,
        "igst_amount": None,
    }


async def backfill_invoice(invoice: GSTInvoice, dry_run: bool) -> dict:
    txn = await Transaction.filter(id=invoice.transaction_id).first()
    if not txn:
        return {"id": invoice.id, "skipped": "no transaction"}

    charger = await Charger.filter(id=txn.charger_id).first()
    station = await ChargingStation.filter(id=charger.station_id).first() if charger else None
    place_of_supply = station.state_code if station else None

    qr_payment = await QRPayment.filter(transaction_id=txn.id).first()

    energy_taxable = txn.energy_charge or Decimal("0")
    energy_tax = txn.gst_amount or Decimal("0")
    gateway_taxable = qr_payment.razorpay_commission if qr_payment else Decimal("0")
    gateway_tax = qr_payment.razorpay_gst if qr_payment else Decimal("0")

    total_taxable = energy_taxable + (gateway_taxable or Decimal("0"))
    total_tax = energy_tax + (gateway_tax or Decimal("0"))
    total_amount = total_taxable + total_tax

    # Gross/refund split — restored to two-line model per the substore plan.
    # `transaction_amount` is the gross UPI payment; `refund_amount` is the
    # amount returned to the customer (NULL for wallet).
    if qr_payment:
        transaction_amount = qr_payment.amount_paid or Decimal("0")
        refund_amount = qr_payment.refund_amount or Decimal("0")
    else:
        transaction_amount = txn.total_billed
        refund_amount = None

    tax_split = _split_tax(total_tax, invoice.is_inter_state)

    update_fields = {
        "place_of_supply_state_code": place_of_supply,
        "energy_taxable_value": energy_taxable,
        "gateway_charges": gateway_taxable or Decimal("0"),
        "total_taxable_value": total_taxable,
        "cgst_amount": tax_split["cgst_amount"],
        "sgst_amount": tax_split["sgst_amount"],
        "igst_amount": tax_split["igst_amount"],
        "total_tax": total_tax,
        "total_amount": total_amount,
        "transaction_amount": transaction_amount,
        "refund_amount": refund_amount,
        "hsn_sac_code": CORRECTED_HSN,
        "gst_rate_percent": invoice.gst_rate_percent or Decimal("18"),
        # Supplier identity — always VoltLync. Migration 28 already normalized
        # name/state/state_code; we re-write here for safety and to set
        # supplier_gstin + supplier_address from env vars (which the migration
        # SQL can't read).
        "supplier_name": VOLTLYNC_NAME,
        "supplier_gstin": VOLTLYNC_GSTIN or invoice.supplier_gstin,
        "supplier_address": VOLTLYNC_ADDRESS or invoice.supplier_address,
        "supplier_state": VOLTLYNC_STATE,
        "supplier_state_code": VOLTLYNC_STATE_CODE,
    }

    # Franchisee operator snapshot for the "Operated by" PDF block. Migration
    # 29 backfills these inline; we re-write here so re-runs against a
    # partially-migrated DB stay consistent.
    if invoice.franchisee_id:
        franchisee = await Franchisee.filter(id=invoice.franchisee_id).first()
        if franchisee:
            update_fields["franchisee_business_name"] = franchisee.business_name
            update_fields["franchisee_gstin"]         = franchisee.gstin
            update_fields["franchisee_address"]       = franchisee.address
            update_fields["franchisee_state"]         = franchisee.state
            update_fields["franchisee_state_code"]    = franchisee.state_code

    summary = {"id": invoice.id, "number": invoice.invoice_number, **{
        k: str(v) for k, v in update_fields.items()
    }}

    if not dry_run:
        await GSTInvoice.filter(id=invoice.id).update(**update_fields)

    return summary


async def backfill_tariffs(dry_run: bool) -> int:
    qs = Tariff.filter(hsn_sac_code__isnull=True)
    count = await qs.count()
    if not dry_run and count:
        await qs.update(hsn_sac_code=CORRECTED_HSN)
    return count


async def main():
    dry_run = "--dry-run" in sys.argv

    await Tortoise.init(config=build_tortoise_config())
    try:
        invoices = await GSTInvoice.all()
        print(f"Backfilling {len(invoices)} invoice rows (dry_run={dry_run})")
        for inv in invoices:
            result = await backfill_invoice(inv, dry_run)
            print(f"  invoice {result['id']}: {result.get('number')} → "
                  f"taxable={result.get('total_taxable_value')} "
                  f"tax={result.get('total_tax')} "
                  f"total={result.get('total_amount')} "
                  f"pos={result.get('place_of_supply_state_code')}")

        tariff_count = await backfill_tariffs(dry_run)
        print(f"Tariff HSN backfill: {tariff_count} rows updated")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
