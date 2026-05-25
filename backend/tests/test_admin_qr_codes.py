"""HTTP-layer tests for ``routers/qr_codes.py``.

Regression coverage for the close-then-recreate flow that was previously
blocked by a stale ``charger_qr_code_charger_id_key`` UNIQUE constraint —
see migration ``41_..._drop_charger_qr_code_charger_id_unique.py``.
"""
from unittest.mock import patch, MagicMock

import pytest

from models import ChargerQRCode


pytestmark = pytest.mark.asyncio


def _razorpay_mocks(qr_ids):
    """Build a contextmanager-style stack of patches against razorpay_service
    as it's imported inside routers/qr_codes.py. ``qr_ids`` is a list of the
    Razorpay-style ids returned by successive create calls (each must be
    unique to avoid violating the razorpay_qr_code_id UNIQUE constraint).
    """
    create_payloads = [
        {"id": qid, "image_url": f"https://rzp.test/{qid}.png", "short_url": f"https://rzp.test/{qid}"}
        for qid in qr_ids
    ]
    create = MagicMock(side_effect=create_payloads)
    close = MagicMock(return_value={"id": "closed", "status": "closed"})
    is_configured = MagicMock(return_value=True)
    return create, close, is_configured


async def test_create_qr_after_close_succeeds(client_admin, test_charger):
    """Closing a charger's QR must not block creating a fresh one.

    Pre-migration 41 this raised 500 with asyncpg UniqueViolationError on
    ``charger_qr_code_charger_id_key`` because the inline UNIQUE(charger_id)
    constraint from the original CREATE TABLE was never dropped (migration
    12 referenced the wrong index name and silently no-op'd).
    """
    create, close, is_configured = _razorpay_mocks(["qr_FIRST_001", "qr_SECOND_002"])

    with patch("routers.qr_codes.razorpay_service.create_qr_code", create), \
         patch("routers.qr_codes.razorpay_service.close_qr_code", close), \
         patch("routers.qr_codes.razorpay_service.is_configured", is_configured):

        first = await client_admin.post("/api/admin/qr-codes", json={"charger_id": test_charger.id})
        assert first.status_code == 200, first.text
        first_body = first.json()
        first_id = first_body["id"]
        assert first_body["razorpay_qr_code_id"] == "qr_FIRST_001"
        assert first_body["is_active"] is True

        closed = await client_admin.post(f"/api/admin/qr-codes/{first_id}/close")
        assert closed.status_code == 200, closed.text

        second = await client_admin.post("/api/admin/qr-codes", json={"charger_id": test_charger.id})
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert second_body["id"] != first_id
        assert second_body["razorpay_qr_code_id"] == "qr_SECOND_002"
        assert second_body["is_active"] is True

    rows = await ChargerQRCode.filter(charger_id=test_charger.id).order_by("id")
    assert len(rows) == 2
    assert rows[0].id == first_id
    assert rows[0].is_active is False
    assert rows[1].id == second_body["id"]
    assert rows[1].is_active is True


async def test_create_qr_blocked_when_active_one_exists(client_admin, test_charger):
    """Sanity check: the duplicate-prevention business rule still applies
    when an ACTIVE QR exists — we only relaxed the schema, not the router."""
    create, _close, is_configured = _razorpay_mocks(["qr_ACTIVE_001"])

    with patch("routers.qr_codes.razorpay_service.create_qr_code", create), \
         patch("routers.qr_codes.razorpay_service.is_configured", is_configured):

        first = await client_admin.post("/api/admin/qr-codes", json={"charger_id": test_charger.id})
        assert first.status_code == 200, first.text

        duplicate = await client_admin.post("/api/admin/qr-codes", json={"charger_id": test_charger.id})
        assert duplicate.status_code == 400
        assert "already exists" in duplicate.json()["detail"].lower()

    assert await ChargerQRCode.filter(charger_id=test_charger.id).count() == 1
