#!/usr/bin/env python3
"""
Test script for QR-based appless charging webhook flow.

Simulates a Razorpay `qr_code.credited` webhook with a valid HMAC signature,
targeting a charger that should be connected via the OCPP simulator.

Usage (inside Docker):
    docker compose exec backend python scripts/test_qr_webhook.py --charger-id 10

Usage (local):
    cd backend && source .venv/bin/activate
    python scripts/test_qr_webhook.py --charger-id 10

Prerequisites:
    1. Server running (docker compose up or uvicorn)
    2. OCPP simulator connected for the target charger (in Preparing state)
    3. A ChargerQRCode record exists for the charger (script will tell you if not)
"""

import asyncio
import argparse
import hmac
import hashlib
import json
import os
import sys
import uuid
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    parser = argparse.ArgumentParser(description="Test QR payment webhook")
    parser.add_argument("--charger-id", type=int, required=True, help="Charger DB id")
    parser.add_argument("--amount", type=int, default=500, help="Payment amount in rupees (default: 500)")
    parser.add_argument("--vpa", default="testuser@okaxis", help="Customer UPI VPA")
    parser.add_argument("--phone", default="+919876543210", help="Customer phone")
    parser.add_argument("--server", default="http://localhost:8000", help="Server base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print payload without sending")
    args = parser.parse_args()

    # --- Step 1: Look up the ChargerQRCode from DB ---
    from tortoise import Tortoise
    from database import TORTOISE_ORM

    await Tortoise.init(config=TORTOISE_ORM)

    from models import Charger, ChargerQRCode

    charger = await Charger.filter(id=args.charger_id).first()
    if not charger:
        print(f"❌ Charger id={args.charger_id} not found in DB")
        await Tortoise.close_connections()
        sys.exit(1)

    qr_code = await ChargerQRCode.filter(charger_id=args.charger_id).first()
    if not qr_code:
        print(f"❌ No ChargerQRCode for charger id={args.charger_id} ({charger.name})")
        print(f"   Create one first via the admin UI or API:")
        print(f"   POST /api/admin/qr-codes  {{\"charger_id\": {args.charger_id}}}")
        await Tortoise.close_connections()
        sys.exit(1)

    print(f"✅ Found QR code: id={qr_code.id}, razorpay_qr_code_id={qr_code.razorpay_qr_code_id}")
    print(f"   Charger: {charger.name} ({charger.charge_point_string_id})")

    await Tortoise.close_connections()

    # --- Step 2: Get webhook secret ---
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")
    if not webhook_secret:
        print("❌ RAZORPAY_WEBHOOK_SECRET not set in environment")
        sys.exit(1)

    # --- Step 3: Build the webhook payload ---
    payment_id = f"pay_test_{uuid.uuid4().hex[:12]}"
    amount_paise = args.amount * 100  # Razorpay sends amount in paise

    payload = {
        "event": "qr_code.credited",
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": amount_paise,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "vpa": args.vpa,
                    "contact": args.phone,
                    "email": None,
                    "notes": {},
                    "description": f"QR payment test for {charger.charge_point_string_id}",
                }
            },
            "qr_code": {
                "entity": {
                    "id": qr_code.razorpay_qr_code_id,
                    "name": f"EV Charging - {charger.name}",
                    "usage": "multiple_use",
                    "type": "upi_qr",
                    "status": "active",
                }
            },
        },
    }

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    # --- Step 4: Compute HMAC-SHA256 signature ---
    signature = hmac.new(
        webhook_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()

    print(f"\n📦 Webhook payload:")
    print(f"   Payment ID: {payment_id}")
    print(f"   Amount: ₹{args.amount} ({amount_paise} paise)")
    print(f"   VPA: {args.vpa}")
    print(f"   Phone: {args.phone}")
    print(f"   QR Code ID: {qr_code.razorpay_qr_code_id}")
    print(f"   Signature: {signature[:20]}...")

    if args.dry_run:
        print(f"\n🔍 Dry run — payload:")
        print(json.dumps(payload, indent=2))
        print(f"\nSignature: {signature}")
        print(f"\ncurl command:")
        print(f"curl -X POST {args.server}/webhooks/razorpay \\")
        print(f"  -H 'Content-Type: application/json' \\")
        print(f"  -H 'X-Razorpay-Signature: {signature}' \\")
        print(f"  -d '{json.dumps(payload, separators=(',', ':'))}'")
        return

    # --- Step 5: Send the webhook ---
    import httpx

    print(f"\n🚀 Sending webhook to {args.server}/webhooks/razorpay ...")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{args.server}/webhooks/razorpay",
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
            },
            timeout=30.0,
        )

    print(f"\n📨 Response: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)

    if response.status_code == 200:
        print(f"\n✅ Webhook accepted! Check server logs and simulator output.")
        print(f"   The server should now send RemoteStartTransaction to the charger.")
    else:
        print(f"\n❌ Webhook failed. Check server logs for details.")


if __name__ == "__main__":
    asyncio.run(main())
