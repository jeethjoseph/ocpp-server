"""Validation of the supplier identity printed on every GST Invoice.

Between April and August 2026 all 1,287 invoices across the production and
staging registers named `VOLTLYNC PRIVATE LIMITED` while carrying GSTIN
`32AAIFI0458G1ZN` — a registration belonging to a different registered person
entirely. Rule 46 CGST requires the name and GSTIN to be those of the same
person.

Nothing caught it, because both halves had silent fallbacks: the business name
defaulted to a hardcoded string in the invoice service, and the GSTIN defaulted
to an empty string, with no check that the two described the same entity.

A GSTIN is self-describing enough to catch exactly that mismatch:

    32 AALCV6461E 1 Z A
    │  │          │ │ └── mod-36 check digit
    │  │          │ └──── default 'Z'
    │  │          └────── registration count for this PAN in this state
    │  └───────────────── PAN; 4th char is the entity type, 5th the name initial
    └──────────────────── state code

The incorrect GSTIN's PAN carried `F` (firm or LLP) with name initial `I`,
against a configured name of "VOLTLYNC PRIVATE LIMITED" — a company beginning
with V. These checks would have refused the very first boot.
"""

import re

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

# Base-36 alphabet used by the GSTIN check-digit algorithm.
_CODES = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# 4th character of a PAN. Only the entity types we could plausibly be.
PAN_ENTITY_TYPES = {
    "C": "Company",
    "F": "Firm / LLP",
    "P": "Individual",
    "H": "HUF",
    "A": "Association of Persons",
    "T": "Trust",
    "B": "Body of Individuals",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}


class SupplierIdentityError(ValueError):
    """Raised when the configured supplier identity is absent or inconsistent."""


def gstin_check_digit(gstin: str) -> str:
    """Compute the 15th character from the first 14."""
    total = 0
    for i, ch in enumerate(gstin[:14]):
        value = _CODES.index(ch)
        product = value * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CODES[(36 - total % 36) % 36]


def validate_supplier_identity(
    *, gstin: str | None, business_name: str | None,
    state_code: str | None, entity_type: str | None,
) -> None:
    """Raise SupplierIdentityError unless the identity is present and coherent.

    `entity_type` is the expected PAN 4th character (e.g. "C" for a company).
    When unset the entity-type check is skipped, but every other check still
    applies — a deployment that has not declared its entity type is degraded,
    not exempt.
    """
    if not business_name or not business_name.strip():
        raise SupplierIdentityError(
            "VOLTLYNC_BUSINESS_NAME is not set. It is the supplier name printed "
            "on every GST Invoice (Rule 46) and has no safe default."
        )
    if not gstin or not gstin.strip():
        raise SupplierIdentityError(
            "VOLTLYNC_GSTIN is not set. GST Invoices cannot be issued without a "
            "supplier GSTIN (Rule 46)."
        )

    gstin = gstin.strip().upper()
    if not GSTIN_PATTERN.match(gstin):
        raise SupplierIdentityError(
            f"VOLTLYNC_GSTIN {gstin!r} is not a well-formed GSTIN "
            f"(expected 15 characters: 2 state digits, 10-char PAN, entity "
            f"digit, 'Z', check digit)."
        )

    expected = gstin_check_digit(gstin)
    if gstin[14] != expected:
        raise SupplierIdentityError(
            f"VOLTLYNC_GSTIN {gstin!r} fails its check digit (got {gstin[14]!r}, "
            f"expected {expected!r}) — most likely a transcription error."
        )

    if state_code and gstin[:2] != str(state_code).strip().zfill(2):
        raise SupplierIdentityError(
            f"VOLTLYNC_GSTIN {gstin!r} is registered in state {gstin[:2]} but "
            f"VOLTLYNC_STATE_CODE is {state_code}. The place of business on the "
            f"invoice would contradict the registration."
        )

    if entity_type:
        expected_type = entity_type.strip().upper()[:1]
        actual_type = gstin[5]
        if actual_type != expected_type:
            raise SupplierIdentityError(
                f"VOLTLYNC_GSTIN {gstin!r} belongs to a "
                f"{PAN_ENTITY_TYPES.get(actual_type, 'unknown entity type')} "
                f"(PAN 4th character {actual_type!r}), but VOLTLYNC_ENTITY_TYPE "
                f"declares {PAN_ENTITY_TYPES.get(expected_type, expected_type)!r} "
                f"and the configured supplier name is {business_name!r}. "
                f"The GSTIN and the name belong to different registered persons."
            )
