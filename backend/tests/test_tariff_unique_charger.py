"""Regression tests for upsert-race-hardening issue 01.

A charger may hold at most one charger-specific Tariff, enforced by
UNIQUE(charger_id) (migration 47). Global tariffs (charger_id NULL) may still
coexist because Postgres treats NULLs as distinct. The admin tariff write path
(`_upsert_charger_tariff`) resolves a lost concurrent-create race as an update
rather than surfacing a 500 / MultipleObjectsReturned.

Origin: prod incident 2026-07-03 — two concurrent PUT /api/admin/chargers/38
inserted duplicate tariff rows, and every later edit then raised
MultipleObjectsReturned.
"""
from decimal import Decimal

import pytest
from tortoise.exceptions import IntegrityError

from models import Tariff
from routers.chargers import _upsert_charger_tariff


async def test_second_charger_tariff_rejected(client, test_charger, test_tariff):
    """A second tariff for a charger that already has one violates the unique index."""
    with pytest.raises(IntegrityError):
        await Tariff.create(
            charger=test_charger,
            rate_per_kwh=Decimal("10.0000"),
            tariff_per_kwh_all_in=Decimal("12.0000"),
            gst_percent=Decimal("18.00"),
            is_global=False,
        )


async def test_multiple_global_tariffs_allowed(client):
    """charger_id NULL rows stay distinct under the unique index, so globals coexist."""
    for rate in ("5.0000", "6.0000"):
        await Tariff.create(
            charger=None,
            rate_per_kwh=Decimal(rate),
            tariff_per_kwh_all_in=Decimal("7.0000"),
            gst_percent=Decimal("18.00"),
            is_global=True,
        )
    assert await Tariff.filter(charger_id=None).count() == 2


async def test_upsert_creates_then_updates_single_row(client, test_charger):
    """The admin write path upserts: first call creates, second updates — never a 2nd row."""
    await _upsert_charger_tariff(test_charger.id, Decimal("20.0000"))
    await _upsert_charger_tariff(test_charger.id, Decimal("25.0000"))
    rows = await Tariff.filter(charger_id=test_charger.id)
    assert len(rows) == 1
    assert rows[0].tariff_per_kwh_all_in == Decimal("25.0000")


async def test_upsert_recovers_from_lost_race(client, test_charger):
    """Losing side of a concurrent create: update_or_create raises IntegrityError
    (the constraint blocked the second insert). The helper must recover by
    updating the existing row, not propagate a 500. Exercises the except branch."""
    from unittest.mock import patch, AsyncMock

    await _upsert_charger_tariff(test_charger.id, Decimal("20.0000"))  # winner's row
    with patch.object(Tariff, "update_or_create",
                      new=AsyncMock(side_effect=IntegrityError("duplicate"))):
        await _upsert_charger_tariff(test_charger.id, Decimal("30.0000"))
    rows = await Tariff.filter(charger_id=test_charger.id)
    assert len(rows) == 1
    assert rows[0].tariff_per_kwh_all_in == Decimal("30.0000")


async def test_real_unique_violation_does_not_poison_connection(client, test_charger):
    """A real UNIQUE violation must leave the connection usable for the follow-up
    UPDATE — the recovery path in _upsert_charger_tariff depends on this."""
    await Tariff.create(charger=test_charger, rate_per_kwh=Decimal("15.0000"),
                        tariff_per_kwh_all_in=Decimal("17.7000"), gst_percent=Decimal("18.00"))
    with pytest.raises(IntegrityError):
        await Tariff.create(charger=test_charger, rate_per_kwh=Decimal("1.0000"),
                            tariff_per_kwh_all_in=Decimal("1.0000"), gst_percent=Decimal("18.00"))
    # connection must still work:
    updated = await Tariff.filter(charger_id=test_charger.id).update(
        tariff_per_kwh_all_in=Decimal("99.0000"))
    assert updated == 1
    row = await Tariff.filter(charger_id=test_charger.id).first()
    assert row.tariff_per_kwh_all_in == Decimal("99.0000")
