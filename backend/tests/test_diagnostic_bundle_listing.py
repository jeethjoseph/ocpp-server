"""The admin bundle listing shows deliveries, not reservations.

A `DiagnosticBundle` row with `archived_at` NULL is a *reservation* — written
before an S3 put that then failed, so the records it names reached nobody. Two
things go wrong when one is listed:

  * it renders with a Download button pointing at a key no object exists at, and
  * because the page's rows are paired to compute the silence gap, a phantom row
    becomes the predecessor of the next real bundle and corrupts the very
    measurement the feature exists to produce.

`find_duplicate` and `previous_delivered` in `diagnostic_bundle_service` both
already filter on `archived_at__isnull=False`; the listing query did not.
Lives in its own file because `test_diagnostics_endpoint` shadows the `client`
fixture with a DB-less app, so these need conftest's real one.
"""
from datetime import datetime, timezone

import pytest

from models import DiagnosticBundle


async def _bundle(charger, *, key, digest, archived, first_hour, last_hour):
    return await DiagnosticBundle.create(
        charger=charger,
        s3_key=key,
        size_bytes=100,
        line_count=5,
        content_sha256=digest,
        first_utc=datetime(2026, 9, 1, first_hour, 0, tzinfo=timezone.utc),
        last_utc=datetime(2026, 9, 1, last_hour, 0, tzinfo=timezone.utc),
        archived_at=(
            datetime(2026, 9, 1, last_hour, 5, tzinfo=timezone.utc) if archived else None
        ),
    )


@pytest.mark.asyncio
async def test_listing_excludes_unarchived_reservations(
    client, client_admin, test_charger
):
    delivered = await _bundle(
        test_charger, key="a.log", digest="a" * 64, archived=True,
        first_hour=1, last_hour=2,
    )
    await _bundle(
        test_charger, key="b.log", digest="b" * 64, archived=False,
        first_hour=3, last_hour=4,
    )

    resp = await client_admin.get(
        f"/api/admin/diagnostics/chargers/{test_charger.id}/bundles"
    )
    assert resp.status_code == 200
    assert [item["id"] for item in resp.json()["items"]] == [delivered.id]


@pytest.mark.asyncio
async def test_reservation_does_not_become_a_predecessor(
    client, client_admin, test_charger
):
    """The silence gap is measured against the last DELIVERED bundle."""
    await _bundle(
        test_charger, key="old.log", digest="c" * 64, archived=True,
        first_hour=1, last_hour=2,
    )
    await _bundle(
        test_charger, key="lost.log", digest="d" * 64, archived=False,
        first_hour=3, last_hour=4,
    )
    newest = await _bundle(
        test_charger, key="new.log", digest="e" * 64, archived=True,
        first_hour=5, last_hour=6,
    )

    resp = await client_admin.get(
        f"/api/admin/diagnostics/chargers/{test_charger.id}/bundles"
    )
    assert resp.status_code == 200
    items = {item["id"]: item for item in resp.json()["items"]}
    assert len(items) == 2

    # newest.first_utc 05:00 minus the delivered predecessor's last_utc 02:00.
    # Measured against the reservation (last_utc 04:00) it would read 1h.
    assert items[newest.id]["gap_before_seconds"] == 3 * 3600
