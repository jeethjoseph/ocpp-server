# tests/test_ocpp_message_type.py
"""Forward-only OCPP Action labeling for OCPPLog.message_type.

The ingestion adapter derives `message_type` from the raw OCPP wire frame so the
Logs Console Action filter works. See .scratch/logs-console/issues/06 + ADR 0014.
"""
import pytest

from core.connection_manager import _ocpp_message_type


# Charger-initiated CALLs (direction IN) — action lives at frame index 2.
@pytest.mark.parametrize("action", [
    "BootNotification", "Heartbeat", "StatusNotification", "MeterValues",
    "StartTransaction", "StopTransaction", "Authorize", "DataTransfer",
    "FirmwareStatusNotification", "DiagnosticsStatusNotification",
])
def test_call_frame_returns_action(action):
    frame = [2, "msg-123", action, {"foo": "bar"}]
    assert _ocpp_message_type(frame) == action


# Server-initiated CALLs (direction OUT) — same shape, action at index 2.
@pytest.mark.parametrize("action", [
    "RemoteStartTransaction", "RemoteStopTransaction", "ChangeAvailability",
    "Reset", "TriggerMessage", "UpdateFirmware",
])
def test_outbound_call_frame_returns_action(action):
    frame = [2, "msg-456", action, {}]
    assert _ocpp_message_type(frame) == action


def test_callresult_frame():
    assert _ocpp_message_type([3, "msg-123", {}]) == "CallResult"


def test_callerror_frame():
    assert _ocpp_message_type([4, "msg-123", "ProtocolError", "bad", {}]) == "CallError"


@pytest.mark.parametrize("frame", [
    None,                      # send() pre-parse failure
    "not-a-list",             # non-array junk
    [],                        # empty
    [2, "msg"],               # incomplete CALL (no action slot)
    [2, "msg", 123, {}],      # non-string action (malformed CALL)
    [9, "msg", {}],           # unknown message type id
])
def test_non_action_frames_fall_back_to_sentinel(frame):
    assert _ocpp_message_type(frame) == "OCPP"
