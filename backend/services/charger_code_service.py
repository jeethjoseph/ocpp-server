"""The Asset Code: allocation, rendering and lookup (ADR 0028).

The one place that knows the Asset Code's shape. Every surface that renders a
code calls `format_asset_code`; every surface that accepts one calls
`parse_asset_code`. Nothing hand-formats and nothing hand-parses — the
disagreeing-fallback problem across three call-site families is exactly what
ADR 0028 exists to end, and it returns the moment two callers each build the
string themselves.
"""
import os

from tortoise import connections

from policy import CHARGER_CODE_MIN_WIDTH, charger_code_series


def current_series() -> str:
    """The Asset Code series this register may mint."""
    return charger_code_series(os.getenv("ENVIRONMENT", "development"))


def format_asset_code(number: int, series: str | None = None) -> str:
    """Render an Asset Code. The ONLY place a code becomes a string.

    Zero-padded to a minimum width and widening by itself past the boundary —
    VOW9999 is followed by VOW10000, with no migration and no re-stencil.
    """
    if number < 1:
        raise ValueError(f"Asset Code number must be positive, got {number}")
    return f"{series or current_series()}{number:0{CHARGER_CODE_MIN_WIDTH}d}"


def parse_asset_code(raw: str, series: str | None = None) -> int | None:
    """Resolve a typed code to its integer, or None if it is not one of ours.

    Lookup parses the integer rather than matching the string, so `VOW0001`,
    `VOW00001`, `vow1` and `VOW1` all resolve to the same unit. That is what
    makes the minimum-width rule safe: a code typed at one padding resolves at
    any other, so the register can widen past 9999 without re-padding anything.

    A FOREIGN SERIES IS REJECTED, NEVER COERCED. A staging code typed into
    production must find nothing rather than silently resolving to production's
    unit with the same number — both registers mint codes a real person reads
    off a real unit, which is the whole reason the series exists.
    """
    if not raw:
        return None
    candidate = raw.strip().upper()
    expected = (series or current_series()).upper()

    # Longest-prefix first: VOW is a strict prefix of VOWS, so testing VOW
    # first would strip only three characters off VOWS0001 and leave "S0001".
    for known in sorted({"VOWS", "VOW"}, key=len, reverse=True):
        if candidate.startswith(known):
            if known != expected:
                return None
            digits = candidate[len(known):]
            if not digits.isdigit():
                return None
            value = int(digits)
            return value if value >= 1 else None
    return None


ASSET_CODE_SEQUENCE = "charger_asset_code_seq"


async def next_asset_code(using_db=None) -> str:
    """Allocate the next Asset Code from the Postgres sequence.

    `nextval` is atomic: two concurrent creates can never receive the same
    number, so there is no collision to retry and no read-modify-write race.
    That is the whole reason this is a sequence rather than `MAX + 1`.

    `nextval` also does not roll back, so a failed insert burns a number and
    leaves a gap. That is intended — ADR 0028 commits to codes never being
    reused and gaps never being backfilled, "including gaps that were never
    allocated". A burned number is that same case by another route.
    """
    connection = using_db or connections.get("default")
    rows = await connection.execute_query_dict(
        f"SELECT nextval('{ASSET_CODE_SEQUENCE}') AS value"
    )
    return format_asset_code(int(rows[0]["value"]))
