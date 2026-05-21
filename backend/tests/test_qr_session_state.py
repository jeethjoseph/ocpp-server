"""Unit tests for the customer-facing QR session sub-state classifier.

Pure function (no DB), so these run as plain pytest functions and assert the
state-machine semantics rather than the endpoint response shape.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from models import QRPaymentStatusEnum, TransactionStatusEnum
from services.qr_session_state import (
    CHARGING, PAUSED, STOPPING, WAITING, customer_sub_state,
)


THRESHOLD = 300  # mirror of QR_PAYMENT_PENDING_TIMEOUT default for these tests


def _payment(status, age_seconds=0):
    return SimpleNamespace(
        status=status,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )


def _txn(status):
    return SimpleNamespace(transaction_status=status)


def test_waiting_paid_no_transaction():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.PAID), None,
        stale_threshold_seconds=THRESHOLD,
    ) == WAITING


def test_waiting_paid_pending_start():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.PAID),
        _txn(TransactionStatusEnum.PENDING_START),
        stale_threshold_seconds=THRESHOLD,
    ) == WAITING


def test_stale_paid_excluded():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.PAID, age_seconds=THRESHOLD + 60), None,
        stale_threshold_seconds=THRESHOLD,
    ) is None


def test_charging_running():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.CHARGING),
        _txn(TransactionStatusEnum.RUNNING),
        stale_threshold_seconds=THRESHOLD,
    ) == CHARGING


def test_charging_started():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.CHARGING),
        _txn(TransactionStatusEnum.STARTED),
        stale_threshold_seconds=THRESHOLD,
    ) == CHARGING


def test_paused_suspended():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.CHARGING),
        _txn(TransactionStatusEnum.SUSPENDED),
        stale_threshold_seconds=THRESHOLD,
    ) == PAUSED


def test_stopping_pending_stop():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.CHARGING),
        _txn(TransactionStatusEnum.PENDING_STOP),
        stale_threshold_seconds=THRESHOLD,
    ) == STOPPING


def test_terminal_qr_status_excluded():
    for terminal in (
        QRPaymentStatusEnum.COMPLETED,
        QRPaymentStatusEnum.REFUNDED,
        QRPaymentStatusEnum.EXPIRED,
        QRPaymentStatusEnum.REFUND_FAILED,
    ):
        assert customer_sub_state(
            _payment(terminal), None, stale_threshold_seconds=THRESHOLD,
        ) is None


def test_charging_without_transaction_excluded():
    assert customer_sub_state(
        _payment(QRPaymentStatusEnum.CHARGING), None,
        stale_threshold_seconds=THRESHOLD,
    ) is None
