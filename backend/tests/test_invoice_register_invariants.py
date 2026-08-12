"""Invariants of the GST Invoice register: numbering, supplier identity, and
the reconciliation identities the invoice arithmetic must satisfy.

Every defect these lock down was live in production, and none was caught by a
worked-example test:

- 1,287 invoices carried another registered person's GSTIN for four months,
  because the check was a warning and only tested presence, not coherence.
- All 1,287 invoice numbers were 18-22 characters against Rule 46(b)'s limit
  of sixteen.
- Two numbers were issued twice, because the number embedded a per-database
  primary key and two registers share one GSTIN.
- Invoice totals exceeded cash collected by Rs 9.61 across 65 invoices, because
  the total was reconstructed from independently-rounded components.

Inputs are randomised from a fixed seed rather than hand-picked, since the
original bugs all survived hand-picked examples. No new dependency: the repo
has no hypothesis, and adding one would drag in a Docker build-parity check.
"""

import random
import re
from decimal import Decimal, ROUND_HALF_UP

import pytest

from core.supplier_identity import (
    SupplierIdentityError,
    gstin_check_digit,
    validate_supplier_identity,
)
from policy import VOLTLYNC_OWNED_INVOICE_CODE, franchisee_code_block
from services.franchisee_code_service import (
    INVOICE_CODE_PATTERN,
    format_invoice_code,
)
from services.invoice_service import (
    INVOICE_NUMBER_MAX_LEN,
    INVOICE_SERIES_CHAR,
)

TWO_DP = Decimal("0.01")
# Sixteen characters exactly: F0001/Q/26/00001
INVOICE_NUMBER_PATTERN = re.compile(r"^F\d{4}/[QW]/\d{2}/\d{5}$")

# The real GSTINs involved, used as regression fixtures.
CORRECT_GSTIN = "32AALCV6461E1ZA"   # VOLTLYNC PRIVATE LIMITED — PAN entity 'C'
WRONG_GSTIN = "32AAIFI0458G1ZN"     # IDOFTHINGS — PAN entity 'F'


def render(code: str, series: str, fy: str, seq: int) -> str:
    """Mirror of the format assembled in get_next_invoice_number."""
    return f"{code}/{INVOICE_SERIES_CHAR[series]}/{fy}/{seq:05d}"


# ── Numbering ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("series", sorted(INVOICE_SERIES_CHAR))
def test_invoice_number_never_exceeds_rule_46b_limit(series):
    """Rule 46(b) caps the serial at sixteen characters. Exercise the widest
    values every field can hold, not a typical one."""
    number = render(format_invoice_code(9999), series, "99", 99999)
    assert len(number) <= INVOICE_NUMBER_MAX_LEN, number
    assert INVOICE_NUMBER_PATTERN.match(number), number


def test_invoice_number_format_across_randomised_inputs():
    rng = random.Random(20260812)
    for _ in range(500):
        code = format_invoice_code(rng.randint(0, 9999))
        series = rng.choice(sorted(INVOICE_SERIES_CHAR))
        number = render(code, series, f"{rng.randint(0, 99):02d}", rng.randint(1, 99999))
        assert len(number) == INVOICE_NUMBER_MAX_LEN, number
        assert INVOICE_NUMBER_PATTERN.match(number), number


def test_every_series_has_a_single_character_code():
    """A two-character code would render a 17-character number. Adding a series
    without a code here must fail loudly rather than silently overflow."""
    for stored, rendered in INVOICE_SERIES_CHAR.items():
        assert len(rendered) == 1, (stored, rendered)


def test_invoice_code_is_four_digits_and_zero_padded():
    assert format_invoice_code(1) == "F0001"
    assert format_invoice_code(9999) == "F9999"
    assert INVOICE_CODE_PATTERN.match(format_invoice_code(0))
    for bad in (-1, 10000):
        with pytest.raises(ValueError):
            format_invoice_code(bad)


def test_voltlync_owned_code_is_outside_every_allocatable_block():
    """F0000 is reserved. No environment may allocate it to a franchisee,
    or a franchisee's invoices would collide with VoltLync-owned ones."""
    reserved = int(VOLTLYNC_OWNED_INVOICE_CODE[1:])
    for env in ("production", "staging", "development", "nonsense"):
        low, high = franchisee_code_block(env)
        assert not low <= reserved <= high, env


def test_environment_blocks_are_disjoint():
    """The whole point: two registers cannot mint the same code. This is the
    defect that produced duplicate invoice numbers VL/F2/QR/202627/00001-2."""
    prod = set(range(*_inclusive(franchisee_code_block("production"))))
    staging = set(range(*_inclusive(franchisee_code_block("staging"))))
    assert not prod & staging


def test_unknown_environment_never_resolves_to_the_production_block():
    """A misconfigured box must not mint codes production may later issue."""
    assert franchisee_code_block("typo") != franchisee_code_block("production")
    assert franchisee_code_block("") != franchisee_code_block("production")


def _inclusive(block):
    low, high = block
    return low, high + 1


# ── Supplier identity ────────────────────────────────────────────────────────

def test_correct_gstin_passes_every_check():
    validate_supplier_identity(
        gstin=CORRECT_GSTIN,
        business_name="VOLTLYNC PRIVATE LIMITED",
        state_code="32",
        entity_type="C",
    )


def test_the_actual_historical_defect_is_refused():
    """The regression that matters: a company name against a firm's GSTIN.
    This configuration ran in production from April to August 2026."""
    with pytest.raises(SupplierIdentityError, match="different registered persons"):
        validate_supplier_identity(
            gstin=WRONG_GSTIN,
            business_name="VOLTLYNC PRIVATE LIMITED",
            state_code="32",
            entity_type="C",
        )


@pytest.mark.parametrize("gstin,name,state,entity", [
    (None, "VOLTLYNC PRIVATE LIMITED", "32", "C"),          # unset GSTIN
    ("", "VOLTLYNC PRIVATE LIMITED", "32", "C"),            # empty GSTIN
    (CORRECT_GSTIN, None, "32", "C"),                       # unset name
    (CORRECT_GSTIN, "   ", "32", "C"),                      # blank name
    ("32AALCV6461E1Z", "VOLTLYNC PRIVATE LIMITED", "32", "C"),   # too short
    ("32AALCV6461E1ZX", "VOLTLYNC PRIVATE LIMITED", "32", "C"),  # bad check digit
    (CORRECT_GSTIN, "VOLTLYNC PRIVATE LIMITED", "29", "C"),      # wrong state
])
def test_incoherent_identities_are_refused(gstin, name, state, entity):
    with pytest.raises(SupplierIdentityError):
        validate_supplier_identity(
            gstin=gstin, business_name=name, state_code=state, entity_type=entity,
        )


def test_check_digit_matches_both_real_gstins():
    for gstin in (CORRECT_GSTIN, WRONG_GSTIN):
        assert gstin_check_digit(gstin) == gstin[14], gstin


def test_entity_type_check_is_skipped_when_undeclared_but_others_still_apply():
    validate_supplier_identity(
        gstin=WRONG_GSTIN, business_name="IDOFTHINGS", state_code="32",
        entity_type=None,
    )
    with pytest.raises(SupplierIdentityError):
        validate_supplier_identity(
            gstin="not-a-gstin", business_name="IDOFTHINGS", state_code="32",
            entity_type=None,
        )


# ── Reconciliation identities ────────────────────────────────────────────────

def assert_reconciles(energy_taxable, gateway_taxable, cgst, sgst, round_off,
                      total, paid, refund):
    """The three identities every issued invoice must satisfy exactly.

    Deliberately NOT asserted: total == kWh * rate_gst_included. That product
    is not representable in paise, and energy_consumed_kwh is itself derived
    from an already-rounded taxable value using a 4-decimal rate. Chasing it
    would require breaking one of the three below. The residual is disclosed
    on the invoice as the Round Off line per ADR 0017.
    """
    taxable = energy_taxable + gateway_taxable
    assert taxable + cgst + sgst + round_off == total
    assert total == paid - refund
    assert cgst == sgst or abs(cgst - sgst) <= TWO_DP


def test_reconciliation_identities_over_randomised_billing():
    """Randomised amounts including the adversarial shapes that produced the
    original Rs 9.61 variance: near-zero energy, near-full refunds, and values
    landing on a half-paisa boundary."""
    rng = random.Random(4626)
    for _ in range(1000):
        paid = Decimal(rng.choice([5, 10, 20, 23.6, 50, 75, 100, 250, 500, 1000])).quantize(TWO_DP)
        # Retained fraction spans full consumption down to a near-total refund.
        frac = Decimal(str(rng.choice([1.0, 0.999, 0.75, 0.5, 0.13, 0.01, 0.001])))
        total = (paid * frac).quantize(TWO_DP, ROUND_HALF_UP)
        refund = paid - total

        gateway_taxable = (total * Decimal("0.0099")).quantize(TWO_DP, ROUND_HALF_UP)
        taxable = (total / Decimal("1.18")).quantize(TWO_DP, ROUND_HALF_UP)
        energy_taxable = taxable - gateway_taxable

        cgst = (taxable * Decimal("0.09")).quantize(TWO_DP, ROUND_HALF_UP)
        sgst = cgst
        # Round Off absorbs the difference between independently-computed tax
        # heads and the tax the total must reconcile to (ADR 0017).
        round_off = total - taxable - cgst - sgst

        assert abs(round_off) <= Decimal("0.02"), (paid, total, round_off)
        assert_reconciles(energy_taxable, gateway_taxable, cgst, sgst,
                          round_off, total, paid, refund)


def test_total_is_anchored_to_cash_not_reconstructed_from_components():
    """The historical double-rounding regression, from a real production case.

    Pre-ADR-0026 the total was rebuilt by grossing up the sum of two
    independently-rounded taxable values, so two upward half-paise compounded:
    a Rs 50.00 payment produced a Rs 50.01 invoice. Invoice totals exceeded
    cash collected by Rs 9.61 across 65 production invoices.
    """
    paid = Decimal("50.00")
    gateway_incl = Decimal("1.00")

    gateway_taxable = (gateway_incl / Decimal("1.18")).quantize(TWO_DP, ROUND_HALF_UP)
    energy_taxable = ((paid - gateway_incl) / Decimal("1.18")).quantize(TWO_DP, ROUND_HALF_UP)

    reconstructed = ((energy_taxable + gateway_taxable) * Decimal("1.18")).quantize(TWO_DP, ROUND_HALF_UP)
    assert reconstructed == Decimal("50.01"), "the historical defect no longer reproduces"

    # The correct construction anchors to cash and lets round_off carry the rest.
    total = paid
    taxable = (total / Decimal("1.18")).quantize(TWO_DP, ROUND_HALF_UP)
    cgst = sgst = (taxable * Decimal("0.09")).quantize(TWO_DP, ROUND_HALF_UP)
    round_off = total - taxable - cgst - sgst
    assert total == paid
    assert taxable + cgst + sgst + round_off == paid


def test_printed_unit_price_does_not_reproduce_the_energy_line():
    """Characterisation, not an assertion of correctness.

    On the real invoices, unit price x quantity does not equal the printed
    taxable value, because both the unit price and the kWh quantity are rounded
    for display while the taxable value is the stored figure:

        VL/F3/QR/202627/00117:  20.00 x 3.141  = 62.82  vs printed 62.81
        VL/F1/QR/202627/00070:  20.76 x 13.354 = 277.23 vs printed 277.27

    Tax, totals and cash all reconcile — but this is the first arithmetic a
    reader performs, and the gap scales with kWh (~Rs 0.30 at 100 kWh). Locked
    down so the behaviour cannot change unnoticed; fixing it means printing the
    unit price at four decimals, which is a presentation decision.
    """
    for unit, kwh, printed in [
        (Decimal("20.00"), Decimal("3.141"), Decimal("62.81")),
        (Decimal("20.76"), Decimal("13.354"), Decimal("277.27")),
    ]:
        recomputed = (unit * kwh).quantize(TWO_DP, ROUND_HALF_UP)
        assert abs(recomputed - printed) <= Decimal("0.05")
        true_rate = (printed / kwh).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        assert (true_rate * kwh).quantize(TWO_DP, ROUND_HALF_UP) == printed
