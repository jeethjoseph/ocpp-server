"""Tests for `core.config.validate_platform_fee_percent` (issue 03).

Validation runs at FastAPI startup; we test the extracted helper directly
rather than spinning up the app.

Bands:
  - value ≤ 0          → RuntimeError
  - 0 < value ≤ 5      → info log, returns value
  - 5 < value ≤ 10     → ERROR log, returns value
  - value > 10         → RuntimeError
"""
import logging
from decimal import Decimal

import pytest

from core.config import (
    PLATFORM_FEE_HARD_CEILING,
    PLATFORM_FEE_SOFT_CEILING,
    validate_platform_fee_percent,
)


@pytest.fixture
def fake_logger():
    return logging.getLogger("test_platform_fee_validation")


@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("0"), Decimal("-0.5")])
def test_zero_or_negative_raises(value, fake_logger):
    """≤0 values would zero out customer-facing math — must refuse startup."""
    with pytest.raises(RuntimeError) as exc_info:
        validate_platform_fee_percent(value, fake_logger)
    assert "must be > 0" in str(exc_info.value)
    assert "ADR 0001" in str(exc_info.value)


@pytest.mark.parametrize("value", [Decimal("0.5"), Decimal("2.0"), Decimal("3.0"), Decimal("5.0")])
def test_inside_normal_band_returns_value_and_logs_info(value, caplog):
    """0 < value ≤ 5: normal config range, info-level log only."""
    logger = logging.getLogger("test_normal_band")
    with caplog.at_level(logging.INFO, logger=logger.name):
        result = validate_platform_fee_percent(value, logger)
    assert result == value
    # Info log fired; no error/warning emitted.
    assert any("Synthetic platform fee configured" in r.message for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


@pytest.mark.parametrize("value", [Decimal("5.5"), Decimal("7.0"), Decimal("10.0")])
def test_inside_soft_band_logs_error_but_proceeds(value, caplog):
    """5 < value ≤ 10: legitimate-but-suspicious, ERROR log, startup proceeds."""
    logger = logging.getLogger("test_soft_band")
    with caplog.at_level(logging.ERROR, logger=logger.name):
        result = validate_platform_fee_percent(value, logger)
    assert result == value
    assert any(
        r.levelno == logging.ERROR
        and "above the soft ceiling" in r.message
        for r in caplog.records
    )


@pytest.mark.parametrize("value", [Decimal("10.01"), Decimal("20"), Decimal("100")])
def test_above_hard_ceiling_raises(value, fake_logger):
    """>10: almost certainly off-by-decimal-point — must refuse startup."""
    with pytest.raises(RuntimeError) as exc_info:
        validate_platform_fee_percent(value, fake_logger)
    assert "exceeds the hard ceiling" in str(exc_info.value)
    assert "off-by-decimal-point" in str(exc_info.value)


def test_ceiling_constants_are_well_ordered():
    """Sanity guard: hard ceiling must exceed soft ceiling, else the bands
    overlap incoherently."""
    assert PLATFORM_FEE_HARD_CEILING > PLATFORM_FEE_SOFT_CEILING
    assert PLATFORM_FEE_SOFT_CEILING > 0


def test_returns_value_unchanged_on_success(fake_logger):
    """Return value composes — caller can chain or assign."""
    result = validate_platform_fee_percent(Decimal("2.0"), fake_logger)
    assert result == Decimal("2.0")
    assert isinstance(result, Decimal)
