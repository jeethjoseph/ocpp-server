"""Itemised /my-charges receipt card breakdown (ADR 0024 / itemised-gst-invoice #02).

`_customer_breakdown` returns tax-inclusive per-line `line_items` (Energy, Gateway
charges) plus a `bill_total` mirroring the invoice's Line total column, summing to
`amount_paid − refund`. Verified for the invoice path (reuses the shared
`build_invoice_line_items`), the pre-invoice synthetic fallback, and the no-billing
case.
"""
from decimal import Decimal
from types import SimpleNamespace

from routers.public_qr_transactions import _customer_breakdown


def _full_invoice():
    return SimpleNamespace(
        energy_consumed_kwh=Decimal("3.065"),
        energy_taxable_value=Decimal("63.64"),
        gateway_charges=Decimal("1.69"), gateway_gst=Decimal("0.31"),
        is_inter_state=False,
        sgst_rate=Decimal("9.00"), sgst_amount=Decimal("5.88"),
        cgst_rate=Decimal("9.00"), cgst_amount=Decimal("5.88"),
        igst_rate=None, igst_amount=None,
        total_tax=Decimal("11.76"), total_amount=Decimal("77.09"),
        transaction_amount=Decimal("100.00"),
        hsn_sac_code="996749", gateway_hsn_code="997158",
    )


def test_invoice_path_returns_line_totals_summing_to_bill_total():
    b = _customer_breakdown(
        SimpleNamespace(amount_paid=Decimal("100.00")), txn=None, invoice=_full_invoice()
    )
    assert b["line_items"] == [
        {"label": "Energy", "amount": "75.10"},          # 63.64 + 5.73 + 5.73
        {"label": "Gateway charges", "amount": "1.99"},  # 1.69 + 0.15 + 0.15
    ]
    assert b["bill_total"] == "77.09"
    assert sum(Decimal(i["amount"]) for i in b["line_items"]) == Decimal(b["bill_total"])


def test_inter_state_invoice_still_yields_two_line_items():
    inv = _full_invoice()
    inv.is_inter_state = True
    inv.sgst_rate = inv.sgst_amount = inv.cgst_rate = inv.cgst_amount = None
    inv.igst_rate, inv.igst_amount = Decimal("18.00"), Decimal("11.76")
    b = _customer_breakdown(SimpleNamespace(amount_paid=Decimal("100.00")), txn=None, invoice=inv)
    assert [i["label"] for i in b["line_items"]] == ["Energy", "Gateway charges"]
    assert sum(Decimal(i["amount"]) for i in b["line_items"]) == Decimal(b["bill_total"])


def test_fallback_without_invoice_returns_line_items():
    txn = SimpleNamespace(
        energy_consumed_kwh=Decimal("3.065"),
        energy_charge=Decimal("63.64"), gst_amount=Decimal("11.46"),
    )
    b = _customer_breakdown(SimpleNamespace(amount_paid=Decimal("100.00")), txn=txn, invoice=None)
    assert b["line_items"] == [
        {"label": "Energy", "amount": "75.10"},
        {"label": "Gateway charges", "amount": "2.00"},
    ]
    assert b["bill_total"] == "77.10"


def test_no_billing_returns_empty_line_items():
    txn = SimpleNamespace(energy_consumed_kwh=Decimal("2.0"), energy_charge=None, gst_amount=None)
    b = _customer_breakdown(SimpleNamespace(amount_paid=Decimal("50.00")), txn=txn, invoice=None)
    assert b["line_items"] == [] and b["bill_total"] is None
