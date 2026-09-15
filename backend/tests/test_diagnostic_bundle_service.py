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
# Removed with the bundle header (ADR 0030)
# --------------------------------------------------------------------------
#
# The epoch, overflow-delta and record-gap tests that lived here covered
# `_resolve_epoch`, `_overflow_delta`, `_gap_records` and `_is_same_bundle`.
# All four are deleted: they derived loss from a header of counters the charger
# cannot persist across a reboot, and in the field not one of the five header
# fields was ever correct.
#
# Where each intent went:
#   * gap detection            -> `test_a_real_hole_is_measured_in_seconds` and
#                                 friends, below, now measured in seconds of
#                                 silence rather than record numbers
#   * retry idempotency        -> the content-digest tests below
#   * sequence-replay handling -> obsolete; identity no longer involves sequence
#
# One intent has NO replacement, deliberately. `test_the_two_loss_causes_are_
# distinguishable` asserted ADR 0029's sharpest idea: that a gap with no
# overflow (a bundle lost in transit) is distinguishable from a gap with
# overflow (the buffer wrapped), because the two need opposite remedies.
# Telling them apart required a monotonic counter held separately from the data
# it describes. There is nowhere to keep one, so the distinction is gone and is
# not approximated. A ring-wrap event now says loss is happening; nothing says
# how much. See ADR 0030 "Consequences".


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------
#
# The unique-constraint race is verified against real Postgres rather than
# mocked: the behaviour under test IS the database constraint, and a test that
# mocks it away proves nothing. See the integration check in the ADR notes —
# two racing uploads must yield one row and no 500.


# --------------------------------------------------------------------------
# Content-hash identity (ADR 0030)
# --------------------------------------------------------------------------
#
# The mechanism these replace keyed on `(epoch, bundle_seq)`. It failed in the
# field because the firmware reuses a sequence number across genuinely different
# bundles, so every retry read as a reflash.

from services.diagnostic_markers import content_digest  # noqa: E402

# Shape taken from three real staging retries of one logical bundle on
# 2026-08-27: 460 byte-identical body lines, differing only in the header's
# `last=`. Their raw SHA-256s were 49c2b4b8…, 20c5266c… and ecc2d1c8… — three
# different digests for the same records.
_BODY = "\n".join([
    "I (376165) EC200U: RX CALLRESULT Heartbeat uid=hb_3311FF0D rtt=1236 ms",
    "I (376185) CLOCK: TIME_SYNC boot_ms=375751 utc=2026-08-27T09:16:37Z src=Heartbeat",
    "I (377435) EC200U: TX CALL StatusNotification uid=status_8E5A26F7",
])
_RETRY_1 = "#VLTDIAG/1 boot=55 seq=2 first=15207 last=15381 overflow=0\n" + _BODY
_RETRY_2 = "#VLTDIAG/1 boot=55 seq=2 first=15207 last=15433 overflow=0\n" + _BODY
_RETRY_3 = "#VLTDIAG/1 boot=55 seq=2 first=15207 last=15498 overflow=0\n" + _BODY


def test_retries_of_one_bundle_share_a_digest_despite_a_moving_header():
    """The regression that would have shipped.

    Hashing the body as received makes every retry unique, because the header
    is the one part that moves between attempts — so nothing would ever
    de-duplicate, while synthetic fixtures that repeat the header verbatim
    would still pass.
    """
    import hashlib
    raw = {hashlib.sha256(b.encode()).hexdigest() for b in (_RETRY_1, _RETRY_2, _RETRY_3)}
    assert len(raw) == 3                                    # as received: three bundles

    digests = {content_digest(b) for b in (_RETRY_1, _RETRY_2, _RETRY_3)}
    assert len(digests) == 1                                # as identified: one


def test_a_headerless_body_hashes_the_same_as_one_still_carrying_a_header():
    """The firmware drops the header on its own schedule (C6), so a unit
    mid-rollout must not have its bundles re-archived as new."""
    assert content_digest(_RETRY_1) == content_digest(_BODY)


def test_different_records_produce_different_digests():
    other = _BODY + "\nE (378000) relay: contactor feedback mismatch"
    assert content_digest(_BODY) != content_digest(other)


def test_digest_is_stable_against_our_own_redaction_policy():
    """Identity is hashed pre-redaction on purpose.

    Hashing the redacted body would rotate every historical digest the day a
    pattern is added, making every previously-seen bundle look new.
    """
    from services import diagnostic_redaction

    dirty = _BODY + "\nI (378000) ATM90E26: Meter E: 12.34567 kWh"
    redacted, changed = diagnostic_redaction.redact_bundle(dirty)
    assert diagnostic_redaction.redaction_occurred(changed)
    assert redacted != dirty
    # The digest the endpoint stores is taken from `dirty`, so it does not move.
    assert content_digest(dirty) != content_digest(redacted)


# --------------------------------------------------------------------------
# Loss window (ADR 0030)
# --------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

from routers import diagnostics as _diag  # noqa: E402


def _b(first=None, last=None, approx=False, wraps=0):
    return SimpleNamespace(first_utc=first, last_utc=last,
                           time_approximate=approx, ring_wrap_events=wraps)


_T = datetime(2026, 8, 27, 9, 0, 0, tzinfo=timezone.utc)


def test_contiguous_bundles_report_no_silence():
    prev = _b(last=_T)
    cur = _b(first=_T + timedelta(seconds=2))
    assert _diag._gap_before(cur, prev) == 2


def test_a_real_hole_is_measured_in_seconds():
    prev = _b(last=_T)
    cur = _b(first=_T + timedelta(minutes=14, seconds=43))
    assert _diag._gap_before(cur, prev) == 883


def test_overlapping_bundles_do_not_report_negative_silence():
    prev = _b(last=_T + timedelta(seconds=30))
    cur = _b(first=_T)
    assert _diag._gap_before(cur, prev) == 0


def test_the_first_bundle_has_no_measurable_silence_before_it():
    assert _diag._gap_before(_b(first=_T), None) is None


def test_an_approximate_window_on_either_side_makes_the_gap_unknowable():
    """Receipt time is an upper bound, not a measurement.

    A gap computed against it would be invented — the records could be
    arbitrarily old — so it must read as unknown rather than as zero or as a
    number someone might alert on.
    """
    prev, cur = _b(last=_T), _b(first=_T + timedelta(hours=3))
    assert _diag._gap_before(cur, prev) == 10800

    assert _diag._gap_before(_b(first=_T + timedelta(hours=3), approx=True), prev) is None
    assert _diag._gap_before(cur, _b(last=_T, approx=True)) is None


def test_an_unanchored_bundle_has_no_gap():
    assert _diag._gap_before(_b(first=None), _b(last=_T)) is None
    assert _diag._gap_before(_b(first=_T), _b(last=None)) is None


def test_gap_threshold_is_configurable(monkeypatch):
    assert _diag._gap_threshold_seconds() == 300
    monkeypatch.setenv("DIAGNOSTIC_GAP_THRESHOLD_SECONDS", "60")
    assert _diag._gap_threshold_seconds() == 60


def test_ring_wrap_alone_marks_a_bundle_lossy():
    """The two loss modes remain separately visible, even though the cumulative
    overwrite count is no longer obtainable (ADR 0030)."""
    assert _diag._gap_before(_b(first=_T, wraps=4), None) is None   # no gap...
    # ...but the wrap is still a loss signal in its own right, which is what
    # `lossy` in the summary combines.
    assert _b(first=_T, wraps=4).ring_wrap_events == 4


# --------------------------------------------------------------------------
# Reservation ordering (ADR 0030, issue 06)
# --------------------------------------------------------------------------
#
# The row is written before the object, so a failed upload cannot strand an
# object no row points at. That inverts the risk — a row can outlive a missing
# object — and `archived_at` is what stops that becoming a durability lie.
#
# `reserve_bundle` / `mark_archived` / `find_duplicate` all query the database,
# so their behaviour is covered by the DB-backed verification in the issue
# rather than here: this module is deliberately DB-free (see the endpoint tests'
# docstring on the cross-loop flake). The endpoint test
# `test_s3_failure_is_not_reported_as_success` pins the observable that matters
# — a failed archive must not mark the row delivered.


# --------------------------------------------------------------------------
# Pagination boundary (issue 12)
# --------------------------------------------------------------------------


def _row(i: int):
    """A bundle 10 minutes older than the one before it, newest at i=0."""
    return SimpleNamespace(
        id=100 - i,
        first_utc=_T - timedelta(minutes=10 * i),
        last_utc=_T - timedelta(minutes=10 * i) + timedelta(minutes=1),
        time_approximate=False,
        ring_wrap_events=0,
    )


def test_paging_does_not_change_any_bundles_predecessor():
    """The gap on the first row of page 2 must equal its unpaginated gap.

    This is the bug a naive offset scheme reintroduces at every page boundary.
    Fetching limit+1 is what prevents it: a row's predecessor is the *older*
    bundle, so it is either on the same page or is that extra row.
    """
    rows = [_row(i) for i in range(7)]          # newest first
    limit = 3

    # Keyed by id: SimpleNamespace defines __eq__ and so is unhashable.
    unpaginated = {
        b.id: prev for b, prev in _diag._pair_with_predecessor(rows, len(rows))
    }

    page1 = _diag._pair_with_predecessor(rows[:limit + 1], limit)
    # The cursor is the last row of page 1; page 2 starts strictly older.
    cursor_id = page1[-1][0].id
    start = next(i for i, r in enumerate(rows) if r.id == cursor_id) + 1
    page2 = _diag._pair_with_predecessor(rows[start:start + limit + 1], limit)

    for bundle, predecessor in page1 + page2:
        expected = unpaginated[bundle.id]
        assert predecessor is expected, (
            f"bundle id={bundle.id} paired with the wrong predecessor when paginated"
        )

    # And concretely: the first row of page 2 reports a real gap, not a blank.
    first_of_page2, prev = page2[0]
    assert prev is not None
    assert _diag._gap_before(first_of_page2, prev) == 9 * 60


def test_the_last_row_of_the_final_page_has_no_predecessor():
    """Not a bug — there genuinely is nothing older to measure against."""
    rows = [_row(i) for i in range(3)]
    paired = _diag._pair_with_predecessor(rows, 3)
    assert paired[-1][1] is None
    assert _diag._gap_before(paired[-1][0], None) is None
