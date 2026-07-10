"""Tests for the admin Reports endpoints (QR churn cohorts).

The report is computed live (ADR 0025). These tests seed QR payments with
back-dated `created_at` to form real weekly cohorts and assert the cohort /
summary shape, plus the auth gate and grain validation.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from models import (
    Charger,
    ChargerQRCode,
    ChargingStation,
    QRPayment,
    QRPaymentStatusEnum,
    User,
)

W0 = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)  # a Monday
W1 = datetime(2026, 3, 23, 12, 0, tzinfo=timezone.utc)  # +1 week


async def _charger():
    station = await ChargingStation.create(name="S", state="Kerala", state_code="32")
    return await Charger.create(
        charge_point_string_id=f"c-{uuid.uuid4().hex[:8]}",
        station=station,
        latest_status="Available",
    )


async def _payment(qr, charger, *, vpa, when, status=QRPaymentStatusEnum.COMPLETED,
                   amount="20.00", refund=None):
    user = await User.create(
        email=f"qp_{uuid.uuid4().hex[:6]}@v.test",
        phone_number=f"9{uuid.uuid4().int % 1000000000:09d}",
    )
    p = await QRPayment.create(
        charger=charger, charger_qr_code=qr, user=user,
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_qr_code_id=qr.razorpay_qr_code_id,
        amount_paid=Decimal(amount), customer_vpa=vpa, status=status,
        refund_amount=Decimal(refund) if refund is not None else None,
    )
    # created_at is auto_now_add on create; overwrite it to place the cohort.
    await QRPayment.filter(id=p.id).update(created_at=when)
    return p


async def _seed_two_customers(charger):
    qr = await ChargerQRCode.create(
        charger=charger, razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://x/qr.png", is_active=True,
    )
    # Customer A: charges in W0 and again in W1 (a repeat).
    await _payment(qr, charger, vpa="a@oksbi", when=W0)
    await _payment(qr, charger, vpa="a@oksbi", when=W1)
    # Customer B: charges once, in W0 (one-time).
    await _payment(qr, charger, vpa="b@oksbi", when=W0)


@pytest.mark.asyncio
async def test_requires_admin(client):
    """Unauthenticated / non-admin callers are rejected, not served."""
    res = await client.get("/api/admin/reports/qr-churn?grain=week")
    assert res.status_code in (401, 403)


@pytest.mark.asyncio
async def test_rejects_bad_grain(client_admin):
    res = await client_admin.get("/api/admin/reports/qr-churn?grain=daily")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_weekly_cohort_shape(client_admin):
    await _seed_two_customers(await _charger())

    res = await client_admin.get("/api/admin/reports/qr-churn?grain=week")
    assert res.status_code == 200
    body = res.json()

    assert body["grain"] == "week"
    s = body["summary"]
    assert s["customers"] == 2
    assert s["one_time"] == 1
    assert s["repeat"] == 1
    assert s["avg_sessions"] == "1.50"  # (2 + 1) / 2
    assert s["successful_sessions"] == 3

    # One cohort (the W0 week), size 2, with a repeat visible at offset 1.
    assert body["max_offset"] == 1
    assert len(body["cohorts"]) == 1
    cohort = body["cohorts"][0]
    assert cohort["cohort"] == "2026-03-16"
    assert cohort["size"] == 2
    cells = {c["offset"]: c["active"] for c in cohort["cells"]}
    assert cells[0] == 2  # both customers active in week 0
    assert cells[1] == 1  # only customer A returned in week 1


@pytest.mark.asyncio
async def test_cohorts_bucket_in_ist_not_utc(client_admin):
    """A charge at 01:30 IST on 1 Mar (= 2026-02-28 20:00 UTC) must land in the
    March cohort. Guards against UTC-based date_trunc (would file it in Feb)."""
    charger = await _charger()
    qr = await ChargerQRCode.create(
        charger=charger, razorpay_qr_code_id=f"qr_{uuid.uuid4().hex[:8]}",
        image_url="https://x/qr.png", is_active=True,
    )
    just_after_ist_midnight = datetime(2026, 2, 28, 20, 0, tzinfo=timezone.utc)
    await _payment(qr, charger, vpa="c@oksbi", when=just_after_ist_midnight)

    res = await client_admin.get("/api/admin/reports/qr-churn?grain=month")
    assert res.status_code == 200
    assert res.json()["cohorts"][0]["cohort"] == "2026-03-01"


@pytest.mark.asyncio
async def test_monthly_grain_collapses_to_one_offset(client_admin):
    """W0 and W1 fall in the same calendar month, so monthly grain sees the
    repeat as same-period (offset 0), not a later cohort period."""
    await _seed_two_customers(await _charger())

    res = await client_admin.get("/api/admin/reports/qr-churn?grain=month")
    assert res.status_code == 200
    body = res.json()
    assert body["grain"] == "month"
    assert body["max_offset"] == 0
    assert body["cohorts"][0]["cohort"] == "2026-03-01"
    assert body["summary"]["customers"] == 2
