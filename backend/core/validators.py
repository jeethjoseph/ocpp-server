"""Shared validators used across public-facing routers.

Putting these in one place avoids drift between endpoints that all gate on
the same customer-typed input (e.g. UPI VPA on the `/api/public/qr-*` family).
"""
import re


# UPI VPA: alphanumeric start, optional dots/hyphens/underscores, @ followed
# by a bank/handle code of 2+ alpha-numeric chars (first char must be alpha).
# Mirrored on the frontend in `app/my-charges/page.tsx` as `VPA_INPUT_PATTERN`
# — MUST stay in sync. If you change one, change the other.
VPA_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9.\-_]{0,253}@[a-zA-Z][a-zA-Z0-9]{1,}$")
