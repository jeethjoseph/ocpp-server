#!/usr/bin/env python3
"""
Docker Development Seed Script for OCPP Server.

Run inside the backend container:
    docker exec ocpp-backend python scripts/seed_docker.py

Env vars consumed:
    CLERK_ADMIN_ID   - your Clerk user_id; seeded as ADMIN if set
    ADMIN_EMAIL      - email for the admin user (default: admin@voltlync.dev)
    CLERK_USER_ID    - your Clerk user_id for a regular USER record
    USER_EMAIL       - email for that user (default: user@voltlync.dev)

Idempotent: re-running skips rows that already exist (keyed on natural unique
fields — clerk_user_id, station name, charger string id, etc).
"""

import asyncio
import os
import random
import sys
from datetime import timedelta
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise

from models import (
    AuthProviderEnum,
    Charger,
    ChargerStatusEnum,
    ChargingStation,
    Connector,
    Tariff,
    Transaction,
    TransactionStatusEnum,
    User,
    UserRoleEnum,
    Wallet,
)
from scripts._db import build_tortoise_config, utc_now


STATIONS_DATA = [
    {"name": "MG Road Station", "latitude": 12.9716, "longitude": 77.5946,
     "address": "MG Road, Bangalore", "pincode": "560001"},
    {"name": "Koramangala Hub", "latitude": 12.9352, "longitude": 77.6245,
     "address": "Koramangala, Bangalore", "pincode": "560034"},
    {"name": "Whitefield Plaza", "latitude": 12.9698, "longitude": 77.7500,
     "address": "Whitefield, Bangalore", "pincode": "560066"},
    {"name": "Electronic City", "latitude": 12.8399, "longitude": 77.6770,
     "address": "Electronic City, Bangalore", "pincode": "560100"},
    {"name": "Indiranagar Station", "latitude": 12.9784, "longitude": 77.6408,
     "address": "Indiranagar, Bangalore", "pincode": "560038"},
]


class DockerSeeder:
    def __init__(self):
        self.users: list[User] = []
        self.stations: list[ChargingStation] = []
        self.chargers: list[Charger] = []
        self.transactions: list[Transaction] = []
        self.tariff_rate = Decimal("12.00")
        self.gst_percent = Decimal("18.00")

        self.clerk_admin_id = os.getenv("CLERK_ADMIN_ID")
        self.admin_email = os.getenv("ADMIN_EMAIL", "admin@voltlync.dev")
        self.clerk_user_id = os.getenv("CLERK_USER_ID")
        self.user_email = os.getenv("USER_EMAIL", "user@voltlync.dev")

        self._owns_connection = False

    async def init_db(self):
        # Tortoise._inited is private API but the documented public alternative
        # (Tortoise.get_connection) raises when uninitialized, which is the
        # condition we want to detect. Stable across Tortoise 0.20+.
        if Tortoise._inited:
            return
        await Tortoise.init(config=build_tortoise_config())
        self._owns_connection = True
        print("✅ Database connection established")

    async def close_db(self):
        if self._owns_connection:
            await Tortoise.close_connections()
            print("✅ Database connection closed")

    def _users_data(self) -> list[dict]:
        admin = {
            "clerk_user_id": self.clerk_admin_id or "clerk_admin_fake_001",
            "email": self.admin_email,
            "phone_number": "+919999999999",
            "full_name": "Admin User (You)" if self.clerk_admin_id else "Test Admin",
            "role": UserRoleEnum.ADMIN,
        }
        regular = []
        if self.clerk_user_id:
            regular.append({
                "clerk_user_id": self.clerk_user_id,
                "email": self.user_email,
                "phone_number": "+918888888888",
                "full_name": "Test User (You)",
                "role": UserRoleEnum.USER,
            })
        regular.extend([
            {"clerk_user_id": "clerk_user_fake_001", "email": "alice@voltlync.dev",
             "phone_number": "+911111111111", "full_name": "Alice Driver", "role": UserRoleEnum.USER},
            {"clerk_user_id": "clerk_user_fake_002", "email": "bob@voltlync.dev",
             "phone_number": "+912222222222", "full_name": "Bob Tesla", "role": UserRoleEnum.USER},
            {"clerk_user_id": "clerk_user_fake_003", "email": "carol@voltlync.dev",
             "phone_number": "+913333333333", "full_name": "Carol Green", "role": UserRoleEnum.USER},
        ])
        return [admin, *regular]

    async def create_users(self):
        print("👥 Creating users...")
        for data in self._users_data():
            defaults = {
                **data,
                "auth_provider": AuthProviderEnum.CLERK,
                "is_email_verified": True,
                "is_active": True,
            }
            clerk_id = defaults.pop("clerk_user_id")
            user, created = await User.get_or_create(
                clerk_user_id=clerk_id, defaults=defaults
            )
            if not created:
                user.email = data["email"]
                user.role = data["role"]
                await user.save()
                print(f"  ⏭️  Updated existing user: {user.full_name}")
            else:
                emoji = "👑" if user.role == UserRoleEnum.ADMIN else "👤"
                print(f"  ✅ Created {emoji} {user.role.value}: {user.full_name}")
            self.users.append(user)

    async def create_wallets(self):
        print("💰 Creating wallets...")
        for user in self.users:
            balance = Decimal("1000.00") if user.role == UserRoleEnum.ADMIN else Decimal("500.00")
            wallet, created = await Wallet.get_or_create(
                user=user, defaults={"balance": balance}
            )
            marker = "✅ Created" if created else "⏭️  Exists"
            print(f"  {marker} wallet for {user.full_name}: ₹{wallet.balance:.2f}")

    async def create_stations_and_chargers(self):
        print("🔌 Creating charging stations and chargers...")
        for data in STATIONS_DATA:
            station = await self._upsert_station(data)
            self.stations.append(station)
            await self._upsert_chargers_for(station)

    async def _upsert_station(self, data: dict) -> ChargingStation:
        defaults = {
            "latitude": data["latitude"],
            "longitude": data["longitude"],
            "address": data["address"],
            "state": "Karnataka",
            "state_code": "29",
            "pincode": data["pincode"],
        }
        station, created = await ChargingStation.get_or_create(
            name=data["name"], defaults=defaults
        )
        marker = "✅ Created" if created else "⏭️  Exists"
        print(f"  {marker} station: {station.name}")
        return station

    async def _upsert_chargers_for(self, station: ChargingStation):
        base_id = station.name.replace(" ", "_").upper()
        for i in range(2):
            charger_id = f"{base_id}_{i + 1:02d}"
            defaults = {
                "external_charger_id": charger_id,
                "station": station,
                "name": f"Charger {i + 1}",
                "model": "FastCharge Pro",
                "vendor": "ChargePoint",
                "serial_number": f"SN{random.randint(100000, 999999)}",
                "firmware_version": "v2.1.0",
                "latest_status": ChargerStatusEnum.AVAILABLE,
                "last_heart_beat_time": utc_now(),
            }
            charger, created = await Charger.get_or_create(
                charge_point_string_id=charger_id, defaults=defaults
            )
            self.chargers.append(charger)
            if created:
                await Connector.create(
                    charger=charger, connector_id=1,
                    connector_type="CCS", max_power_kw=50.0,
                )
                print(f"    ✅ Charger: {charger_id}")
            else:
                print(f"    ⏭️  Charger exists: {charger_id}")

    async def create_tariff(self):
        print("💵 Creating tariff...")
        tariff, created = await Tariff.get_or_create(
            is_global=True,
            defaults={
                "rate_per_kwh": self.tariff_rate,
                "gst_percent": self.gst_percent,
                "hsn_sac_code": "998714",
            },
        )
        marker = "✅ Created" if created else "⏭️  Exists"
        print(f"  {marker} global tariff: ₹{tariff.rate_per_kwh}/kWh @ {tariff.gst_percent}% GST")

    async def create_sample_transactions(self):
        print("⚡ Creating sample transactions...")
        regular_users = [u for u in self.users if u.role == UserRoleEnum.USER]
        if not regular_users or not self.chargers:
            print("  ⚠️  No regular users or chargers - skipping")
            return
        existing_count = await Transaction.all().count()
        if existing_count >= 5:
            print(f"  ⏭️  {existing_count} transactions already present - skipping")
            return
        for i in range(5):
            txn = await self._create_one_transaction(i, regular_users)
            self.transactions.append(txn)

    async def _create_one_transaction(self, idx: int, users: list[User]) -> Transaction:
        user = random.choice(users)
        charger = random.choice(self.chargers)
        start = utc_now() - timedelta(days=random.randint(1, 30))
        end = start + timedelta(minutes=random.randint(30, 120))
        energy_kwh = round(random.uniform(10, 40), 2)

        energy_charge = (Decimal(str(energy_kwh)) * self.tariff_rate).quantize(Decimal("0.01"))
        gst_amount = (energy_charge * self.gst_percent / Decimal("100")).quantize(Decimal("0.01"))
        total_billed = (energy_charge + gst_amount).quantize(Decimal("0.01"))

        txn = await Transaction.create(
            user=user, charger=charger,
            start_meter_kwh=1000 + idx * 100,
            end_meter_kwh=1000 + idx * 100 + energy_kwh,
            energy_consumed_kwh=energy_kwh,
            end_time=end,
            transaction_status=TransactionStatusEnum.COMPLETED,
            stop_reason="Completed normally",
            energy_charge=energy_charge,
            gst_amount=gst_amount,
            total_billed=total_billed,
        )
        txn.start_time = start
        await txn.save()
        print(f"  ✅ Txn #{txn.id}: {energy_kwh} kWh, ₹{total_billed} (incl. GST)")
        return txn

    async def seed_all(self):
        print("=" * 60)
        print("🐳 Docker Development Database Seeder")
        print("=" * 60)
        if self.clerk_admin_id:
            print(f"✅ CLERK_ADMIN_ID set ({self.clerk_admin_id[:20]}...) — seeding you as admin")
        else:
            print("💡 Tip: set CLERK_ADMIN_ID to seed your real Clerk user as admin")
        print()

        await self.init_db()
        try:
            await self.create_users()
            await self.create_wallets()
            await self.create_stations_and_chargers()
            await self.create_tariff()
            await self.create_sample_transactions()
        finally:
            await self.close_db()

        print()
        print("=" * 60)
        print("🎉 Core seeding completed")
        print("=" * 60)
        print(f"   Users: {len(self.users)}  Stations: {len(self.stations)}  "
              f"Chargers: {len(self.chargers)}  Txns: {len(self.transactions)}")


async def main():
    await DockerSeeder().seed_all()


if __name__ == "__main__":
    asyncio.run(main())
