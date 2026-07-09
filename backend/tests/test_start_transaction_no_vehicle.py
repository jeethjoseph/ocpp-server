"""Regression tests for upsert-race-hardening issue 02.

StartTransaction no longer auto-creates a placeholder VehicleProfile — it leaves
Transaction.vehicle null. This removes a non-atomic get_or_create(user=user) that
would raise MultipleObjectsReturned (locking the user out of charging) the moment
a user had more than one vehicle profile, which the one-user-many-vehicles model
explicitly allows.

Origin: upsert-race-hardening sweep — latent sibling of the Tariff prod incident.
"""
import uuid
from unittest.mock import MagicMock

from models import Transaction, User, VehicleProfile


async def _make_user_with_rfid() -> tuple[User, str]:
    rfid = f"rfid-{uuid.uuid4().hex[:8]}"
    user = await User.create(
        email=f"{uuid.uuid4().hex[:8]}@voltlync.test",
        phone_number=f"9{uuid.uuid4().int % 10**9:09d}",
        rfid_card_id=rfid,
    )
    return user, rfid


async def _start_transaction(charge_point_string_id: str, id_tag: str):
    from main import ChargePoint
    fake = MagicMock(spec=ChargePoint)
    fake.id = charge_point_string_id
    return await ChargePoint.on_start_transaction(
        fake, connector_id=1, id_tag=id_tag, meter_start=0,
        timestamp="2026-07-03T10:00:00Z",
    )


async def test_start_transaction_leaves_vehicle_null_and_creates_no_profile(
    client, test_charger
):
    """A first-time user starts a session: the transaction is created with
    vehicle=null and NO VehicleProfile is fabricated."""
    user, rfid = await _make_user_with_rfid()

    result = await _start_transaction(test_charger.charge_point_string_id, rfid)

    assert result.id_tag_info["status"] == "Accepted"
    txn = await Transaction.filter(user_id=user.id).first()
    assert txn is not None
    assert txn.vehicle_id is None
    assert await VehicleProfile.filter(user_id=user.id).count() == 0


async def test_start_transaction_with_multiple_vehicles_does_not_raise(
    client, test_charger
):
    """A user who legitimately owns two vehicles can still StartTransaction —
    the old get_or_create(user=user) would have raised MultipleObjectsReturned."""
    user, rfid = await _make_user_with_rfid()
    await VehicleProfile.create(user=user, make="Tata", model="Nexon")
    await VehicleProfile.create(user=user, make="MG", model="ZS")

    result = await _start_transaction(test_charger.charge_point_string_id, rfid)

    assert result.id_tag_info["status"] == "Accepted"
    txn = await Transaction.filter(user_id=user.id).first()
    assert txn is not None
    assert txn.vehicle_id is None
    # still exactly two — the handler added no third placeholder
    assert await VehicleProfile.filter(user_id=user.id).count() == 2
