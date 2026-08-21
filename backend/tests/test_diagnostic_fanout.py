"""Clock reconstruction and OTLP fan-out (ADR 0029).

The bundle bodies here are taken from a real charger upload, including the case
that motivated the whole design: one bundle containing three boot cycles whose
millisecond counters each restart, and whose two clock anchors therefore
disagreed by 73 seconds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services import diagnostic_fanout as fan

RECEIVED = datetime(2026, 8, 19, 12, 3, 38, tzinfo=timezone.utc)

REAL_BUNDLE = "\n".join([
    "#VLTDIAG/1 boot=3 seq=1 first=1 last=133 overflow=0",
    "===== BOOT n=1 @254 ms, reset reason 1 =====",
    "I (683) DIAGBUN: boot count = 1",
    "I (17673) CLOCK: TIME_SYNC boot_ms=17673 utc=2026-08-19T12:02:05Z",
    "I (17773) modem: registered on network",
    "===== BOOT n=2 @255 ms, reset reason 3 =====",
    "I (500) relay: contactor closed",
    "I (19763) CLOCK: TIME_SYNC boot_ms=19763 utc=2026-08-19T12:03:20Z",
    "E (19863) relay: contactor feedback mismatch",
])


def test_boot_markers_split_the_bundle_into_segments():
    """A bundle spans several boots; anchoring across them yields confidently
    wrong times, so segmentation comes first."""
    segments = fan.split_boot_segments(REAL_BUNDLE.splitlines())
    # header line, then two boot segments
    assert len(segments) == 3
    assert segments[1][0].startswith("===== BOOT n=1")
    assert segments[2][0].startswith("===== BOOT n=2")


def test_each_segment_is_anchored_by_its_own_time_sync():
    segments = fan.split_boot_segments(REAL_BUNDLE.splitlines())
    assert fan.find_anchor(segments[1]) == (
        17673, datetime(2026, 8, 19, 12, 2, 5, tzinfo=timezone.utc))
    assert fan.find_anchor(segments[2]) == (
        19763, datetime(2026, 8, 19, 12, 3, 20, tzinfo=timezone.utc))


def test_timestamps_are_reconstructed_per_segment():
    """The 100 ms offsets are relative to each segment's own anchor — using one
    anchor across the bundle would place the second segment 73 s adrift."""
    records, unanchored = fan.resolve_records(REAL_BUNDLE, RECEIVED)
    assert unanchored == 1          # the header "segment" has no anchor

    by_msg = {r["message"]: r for r in records}
    first = by_msg["I (17773) modem: registered on network"]
    second = by_msg["E (19863) relay: contactor feedback mismatch"]

    assert first["timestamp"] == datetime(2026, 8, 19, 12, 2, 5, 100000, tzinfo=timezone.utc)
    assert second["timestamp"] == datetime(2026, 8, 19, 12, 3, 20, 100000, tzinfo=timezone.utc)
    assert first["time_approx"] is False and second["time_approx"] is False


def test_lines_before_the_anchor_are_still_placed_correctly():
    """Records written before the clock was set carry a negative offset from the
    anchor — the pre-connection window, which is exactly where faults live."""
    records, _ = fan.resolve_records(REAL_BUNDLE, RECEIVED)
    boot_line = next(r for r in records if "boot count = 1" in r["message"])
    expected = datetime(2026, 8, 19, 12, 2, 5, tzinfo=timezone.utc) - timedelta(
        milliseconds=17673 - 683)
    assert boot_line["timestamp"] == expected


def test_a_segment_with_no_anchor_falls_back_and_is_flagged():
    """A charger that never reached the server that boot still gets searchable
    lines — marked approximate so nobody reads them as precise."""
    body = "===== BOOT n=1 @254 ms =====\nI (500) relay: contactor closed"
    records, unanchored = fan.resolve_records(body, RECEIVED)
    assert unanchored == 1
    assert all(r["time_approx"] for r in records)
    assert all(r["timestamp"] == RECEIVED for r in records)


def test_the_loose_firmware_format_is_accepted_as_a_fallback():
    """Current firmware logs a free-text sync line; the fan-out works before the
    machine-parseable TIME_SYNC form lands."""
    body = "\n".join([
        "===== BOOT @254 ms =====",
        "I (17673) EC200U: Time synced from heartbeat: 2026-08-19T12:02:05Z",
        "I (17773) modem: up",
    ])
    records, unanchored = fan.resolve_records(body, RECEIVED)
    assert unanchored == 0
    up = next(r for r in records if r["message"].endswith("modem: up"))
    assert up["timestamp"] == datetime(2026, 8, 19, 12, 2, 5, 100000, tzinfo=timezone.utc)


def test_line_formats_are_classified():
    esp = fan._parse_line("W (723) VoltLync_ADC: window OPEN")
    assert (esp["level"], esp["boot_ms"], esp["subsystem"]) == ("WARN", 723, "VoltLync_ADC")

    at = fan._parse_line("[     326] TX> AT+QWSCLOSE=0")
    assert (at["level"], at["subsystem"]) == ("DEBUG", "at")
    # Deliberately untimed: the bracketed counter is a separate clock from the
    # ESP-IDF one. Real bundles show `[326]` between `I (743)` and `I (753)`,
    # so treating it as ms-since-boot placed AT lines ~400 ms early.
    assert at["boot_ms"] is None


def test_unparseable_lines_are_forwarded_not_dropped():
    """Firmware format drifts; a silent drop means an update deletes logs with
    nothing reporting it."""
    rec = fan._parse_line("something entirely unexpected")
    assert rec is not None
    assert rec["subsystem"] == "raw"
    assert rec["boot_ms"] is None


def test_service_name_is_per_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert fan.service_name() == "VoltLync-Charger-Logs-Staging"
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert fan.service_name() == "VoltLync-Charger-Logs-Production"
    monkeypatch.setenv("ENVIRONMENT", "anything-else")
    assert fan.service_name() == "VoltLync-Charger-Logs-Development"


def test_records_beyond_the_ingest_window_are_excluded_and_counted(monkeypatch):
    """New Relic silently drops anything older than 48h. Excluding them locally
    keeps the count honest instead of trusting a success response that lied."""
    monkeypatch.setenv("DIAGNOSTIC_FANOUT_ENABLED", "true")
    monkeypatch.setenv("NEW_RELIC_LICENSE_KEY", "fake")
    old_utc = (datetime.now(timezone.utc) - timedelta(hours=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = "\n".join([
        "===== BOOT n=1 @254 ms =====",
        f"I (1000) CLOCK: TIME_SYNC boot_ms=1000 utc={old_utc}",
        "I (1100) modem: ancient line",
    ])
    posted = []
    monkeypatch.setattr(fan, "_post", lambda p, k, e: posted.append(p) or 200)
    summary = fan.forward_bundle(body, "S006C02", 42, 0)
    # All three lines resolve into the ancient window: the two timestamped ones
    # directly, and the BOOT marker by inheriting its neighbour rather than
    # jumping to the upload time.
    assert summary["too_old"] == 3
    assert summary["forwarded"] == 0
    assert posted == []


def test_fanout_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DIAGNOSTIC_FANOUT_ENABLED", raising=False)
    assert fan.forward_bundle(REAL_BUNDLE, "S006C02", 1, 0)["enabled"] is False


def test_a_forwarding_failure_never_raises(monkeypatch):
    """The bundle is already durably in S3; a vendor outage must not become a
    non-2xx that makes the charger re-send data that is already safe."""
    monkeypatch.setenv("DIAGNOSTIC_FANOUT_ENABLED", "true")
    monkeypatch.setenv("NEW_RELIC_LICENSE_KEY", "fake")

    def boom(*_a, **_k):
        raise RuntimeError("otlp down")

    monkeypatch.setattr(fan, "_post", boom)
    summary = fan.forward_bundle(REAL_BUNDLE, "S006C02", 1, 0)
    assert summary["forwarded"] == 0


def test_successful_forward_batches_and_tags_records(monkeypatch):
    monkeypatch.setenv("DIAGNOSTIC_FANOUT_ENABLED", "true")
    monkeypatch.setenv("NEW_RELIC_LICENSE_KEY", "fake")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    captured = []
    monkeypatch.setattr(fan, "_post", lambda p, k, e: captured.append(p) or 200)

    summary = fan.forward_bundle(REAL_BUNDLE, "S006C02", 42, 3, received_at=datetime.now(timezone.utc))
    assert summary["forwarded"] > 0 and summary["batches"] == 1

    resource = captured[0]["resourceLogs"][0]["resource"]["attributes"]
    assert {"key": "service.name",
            "value": {"stringValue": "VoltLync-Charger-Logs-Staging"}} in resource

    attrs = captured[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"]
    keys = {a["key"] for a in attrs}
    assert {"charger_code", "subsystem", "bundle_seq", "epoch", "boot_segment"} <= keys


def test_untimestamped_lines_stay_beside_their_neighbours():
    """A BOOT marker carries no millisecond offset. Placing it at the upload
    time would scatter it hours from the events it introduces, so it inherits
    the surrounding segment's resolved time instead."""
    records, _ = fan.resolve_records(REAL_BUNDLE, RECEIVED)
    marker = next(r for r in records if "BOOT n=2" in r["message"])
    neighbour = next(r for r in records if "contactor closed" in r["message"])
    # Same segment, and nowhere near the unrelated upload time.
    assert marker["boot_segment"] == neighbour["boot_segment"]
    assert marker["timestamp"] != RECEIVED
    assert abs((marker["timestamp"] - neighbour["timestamp"]).total_seconds()) < 60


def test_at_trace_lines_inherit_position_rather_than_their_own_counter():
    """Regression: the AT trace ticks on a different clock from the ESP log, so
    its bracketed number must never be used as an offset. Placing these lines by
    neighbour keeps them accurate to within one log line."""
    body = "\n".join([
        "===== BOOT n=1 @254 ms =====",
        "I (1000) CLOCK: TIME_SYNC boot_ms=1000 utc=2026-08-19T12:00:00Z",
        "I (1743) gpio: configured",
        "[     326] TX> AT+QWSCLOSE=0",
        "I (1753) EC200U: sent",
    ])
    records, _ = fan.resolve_records(body, RECEIVED)
    at = next(r for r in records if "AT+QWSCLOSE" in r["message"])
    before = next(r for r in records if "gpio: configured" in r["message"])
    # Sits with its neighbour at ~12:00:00.743, not 400ms earlier at .326
    assert at["timestamp"] == before["timestamp"]
    assert at["time_approx"] is True


def test_every_esp_idf_level_is_mapped():
    """Severity is the primary filter dimension in New Relic. An unmapped level
    letter would fall through to the raw catch-all, losing BOTH the level and
    the millisecond offset — so the line would be mislabelled INFO and placed
    only approximately."""
    expected = {"E": "ERROR", "W": "WARN", "I": "INFO", "D": "DEBUG", "V": "TRACE"}
    for letter, level in expected.items():
        rec = fan._parse_line(f"{letter} (683) EC200U: something happened")
        assert rec["level"] == level, letter
        assert rec["boot_ms"] == 683, letter
        assert rec["subsystem"] == "EC200U", letter
