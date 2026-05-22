"""Unit tests for the Razorpay outbound audit-log helpers.

Pure logic tests for ``_mask_sensitive``. No DB, no network.
"""
import pytest

from services.razorpay_service import _mask_sensitive, _SENSITIVE_KEYS


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("pan", "BFIPJ6239L", "***239L"),
        ("account_number", "31573863930", "***3930"),
        ("ifsc_code", "SBIN0010570", "***0570"),
        ("ifsc", "SBIN0010570", "***0570"),
        ("aadhaar", "123456789012", "***9012"),
        ("aadhar", "123456789012", "***9012"),
        ("gst", "18AABCU9603R1ZM", "***R1ZM"),
        ("gstin", "18AABCU9603R1ZM", "***R1ZM"),
        ("tan", "ABCD12345E", "***345E"),
        ("card_number", "4111111111111111", "***1111"),
        ("card_id", "card_xyz", "***_xyz"),
    ],
)
def test_mask_sensitive_keys_have_last4_preserved(key, value, expected):
    masked = _mask_sensitive({key: value})
    assert masked == {key: expected}


@pytest.mark.parametrize(
    "key,value",
    [
        ("pan", "AB"),     # < 4 chars
        ("ifsc", "X"),
        ("account_number", ""),
    ],
)
def test_mask_sensitive_short_values_use_full_mask(key, value):
    masked = _mask_sensitive({key: value})
    assert masked == {key: "***"}


def test_mask_sensitive_does_not_mask_email_or_phone():
    """Email/phone are already cleartext on the franchisee row; not in
    the sensitive set."""
    body = {
        "email": "jane@example.com",
        "phone": "9876543210",
        "contact_phone": "9876543210",
    }
    masked = _mask_sensitive(body)
    assert masked == body


def test_mask_sensitive_recurses_into_nested_dicts():
    body = {
        "legal_info": {"pan": "BFIPJ6239L", "gstin": "18AABCU9603R1ZM"},
        "settlements": {
            "account_number": "31573863930",
            "ifsc_code": "SBIN0010570",
            "beneficiary_name": "JEETH JOSEPH",
        },
    }
    masked = _mask_sensitive(body)
    assert masked["legal_info"]["pan"] == "***239L"
    assert masked["legal_info"]["gstin"] == "***R1ZM"
    assert masked["settlements"]["account_number"] == "***3930"
    assert masked["settlements"]["ifsc_code"] == "***0570"
    # Non-sensitive keys remain untouched at the same nesting level.
    assert masked["settlements"]["beneficiary_name"] == "JEETH JOSEPH"


def test_mask_sensitive_recurses_into_lists():
    body = {
        "stakeholders": [
            {"name": "Jeeth", "kyc": {"pan": "BFIPJ6239L"}},
            {"name": "Other", "kyc": {"pan": "ABCDE1234F"}},
        ],
    }
    masked = _mask_sensitive(body)
    assert masked["stakeholders"][0]["kyc"]["pan"] == "***239L"
    assert masked["stakeholders"][1]["kyc"]["pan"] == "***234F"


def test_mask_sensitive_handles_none_values_at_sensitive_keys():
    """A None value at a sensitive key should pass through (not crash)."""
    masked = _mask_sensitive({"pan": None, "gstin": None})
    assert masked == {"pan": None, "gstin": None}


def test_mask_sensitive_does_not_mutate_input():
    body = {"pan": "BFIPJ6239L", "stakeholders": [{"kyc": {"pan": "X1"}}]}
    masked = _mask_sensitive(body)
    assert body["pan"] == "BFIPJ6239L"  # original untouched
    assert body["stakeholders"][0]["kyc"]["pan"] == "X1"
    assert masked["pan"] == "***239L"


def test_mask_sensitive_handles_non_dict_non_list_inputs():
    assert _mask_sensitive("plain string") == "plain string"
    assert _mask_sensitive(42) == 42
    assert _mask_sensitive(None) is None


def test_sensitive_keys_set_is_complete():
    """Sanity guard: if someone adds a sensitive key, they shouldn't
    forget the canonical names."""
    expected_minimum = {
        "pan", "account_number", "ifsc_code", "aadhaar",
        "gst", "gstin", "tan", "card_number",
    }
    assert expected_minimum.issubset(_SENSITIVE_KEYS)
