"""End-to-end test: simulate an in-flight charging session, rebuild the
backend container mid-transaction, verify the transaction resumes via the
PostBootState + MeterValues auto-resume path.

Run from the project root with the local docker stack up:
    python backend/simulators/deploy_recovery_test.py

Reuses the PostBootStateSimulator class from ocpp_simulator_post_boot_state
for the OCPP primitives. The orchestrator drives the test end-to-end:
boot → start → meter loop → backend rebuild → reconnect → PostBootState →
post-restart MeterValues → StopTransaction. Reports a verdict at the end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import websocket

# Make the simulator class importable when running from the project root.
SIM_DIR = Path(__file__).parent
sys.path.insert(0, str(SIM_DIR))
from ocpp_simulator_post_boot_state import PostBootStateSimulator  # noqa: E402


CHARGER_ID = "MG_ROAD_STATION_01"
ID_TAG = "test_rfid_830e5d98"
SERVER_WS = "ws://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def banner(text: str) -> None:
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def stamp(text: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")


def query_txn_status(txn_id: int) -> dict | None:
    """Query postgres directly for the transaction row state."""
    sql = (
        "SELECT transaction_status, suspended_at, resumed_at, resume_count, "
        "end_meter_kwh, energy_consumed_kwh, stop_reason "
        f"FROM transaction WHERE id = {txn_id};"
    )
    result = subprocess.run(
        ["docker", "exec", "ocpp-postgres", "psql", "-U", "ocpp_user",
         "-d", "ocpp_db", "-tA", "-F", "|", "-c", sql],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    fields = result.stdout.strip().split("|")
    return {
        "transaction_status": fields[0],
        "suspended_at": fields[1] or None,
        "resumed_at": fields[2] or None,
        "resume_count": fields[3] or "0",
        "end_meter_kwh": fields[4] or None,
        "energy_consumed_kwh": fields[5] or None,
        "stop_reason": fields[6] or None,
    }


def wait_for_health(timeout_seconds: int = 90) -> bool:
    """Poll the backend /health endpoint until 200 or timeout."""
    import urllib.request
    import urllib.error
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionResetError, TimeoutError):
            pass
        time.sleep(1)
    return False


def rebuild_backend() -> float:
    """Run `docker compose up -d --build backend` and return wall-clock
    seconds from kickoff until /health returns 200.
    """
    stamp("🛠  triggering: docker compose up -d --build backend")
    t0 = time.time()
    proc = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "up", "-d",
         "--build", "backend"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-800:])
        raise RuntimeError("docker compose up failed")
    stamp("🛠  docker compose returned, polling /health")
    if not wait_for_health(timeout_seconds=90):
        raise RuntimeError("backend did not become healthy within 90s")
    elapsed = time.time() - t0
    stamp(f"✅ backend healthy after {elapsed:.1f}s")
    return elapsed


def main() -> int:
    sim = PostBootStateSimulator(CHARGER_ID, server_url=SERVER_WS)

    banner("PHASE 1 — connect, boot, start a charging session")
    sim.connect()
    sim.send_boot_notification()
    # Drain any PostBootState from a stale prior session
    sim.wait_and_handle_server_calls(timeout=4)
    sim.send_status("Available")
    time.sleep(1)
    sim.send_status("Preparing")
    time.sleep(1)
    sim.send_start_transaction(id_tag=ID_TAG)
    txn_id = sim.transaction_id
    if not txn_id:
        print("❌ FAIL: no transaction_id returned from StartTransaction")
        return 1
    sim.send_status("Charging")

    banner(f"PHASE 2 — pre-restart MeterValues loop (txn={txn_id})")
    for i in range(4):
        time.sleep(2)
        sim.meter_wh += 500
        sim.send_meter_values()

    pre = query_txn_status(txn_id)
    stamp(f"📊 DB before restart: {pre}")
    assert pre and pre["transaction_status"] == "RUNNING", (
        f"expected RUNNING before restart, got {pre}"
    )

    banner("PHASE 3 — REBUILD BACKEND mid-transaction")
    # Closing the WS from our side first; in a real scenario the backend
    # would kill it. Either way the symptom on the server is "WS died with
    # no StopTransaction received."
    sim.disconnect()
    elapsed = rebuild_backend()

    banner("PHASE 4 — reconnect, expect PostBootState w/ hasPendingTransaction")
    # Brief grace period for the backend to be ready for new WS handshakes
    # after /health returns OK.
    time.sleep(2)
    sim.connect()
    sim.send_boot_notification()
    post_boot_data = sim.wait_and_handle_server_calls(timeout=15)
    if not post_boot_data:
        print("❌ FAIL: no PostBootState DataTransfer received after reconnect")
        print("        (this would mean the charger has no signal to resume)")
        return 1
    if not post_boot_data.get("hasPendingTransaction"):
        print(f"❌ FAIL: PostBootState says hasPendingTransaction=False — "
              f"backend forgot the session. payload={post_boot_data}")
        return 1
    received_txn_id = post_boot_data.get("transactionId")
    if received_txn_id != txn_id:
        print(f"❌ FAIL: PostBootState references wrong transactionId "
              f"(expected {txn_id}, got {received_txn_id})")
        return 1
    stamp(f"✅ PostBootState confirmed: txn={received_txn_id}, "
          f"lastMeterValueWh={post_boot_data.get('lastMeterValueWh')}, "
          f"energyConsumedWh={post_boot_data.get('energyConsumedWh')}")

    # Should be SUSPENDED right now (BootNotification handler marks it so).
    mid = query_txn_status(txn_id)
    stamp(f"📊 DB right after BootNotification: {mid}")

    banner("PHASE 5 — post-restart MeterValues (expect auto-resume to RUNNING)")
    sim.send_status("Charging")
    sim.meter_wh = post_boot_data["lastMeterValueWh"] + 300
    sim.send_meter_values()
    time.sleep(2)
    sim.meter_wh += 500
    sim.send_meter_values()

    after_resume = query_txn_status(txn_id)
    stamp(f"📊 DB after post-restart MeterValues: {after_resume}")
    if after_resume["transaction_status"] != "RUNNING":
        print(f"❌ FAIL: expected RUNNING after MeterValues, got "
              f"{after_resume['transaction_status']}")
        return 1

    banner("PHASE 6 — stop the transaction cleanly")
    sim.send_status("Finishing")
    sim.meter_wh += 200
    sim.send_stop_transaction(meter_stop_wh=sim.meter_wh, reason="EVDisconnected")
    time.sleep(2)
    sim.send_status("Available")
    sim.disconnect()

    final = query_txn_status(txn_id)
    stamp(f"📊 DB final: {final}")

    banner("VERDICT")
    print(f"Backend cold-restart took: {elapsed:.1f}s")
    print(f"Transaction id:            {txn_id}")
    print(f"resume_count:              {after_resume.get('resume_count')}")
    print(f"final status:              {final.get('transaction_status')}")
    print(f"energy_consumed_kwh:       {final.get('energy_consumed_kwh')}")
    if final["transaction_status"] in ("COMPLETED", "STOPPED"):
        print("✅ PASS — transaction recovered, completed, and finalized.")
        return 0
    print("⚠️  Transaction did not finalize cleanly. Inspect DB.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
