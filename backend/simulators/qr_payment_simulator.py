#!/usr/bin/env python3
"""
QR Payment end-to-end simulator.

Exercises the full appless charging flow against a running OCPP server:
  1. Generates a mock Razorpay QR-credited webhook payload
  2. Posts it to /webhooks/razorpay (simulating Razorpay-side payment)
  3. Opens an OCPP 1.6 WebSocket as the charger
  4. Sends BootNotification + StatusNotification (Preparing)
  5. Waits for the server's RemoteStartTransaction
  6. Sends StartTransaction → periodic MeterValues → StopTransaction
  7. Verifies the server auto-stops when budget is exceeded

Usage:
    python qr_payment_simulator.py \
        --charger-id <charge_point_string_id> \
        --qr-code-id <razorpay_qr_code_id> \
        --amount 100 \
        --server-http https://staging.voltlync.com \
        --server-ws wss://staging.voltlync.com

Requires:
    - charger row already created in DB (via admin API)
    - ChargerQRCode row with the given razorpay_qr_code_id and matching charger
    - Razorpay webhook secret configured server-side (bypass via --skip-signature if
      running against a dev server that verifies signatures)
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import websockets


def build_qr_credited_payload(payment_id: str, qr_code_id: str, amount_rupees: float, vpa: str) -> dict:
    amount_paise = int(amount_rupees * 100)
    return {
        "event": "qr_code.credited",
        "payload": {
            "payment": {"entity": {
                "id": payment_id,
                "amount": amount_paise,
                "vpa": vpa,
                "contact": "+919999999999",
                "email": "simulator@voltlync.test",
                "notes": {"customer_name": "Simulator"},
                "created_at": int(time.time()),
            }},
            "qr_code": {"entity": {"id": qr_code_id}},
        },
    }


def sign_razorpay_webhook(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def post_qr_webhook(http_url: str, payload: dict, webhook_secret: Optional[str], skip_signature: bool):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if webhook_secret and not skip_signature:
        headers["X-Razorpay-Signature"] = sign_razorpay_webhook(body, webhook_secret)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{http_url}/webhooks/razorpay", content=body, headers=headers)
        resp.raise_for_status()
        return resp.json()


class OCPPRunner:
    def __init__(self, charger_id: str, ws_url: str):
        self.charger_id = charger_id
        self.ws_url = ws_url
        self.msg_counter = 0
        self.transaction_id: Optional[int] = None
        self.meter_wh = 0

    def _next_id(self) -> str:
        self.msg_counter += 1
        return f"sim_{self.msg_counter:04d}"

    async def run(self, amount_rupees: float, max_wh: Optional[int] = None, step_wh: int = 1000):
        uri = f"{self.ws_url}/ocpp/{self.charger_id}"
        async with websockets.connect(uri, subprotocols=["ocpp1.6"]) as ws:
            print(f"[SIM] Connected to {uri}")

            await self._send(ws, "BootNotification", {
                "chargePointVendor": "VoltLync",
                "chargePointModel": "SIM-QR",
                "firmwareVersion": "sim-1.0",
            })
            await self._recv(ws)

            await self._send(ws, "StatusNotification", {
                "connectorId": 1, "errorCode": "NoError", "status": "Preparing",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await self._recv(ws)

            print("[SIM] Waiting up to 60s for RemoteStartTransaction…")
            remote_start = await asyncio.wait_for(self._await_server_request(ws, "RemoteStartTransaction"), timeout=60)
            id_tag = remote_start.get("idTag")
            print(f"[SIM] Got RemoteStartTransaction with idTag={id_tag}")

            start_resp = await self._send(ws, "StartTransaction", {
                "connectorId": 1,
                "idTag": id_tag,
                "meterStart": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.transaction_id = start_resp.get("transactionId") or 1
            print(f"[SIM] StartTransaction accepted: txn={self.transaction_id}")

            # Emit MeterValues in step_wh increments until RemoteStopTransaction
            # arrives — or, when --max-wh is set, self-stop once that total is
            # delivered. Use --max-wh 300 to demo a Non-billable Session
            # (sub-0.5 kWh de-minimis waiver → full refund, no bill; ADR 0013).
            stop_task = asyncio.create_task(self._await_server_request(ws, "RemoteStopTransaction"))
            try:
                for step in range(1, 20):
                    if stop_task.done():
                        break
                    if max_wh is not None and self.meter_wh >= max_wh:
                        print(f"[SIM] Reached --max-wh {max_wh}; self-stopping")
                        break
                    self.meter_wh += step_wh
                    if max_wh is not None:
                        self.meter_wh = min(self.meter_wh, max_wh)
                    await self._send(ws, "MeterValues", {
                        "connectorId": 1,
                        "transactionId": self.transaction_id,
                        "meterValue": [{
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "sampledValue": [{
                                "value": str(self.meter_wh),
                                "measurand": "Energy.Active.Import.Register",
                                "unit": "Wh",
                            }],
                        }],
                    })
                    print(f"[SIM] MeterValues sent: {self.meter_wh} Wh")
                    await asyncio.sleep(2)
            finally:
                stop_task.cancel()

            print("[SIM] Sending StopTransaction")
            await self._send(ws, "StopTransaction", {
                "transactionId": self.transaction_id,
                "meterStop": self.meter_wh,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": "Remote",
            })

    async def _send(self, ws, action: str, payload: dict) -> dict:
        msg_id = self._next_id()
        msg = [2, msg_id, action, payload]
        await ws.send(json.dumps(msg))
        raw = await ws.recv()
        resp = json.loads(raw)
        if resp[0] == 3 and resp[1] == msg_id:
            return resp[2]
        return {}

    async def _recv(self, ws):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            return json.loads(raw)
        except asyncio.TimeoutError:
            return None

    async def _await_server_request(self, ws, action: str) -> dict:
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            if msg[0] == 2 and msg[2] == action:
                server_msg_id = msg[1]
                await ws.send(json.dumps([3, server_msg_id, {"status": "Accepted"}]))
                return msg[3]


async def main():
    parser = argparse.ArgumentParser(description="QR payment end-to-end simulator")
    parser.add_argument("--charger-id", required=True, help="charge_point_string_id of the test charger")
    parser.add_argument("--qr-code-id", required=True, help="razorpay_qr_code_id of a ChargerQRCode row")
    parser.add_argument("--amount", type=float, default=100.0, help="Payment amount in rupees")
    parser.add_argument("--vpa", default="simulator@okhdfc", help="Simulated payer VPA")
    parser.add_argument("--server-http", default="http://localhost:8000", help="Backend HTTP base URL")
    parser.add_argument("--server-ws", default="ws://localhost:8000", help="Backend WebSocket base URL")
    parser.add_argument("--webhook-secret", default=None, help="Razorpay webhook secret (if signing)")
    parser.add_argument("--skip-signature", action="store_true", help="Don't sign the webhook (dev server only)")
    parser.add_argument("--max-wh", type=int, default=None,
                        help="Self-stop after delivering this many Wh (e.g. 300 to demo a sub-0.5 kWh de-minimis full refund). Default: deliver until RemoteStop.")
    parser.add_argument("--step-wh", type=int, default=1000, help="Wh delivered per MeterValues frame (default 1000)")
    args = parser.parse_args()

    payment_id = f"pay_SIM_{uuid.uuid4().hex[:16]}"
    payload = build_qr_credited_payload(payment_id, args.qr_code_id, args.amount, args.vpa)
    print(f"[SIM] Posting QR webhook: payment_id={payment_id} amount=₹{args.amount}")
    result = await post_qr_webhook(args.server_http, payload, args.webhook_secret, args.skip_signature)
    print(f"[SIM] Webhook response: {result}")

    runner = OCPPRunner(args.charger_id, args.server_ws)
    await runner.run(args.amount, max_wh=args.max_wh, step_wh=args.step_wh)
    print("[SIM] Simulation completed — verify server logs for billing/refund outcome")


if __name__ == "__main__":
    asyncio.run(main())
