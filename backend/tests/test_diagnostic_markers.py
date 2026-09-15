"""In-band marker parsing — ADR 0030.

These cover what the bundle header used to carry and the body now supplies:
where one boot ends and the next begins, what real time a segment's
millisecond counter maps to, and how much of a bundle can be trusted when the
charger never reached the network that boot.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import diagnostic_markers as dm

RECEIVED = datetime(2026, 8, 19, 12, 3, 38, tzinfo=timezone.utc)

# Two boots, each with its own anchor, and — the case that matters — records
# written BEFORE the clock sync in both.
MULTI_BOOT = "\n".join([
    "===== BOOT @254 ms, reset reason 1 =====",
    "I (683) DIAGBUN: boot count = 1",
    "I (17673) CLOCK: TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z",
    "I (17773) modem: registered on network",
    "===== BOOT @255 ms, reset reason 3 =====",
    "I (500) relay: contactor closed",
    "I (19763) CLOCK: TIME_SYNC boot_ms=19763 utc=2026-08-19T12:03:20Z",
    "E (19863) relay: contactor feedback mismatch",
])

NO_ANCHOR = "\n".join([
    "===== BOOT @254 ms, reset reason 1 =====",
    "I (683) DIAGBUN: boot count = 1",
    "E (900) modem: registration failed, no network",
])


def test_boot_markers_split_segments():
    segments = dm.split_boot_segments(MULTI_BOOT.splitlines())
    assert len(segments) == 2
    assert segments[0][0].startswith("===== BOOT @254")
    assert segments[1][0].startswith("===== BOOT @255")


def test_anchor_resolves_records_written_before_the_sync():
    """`boot_ms - anchor_ms` is signed on purpose.

    Without retroactive resolution an entire outage segment collapses onto the
    moment connectivity returned — losing the times of exactly the records
    worth reading. All clock anchors come from the network, so the records
    preceding one are the interesting ones.
    """
    records, unanchored = dm.resolve_records(MULTI_BOOT, RECEIVED)
    assert unanchored == 0

    by_msg = {r["message"]: r for r in records}
    # 683 ms is 16,990 ms BEFORE the 17,673 ms anchor at 12:02:05Z.
    early = by_msg["I (683) DIAGBUN: boot count = 1"]
    assert early["timestamp"] == datetime(2026, 8, 19, 12, 1, 48, 10000, tzinfo=timezone.utc)
    assert early["time_approx"] is False
    assert early["timestamp"] < datetime(2026, 8, 19, 12, 2, 5, tzinfo=timezone.utc)


def test_each_segment_uses_its_own_anchor():
    """The disagreement that motivated per-segment anchoring.

    Both boots log at a few hundred ms, but those are different real moments.
    Anchoring the whole bundle to one TIME_SYNC would place boot 2's records
    beside boot 1's — confidently wrong rather than merely imprecise.
    """
    records, _ = dm.resolve_records(MULTI_BOOT, RECEIVED)
    by_msg = {r["message"]: r for r in records}

    # boot 1: 683 ms against a 17,673 ms anchor at 12:02:05Z  -> 12:01:48.010
    early = by_msg["I (683) DIAGBUN: boot count = 1"]
    # boot 2: 500 ms against a 19,763 ms anchor at 12:03:20Z  -> 12:03:00.737
    late = by_msg["I (500) relay: contactor closed"]

    assert early["boot_segment"] == 0
    assert late["boot_segment"] == 1
    assert late["timestamp"] == datetime(2026, 8, 19, 12, 3, 0, 737000, tzinfo=timezone.utc)
    # Near-identical boot_ms, 72.7 s apart in real time.
    assert (late["timestamp"] - early["timestamp"]).total_seconds() == pytest.approx(72.727)


def test_window_spans_first_to_last_resolved_record():
    first, last, approx = dm.resolve_window(MULTI_BOOT, RECEIVED)
    assert approx is False
    assert first == datetime(2026, 8, 19, 12, 1, 48, 10000, tzinfo=timezone.utc)
    assert last == datetime(2026, 8, 19, 12, 3, 20, 100000, tzinfo=timezone.utc)


def test_unanchored_body_falls_back_to_receipt_time_and_says_so():
    """A boot that never reached the network is unanchorable.

    Receipt time is an upper bound, not a measurement — the records could be
    arbitrarily old — so the window must be flagged approximate and must never
    be read as evidence of a loss gap.
    """
    first, last, approx = dm.resolve_window(NO_ANCHOR, RECEIVED)
    assert (first, last) == (RECEIVED, RECEIVED)
    assert approx is True


def test_partially_anchored_bundle_is_approximate():
    """One boot anchored, one not: the window covers only what resolved."""
    body = MULTI_BOOT + "\n" + NO_ANCHOR
    first, last, approx = dm.resolve_window(body, RECEIVED)
    assert approx is True
    assert first is not None and last is not None


def test_empty_body_has_no_window():
    assert dm.resolve_window("", RECEIVED) == (None, None, True)


def test_loose_anchor_form_still_resolves():
    body = "\n".join([
        "===== BOOT @254 ms, reset reason 1 =====",
        "I (17673) CLOCK: Time synced from heartbeat: 2026-08-19T12:02:05Z",
        "I (17773) modem: up",
    ])
    first, _, approx = dm.resolve_window(body, RECEIVED)
    assert approx is False
    assert first == datetime(2026, 8, 19, 12, 2, 5, tzinfo=timezone.utc)


@pytest.mark.parametrize("body,expected", [
    ("#VLTDIAG/1 boot=1 seq=2 first=1 last=9 overflow=0\nI (1) a: b\n", "I (1) a: b\n"),
    ("I (1) a: b\n", "I (1) a: b\n"),
    ("#VLTDIAG/1 boot=1", ""),
    ("", ""),
])
def test_strip_legacy_header(body, expected):
    assert dm.strip_legacy_header(body) == expected


def test_strip_legacy_header_is_idempotent():
    once = dm.strip_legacy_header("#VLTDIAG/1 x\nI (1) a: b\n")
    assert dm.strip_legacy_header(once) == once


def test_ring_wrap_events_are_counted():
    body = "\n".join([
        "W (41564) EC200U: DiagUpload: body short by 80 B (ring wrapped mid-upload) - padding",
        "I (41600) EC200U: fine",
        "W (52000) EC200U: DiagUpload: body short by 251 B (ring wrapped mid-upload) - padding",
    ])
    assert dm.count_ring_wraps(body) == 2
    assert dm.count_ring_wraps("nothing here") == 0


# ---------------------------------------------------------------------------
# Malformed clock anchors (review finding 2)
#
# The anchor regexes match digits and colons, which is strictly more permissive
# than strptime. An unparseable-but-well-shaped stamp used to raise out of
# resolve_window into receive_bundle's unguarded call, returning HTTP 500 --
# and because the charger never saw a 2xx it re-sent the identical body until
# its hourly upload budget was gone, forever.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_utc", [
    "0000-00-00T00:00:00Z",   # RTC never synced -- the realistic case
    "2026-13-45T99:99:99Z",   # digits in range for the regex, not for a calendar
    "2026-08-19T12:02:05:99Z",  # [\d:]+ admits the extra group
])
def test_malformed_anchor_does_not_raise(bad_utc):
    assert dm.find_anchor([f"TIME_SYNC boot_ms=17673 utc={bad_utc}"]) is None


@pytest.mark.parametrize("bad_utc", ["0000-00-00T00:00:00Z", "2026-13-45T99:99:99Z"])
def test_bundle_with_malformed_anchor_still_resolves_a_window(bad_utc):
    """The bundle is archived with an approximate window rather than 500ing."""
    body = "\n".join([
        "===== BOOT @278 ms, reset reason 3 =====",
        f"TIME_SYNC boot_ms=17673 utc={bad_utc}",
        "I (17700) app: charging started",
    ])
    first, last, approximate = dm.resolve_window(body, RECEIVED)
    assert approximate is True
    assert first is not None and last is not None


def test_good_anchor_after_a_malformed_one_is_still_found():
    """A charger that syncs mid-segment must not be written off because its
    first attempt was garbage."""
    anchor = dm.find_anchor([
        "TIME_SYNC boot_ms=100 utc=0000-00-00T00:00:00Z",
        "TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z",
    ])
    assert anchor is not None
    boot_ms, utc = anchor
    assert boot_ms == 17673
    assert utc == datetime(2026, 8, 19, 12, 2, 5, tzinfo=timezone.utc)


def test_malformed_loose_form_anchor_does_not_raise():
    """The pre-C1 free-text anchor takes the same guard."""
    assert dm.find_anchor([
        "I (17673) app: Time synced from heartbeat: 0000-00-00T00:00:00Z"
    ]) is None
