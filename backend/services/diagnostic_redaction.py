"""Server-side redaction of Diagnostic Bundle bodies — ADR 0029.

Firmware is asked to keep three things out of its traces (spec §2.2): the
Charger Auth Key, raw RFID card identifiers, and metering data. This module is
the second line of defence, applied **before the S3 write** rather than only on
the New Relic path — S3 holds bundles for 90 days, so redacting one side alone
would leave the sensitive copy in the archive.

It exists because the first real bundle proved firmware redaction can silently
under-match: the charger reported ``redacted: 0 meter`` while cumulative energy
readings were plainly in the body.

Design notes:
  * **Redact, never drop the line.** A stripped field keeps the surrounding
    diagnostic context intact; dropping the line would lose the timing.
  * **Count what was redacted.** A non-zero count means firmware let something
    through, which is itself worth alerting on.
  * Voltage, current, power factor and frequency are deliberately **kept** —
    device-health telemetry with no billing meaning.
"""
from __future__ import annotations

import re

# Cumulative energy totalizer. This is the field that matters: it is the same
# quantity GST invoices are computed from, reached through the audited
# MeterValues path. A second unaudited copy is the liability.
_METER_ENERGY_RE = re.compile(r"(Meter\s*E\s*:\s*)([0-9]+(?:\.[0-9]+)?)(\s*k?Wh)", re.IGNORECASE)

# Explicit credential-shaped assignments, e.g. `AuthKey=abc123`, `password: x`.
_CREDENTIAL_RE = re.compile(
    r"((?:auth[_-]?key|authkey|password|passwd|secret|bearer)\s*[:=]\s*)(\S+)",
    re.IGNORECASE,
)

# RFID / idTag assignments. Value masked rather than removed so the same card
# remains correlatable across lines without being identifiable.
#
# The negative lookahead matters: a line like `RFID: idTag=ABCD1234` has two
# keyword-ish tokens, and without it the engine matches `RFID: ` + the literal
# word `idTag` as the "value" — masking the label and leaving the real card
# identifier untouched. Refusing a keyword as a value makes it skip ahead to the
# genuine assignment.
_KEYWORDS = r"id[_-]?tag|rfid|card[_-]?uid"
_IDTAG_RE = re.compile(
    rf"((?:{_KEYWORDS})\s*[:=]\s*)(?!(?:{_KEYWORDS})\b)([A-Za-z0-9]{{4,}})",
    re.IGNORECASE,
)


def _mask_tag(match: re.Match) -> str:
    from utils import mask_id_tag
    return match.group(1) + mask_id_tag(match.group(2))


def redact_bundle(text: str) -> tuple[str, dict[str, int]]:
    """Strip sensitive values from a bundle body.

    Returns ``(redacted_text, counts)`` where counts maps category → number of
    substitutions. A non-zero count is a firmware-side miss, not a normal event.
    """
    counts = {"meter": 0, "credential": 0, "idtag": 0}

    text, n = _METER_ENERGY_RE.subn(r"\1[REDACTED]\3", text)
    counts["meter"] = n

    text, n = _CREDENTIAL_RE.subn(r"\1[REDACTED]", text)
    counts["credential"] = n

    text, n = _IDTAG_RE.subn(_mask_tag, text)
    counts["idtag"] = n

    return text, counts


def redaction_occurred(counts: dict[str, int]) -> bool:
    return any(counts.values())
