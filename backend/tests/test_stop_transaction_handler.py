"""Tests for the StopTransaction OCPP handler edge cases.

Focus: a charger that sends a placeholder/unknown transaction_id (e.g. -1)
is an expected, benign condition — the handler responds Invalid and must NOT
log at ERROR (Sentry's LoggingIntegration captures ERROR). Regression for
OCPP-BACKEND-A (39 false alarms).
"""
from unittest.mock import MagicMock

import pytest


pytestmark = pytest.mark.asyncio


async def test_unknown_transaction_id_returns_invalid_without_error_log(client, caplog):
    from main import ChargePoint

    fake_cp = MagicMock(spec=ChargePoint)
    fake_cp.id = "cp-unknown-txn"

    with caplog.at_level("WARNING", logger="main"):
        response = await ChargePoint.on_stop_transaction(
            fake_cp,
            transaction_id=-1,
            meter_stop=0,
            timestamp="2026-06-11T00:00:00Z",
        )

    # OCPP contract preserved: unknown transaction → Invalid.
    assert response.id_tag_info == {"status": "Invalid"}

    not_found_errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "not found" in r.message
    ]
    assert not not_found_errors, "benign unknown-txn StopTransaction must not log at ERROR"
