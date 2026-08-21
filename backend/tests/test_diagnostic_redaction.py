"""Server-side redaction of Diagnostic Bundle bodies (ADR 0029 §2.2).

The lines below are taken from a real charger upload — the one where firmware
reported `redacted: 0 meter` while cumulative energy was plainly in the body.
That miss is why this second line of defence exists.
"""
from __future__ import annotations

from services.diagnostic_redaction import redact_bundle, redaction_occurred

REAL_METER_LINE = (
    "I (11473) ATM90E26: [AVERAGED] V: 239.12 V | I: 0.00 A | P(V*I): 0.00 W | "
    "Active Power: 0.00 W | PF: 0.325 | Freq: 50.05 Hz | Meter E: 12.34567 kWh"
)


def test_energy_totalizer_is_redacted():
    out, counts = redact_bundle(REAL_METER_LINE)
    assert "12.34567" not in out
    assert "[REDACTED]" in out
    assert counts["meter"] == 1


def test_device_health_telemetry_is_deliberately_kept():
    """Voltage, current, PF and frequency carry no billing meaning and are
    genuinely useful for diagnosis — redacting the whole line would lose that
    for no compliance gain."""
    out, _ = redact_bundle(REAL_METER_LINE)
    for keep in ("239.12 V", "0.00 A", "PF: 0.325", "50.05 Hz"):
        assert keep in out


def test_the_line_is_redacted_not_dropped():
    """Stripping a field keeps surrounding context and timing intact."""
    out, _ = redact_bundle(REAL_METER_LINE)
    assert out.startswith("I (11473) ATM90E26:")
    assert len(out.splitlines()) == 1


def test_credentials_are_redacted():
    body = "I (683) CFG: AuthKey=PQGcuCilAdD1nALQJG08sRfUXJk\nI (684) CFG: password: hunter2"
    out, counts = redact_bundle(body)
    assert "PQGcuCilAdD1nALQJG08sRfUXJk" not in out
    assert "hunter2" not in out
    assert counts["credential"] == 2


def test_card_identifiers_are_masked_not_removed():
    """Masking keeps the same card correlatable across lines without making it
    identifiable — the rule the server already applies to its own logs."""
    out, counts = redact_bundle("I (900) RFID: idTag=ABCD1234EFGH")
    assert "ABCD1234EFGH" not in out
    assert "EFGH" in out          # last 4 retained by mask_id_tag
    assert counts["idtag"] == 1


def test_clean_bundle_is_untouched_and_reports_nothing():
    body = "#VLTDIAG/1 boot=3 seq=1 first=1 last=133 overflow=0\nI (683) DIAGBUN: boot count = 1"
    out, counts = redact_bundle(body)
    assert out == body
    assert redaction_occurred(counts) is False


def test_multiple_meter_lines_are_all_caught():
    body = "\n".join([REAL_METER_LINE] * 19)
    out, counts = redact_bundle(body)
    assert counts["meter"] == 19
    assert "12.34567" not in out


def test_redaction_is_case_insensitive():
    out, counts = redact_bundle("meter e: 5.5 kwh and AUTHKEY=abc123")
    assert counts["meter"] == 1
    assert counts["credential"] == 1
    assert "5.5" not in out


def test_a_keyword_label_is_never_mistaken_for_the_value():
    """Regression: `RFID: idTag=X` previously masked the literal word `idTag`
    and left the real card identifier in the body."""
    out, counts = redact_bundle("I (900) RFID: idTag=ABCD1234EFGH")
    assert "ABCD1234EFGH" not in out
    assert "idTag" in out          # the label survives; only the value is masked
    assert counts["idtag"] == 1
