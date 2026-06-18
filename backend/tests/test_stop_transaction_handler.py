"""Tests for the StopTransaction OCPP handler edge cases.

Focus: a placeholder/unknown transaction_id (e.g. -1) is benign and must NOT
log at ERROR (Sentry's LoggingIntegration captures ERROR) — regression for
OCPP-BACKEND-A. But a POSITIVE unknown id is a real anomaly (lost transaction)
and must stay at ERROR, so the noise fix doesn't over-suppress real signal.

The `ocpp-server` logger sets propagate=False, so caplog's root handler can't
see it — attach caplog's handler to that logger directly.
"""
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.asyncio


@contextmanager
def _capture_ocpp_logs(caplog):
    """Capture records from the non-propagating `ocpp-server` logger."""
    lg = logging.getLogger("ocpp-server")
    lg.addHandler(caplog.handler)
    old_level = lg.level
    lg.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        lg.removeHandler(caplog.handler)
        lg.setLevel(old_level)


async def _stop(transaction_id):
    from main import ChargePoint
    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = f"cp-{transaction_id}"
    return await ChargePoint.on_stop_transaction(
        fake_cp, transaction_id=transaction_id, meter_stop=0,
        timestamp="2026-06-11T00:00:00Z",
    )


async def test_placeholder_transaction_id_returns_invalid_without_error_log(client, caplog):
    """The benign -1 placeholder responds Invalid and must not log at ERROR."""
    with _capture_ocpp_logs(caplog):
        response = await _stop(-1)

    assert response.id_tag_info == {"status": "Invalid"}
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert not errors, "benign placeholder StopTransaction must not log at ERROR"


async def test_positive_unknown_transaction_id_still_logs_error(client, caplog):
    """A POSITIVE id we don't have is a real anomaly (lost transaction → lost
    billing) and must stay visible at ERROR — not over-suppressed with -1."""
    with _capture_ocpp_logs(caplog):
        response = await _stop(999999)

    assert response.id_tag_info == {"status": "Invalid"}
    errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "999999" in r.message
    ]
    assert errors, "a positive unknown transaction_id must still log at ERROR"
