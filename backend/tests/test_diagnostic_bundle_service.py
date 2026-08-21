"""Loss-accounting logic for Diagnostic Bundles (ADR 0029).

These cover the pure decision functions, which is where the whole
"make loss visible" design actually lives. `record_bundle` itself is exercised
through the endpoint tests.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import diagnostic_bundle_service as svc

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _prev(seq: int, epoch: int = 0, last: int | None = None, overflow: int | None = None):
    return SimpleNamespace(bundle_seq=seq, epoch=epoch, last_record=last, overflow=overflow)


# --------------------------------------------------------------------------
# Epoch — surviving a reflash
# --------------------------------------------------------------------------

def test_first_ever_bundle_starts_at_epoch_zero():
    assert svc._resolve_epoch(None, 1) == (0, False)


def test_normal_progression_keeps_the_epoch():
    assert svc._resolve_epoch(_prev(seq=41), 42) == (0, False)


def test_sequence_going_backwards_starts_a_new_epoch():
    """A reflash or EEPROM clear restarts bundle_seq at 1. Without a new epoch
    the charger's new data would collide with its historical bundles and be
    dropped as duplicates — the worst outcome for a loss-detection system."""
    assert svc._resolve_epoch(_prev(seq=42, epoch=0), 1) == (1, True)


def test_repeating_the_same_sequence_also_regresses():
    """Equal, not just lower: a charger reflashed at exactly the same seq must
    not silently overwrite the previous epoch's row."""
    assert svc._resolve_epoch(_prev(seq=42, epoch=3), 42) == (4, True)


# --------------------------------------------------------------------------
# Overflow delta — the buffer being outrun
# --------------------------------------------------------------------------

def test_overflow_delta_is_the_increase_since_the_last_bundle():
    assert svc._overflow_delta(_prev(seq=1, overflow=100), 350, same_epoch=True) == 250


def test_overflow_delta_survives_the_uint32_wrap():
    """The firmware counter is a monotonic uint32. A naive subtraction across
    the wrap point would report a hugely negative delta and hide real loss."""
    prev = _prev(seq=1, overflow=(1 << 32) - 10)
    assert svc._overflow_delta(prev, 5, same_epoch=True) == 15


def test_overflow_delta_is_zero_across_an_epoch_boundary():
    """After a reflash the counter restarts, so a cross-epoch delta is
    meaningless rather than enormous."""
    assert svc._overflow_delta(_prev(seq=9, overflow=5000), 3, same_epoch=False) == 0


def test_overflow_delta_is_zero_without_a_baseline():
    assert svc._overflow_delta(None, 500, same_epoch=True) == 0
    assert svc._overflow_delta(_prev(seq=1, overflow=None), 500, same_epoch=True) == 0


# --------------------------------------------------------------------------
# Gap — a bundle that never arrived
# --------------------------------------------------------------------------

def test_contiguous_bundles_report_no_gap():
    assert svc._gap_records(_prev(seq=1, last=100), first_record=101, same_epoch=True) == 0


def test_missing_records_between_bundles_are_counted():
    assert svc._gap_records(_prev(seq=1, last=100), first_record=140, same_epoch=True) == 39


def test_overlapping_bundles_are_not_reported_as_negative_gap():
    """A re-sent or overlapping range is not loss; clamp rather than report a
    negative count that would corrupt any aggregate."""
    assert svc._gap_records(_prev(seq=1, last=100), first_record=80, same_epoch=True) == 0


def test_gap_is_zero_across_an_epoch_boundary():
    assert svc._gap_records(_prev(seq=9, last=9000), first_record=1, same_epoch=False) == 0


# --------------------------------------------------------------------------
# The distinction that matters operationally
# --------------------------------------------------------------------------

def test_the_two_loss_causes_are_distinguishable():
    """Same symptom, opposite remedy: a gap with no overflow means an upload
    was lost (fix retries); overflow means the charger logged faster than it
    uploaded (upload more often, or get bigger flash)."""
    lost_upload = _prev(seq=1, last=100, overflow=7)
    assert svc._gap_records(lost_upload, 140, True) == 39
    assert svc._overflow_delta(lost_upload, 7, True) == 0

    outrun_buffer = _prev(seq=1, last=100, overflow=7)
    assert svc._gap_records(outrun_buffer, 101, True) == 0
    assert svc._overflow_delta(outrun_buffer, 507, True) == 500


# --------------------------------------------------------------------------
# Retry vs reflash — the two look identical by sequence alone
# --------------------------------------------------------------------------

def _row(seq, boot, first, last):
    return SimpleNamespace(bundle_seq=seq, boot=boot, first_record=first, last_record=last)


def test_identical_resend_is_recognised_as_the_same_bundle():
    """Regression: deciding on sequence alone made every retry look like a
    reflash, which minted a new epoch and defeated idempotency — so a charger
    retrying after a lost response would duplicate its archive every time."""
    existing = _row(seq=4, boot=1, first=301, last=400)
    header = {"seq": 4, "boot": 1, "first": 301, "last": 400}
    assert svc._is_same_bundle(existing, header) is True


def test_sequence_replay_with_different_content_is_not_a_duplicate():
    """A reflashed unit restarts bundle_seq over genuinely new records. Treating
    that as a duplicate would silently discard the charger's new data."""
    existing = _row(seq=1, boot=1, first=1, last=100)
    assert svc._is_same_bundle(existing, {"seq": 1, "boot": 9, "first": 1, "last": 50}) is False
    assert svc._is_same_bundle(existing, {"seq": 1, "boot": 1, "first": 1, "last": 50}) is False
    assert svc._is_same_bundle(existing, {"seq": 1, "boot": 1, "first": 5, "last": 100}) is False


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------
#
# The unique-constraint race is verified against real Postgres rather than
# mocked: the behaviour under test IS the database constraint, and a test that
# mocks it away proves nothing. See the integration check in the ADR notes —
# two racing uploads must yield one row and no 500.
