#!/usr/bin/env python3
"""
Docker Development Seed Script for OCPP Server
Creates sample data with support for real Clerk user IDs

Usage:
    # Basic seed with fake users:
    python scripts/seed_docker.py

    # Seed with your real Clerk user ID as admin:
    CLERK_ADMIN_ID=user_xxxx python scripts/seed_docker.py

    # Or set multiple users:
    CLERK_ADMIN_ID=user_xxxx CLERK_USER_ID=user_yyyy python scripts/seed_docker.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
import random

# Add the parent directory to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from models import (
    User, UserRoleEnum,
    Wallet, WalletTransaction, TransactionTypeEnum,
    ChargingStation, Charger, ChargerStatusEnum, Connector,
    Tariff, Transaction, TransactionStatusEnum,
    MeterValue, OCPPLog, MessageDirectionEnum
)

# Database URL for Docker
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgres://{os.getenv('DB_USER', 'ocpp')}:{os.getenv('DB_PASSWORD', 'ocpp_password')}@{os.getenv('DB_HOST', 'postgres')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'ocpp_db')}"
)

TORTOISE_CONFIG = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            "models": ["models", "aerich.models"],
            "default_connection": "default",
        },
    },
}

class DockerSeeder:
    def __init__(self):
        self.users = []
        self.stations = []
        self.chargers = []
        self.transactions = []

        # Get real Clerk IDs from environment
        self.clerk_admin_id = os.getenv("CLERK_ADMIN_ID")
        self.clerk_user_id = os.getenv("CLERK_USER_ID")

    async def init_db(self):
        await Tortoise.init(config=TORTOISE_CONFIG)
        print("✅ Database connection established")
        print(f"   Using: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")

    async def close_db(self):
        await Tortoise.close_connections()
        print("✅ Database connection closed")

    async def create_users(self):
        """Create users - prioritizes real Clerk IDs if provided"""
        print("👥 Creating users...")

        users_data = []

        # Real admin user (if Clerk ID provided)
        if self.clerk_admin_id:
            users_data.append({
                "clerk_user_id": self.clerk_admin_id,
                "phone_number": "+919999999999",
                "full_name": "Admin User (You)",
                "role": UserRoleEnum.ADMIN,
                "is_active": True,
            })
            print(f"  📌 Will create ADMIN with your Clerk ID: {self.clerk_admin_id[:20]}...")
        else:
            # Fake admin
            users_data.append({
                "clerk_user_id": "clerk_admin_fake_001",
                "phone_number": "+911234567890",
                "full_name": "Test Admin",
                "role": UserRoleEnum.ADMIN,
                "is_active": True,
            })
            print("  ⚠️  No CLERK_ADMIN_ID set - creating fake admin")

        # Real regular user (if Clerk ID provided)
        if self.clerk_user_id:
            users_data.append({
                "clerk_user_id": self.clerk_user_id,
                "phone_number": "+918888888888",
                "full_name": "Test User (You)",
                "role": UserRoleEnum.USER,
                "is_active": True,
            })

        # Additional fake users for testing
        fake_users = [
            {"clerk_user_id": "clerk_user_fake_001", "phone_number": "+911111111111", "full_name": "Alice Driver", "role": UserRoleEnum.USER},
            {"clerk_user_id": "clerk_user_fake_002", "phone_number": "+912222222222", "full_name": "Bob Tesla", "role": UserRoleEnum.USER},
            {"clerk_user_id": "clerk_user_fake_003", "phone_number": "+913333333333", "full_name": "Carol Green", "role": UserRoleEnum.USER},
        ]
        users_data.extend(fake_users)

        for user_data in users_data:
            user_data["is_active"] = user_data.get("is_active", True)
            try:
                # Check if user already exists
                existing = await User.filter(clerk_user_id=user_data["clerk_user_id"]).first()
                if existing:
                    print(f"  ⏭️  User already exists: {user_data['full_name']}")
                    self.users.append(existing)
                    continue

                user = await User.create(**user_data)
                self.users.append(user)
                role_emoji = "👑" if user.role == UserRoleEnum.ADMIN else "👤"
                print(f"  ✅ Created {role_emoji} {user.role.value}: {user.full_name}")
            except Exception as e:
                print(f"  ❌ Failed to create {user_data['full_name']}: {e}")

    async def create_wallets(self):
        """Create wallets for all users"""
        print("💰 Creating wallets...")

        for user in self.users:
            try:
                existing = await Wallet.filter(user=user).first()
                if existing:
                    print(f"  ⏭️  Wallet exists for {user.full_name}: ₹{existing.balance}")
                    continue

                balance = Decimal("1000.00") if user.role == UserRoleEnum.ADMIN else Decimal("500.00")
                wallet = await Wallet.create(user=user, balance=balance)
                print(f"  ✅ Created wallet for {user.full_name}: ₹{balance}")
            except Exception as e:
                print(f"  ❌ Failed to create wallet for {user.full_name}: {e}")

    async def create_stations_and_chargers(self):
        """Create charging infrastructure"""
        print("🔌 Creating charging stations and chargers...")

        stations_data = [
            {"name": "MG Road Station", "latitude": 12.9716, "longitude": 77.5946, "address": "MG Road, Bangalore"},
            {"name": "Koramangala Hub", "latitude": 12.9352, "longitude": 77.6245, "address": "Koramangala, Bangalore"},
            {"name": "Whitefield Plaza", "latitude": 12.9698, "longitude": 77.7500, "address": "Whitefield, Bangalore"},
            {"name": "Electronic City", "latitude": 12.8399, "longitude": 77.6770, "address": "Electronic City, Bangalore"},
            {"name": "Indiranagar Station", "latitude": 12.9784, "longitude": 77.6408, "address": "Indiranagar, Bangalore"},
        ]

        for station_data in stations_data:
            try:
                existing = await ChargingStation.filter(name=station_data["name"]).first()
                if existing:
                    self.stations.append(existing)
                    print(f"  ⏭️  Station exists: {station_data['name']}")
                    # Still load chargers for this station
                    chargers = await Charger.filter(station=existing).all()
                    self.chargers.extend(chargers)
                    continue

                station = await ChargingStation.create(**station_data)
                self.stations.append(station)
                print(f"  ✅ Created station: {station.name}")

                # Create 2 chargers per station
                for i in range(2):
                    charger_id = f"{station.name.replace(' ', '_').upper()}_{i+1:02d}"
                    charger = await Charger.create(
                        charge_point_string_id=charger_id,
                        station=station,
                        name=f"Charger {i+1}",
                        model="FastCharge Pro",
                        vendor="ChargePoint",
                        serial_number=f"SN{random.randint(100000, 999999)}",
                        firmware_version="v2.1.0",
                        latest_status=ChargerStatusEnum.AVAILABLE,
                        last_heart_beat_time=datetime.now()
                    )
                    self.chargers.append(charger)

                    # Create connector
                    await Connector.create(
                        charger=charger,
                        connector_id=1,
                        connector_type="CCS",
                        max_power_kw=50.0
                    )
                    print(f"    ✅ Charger: {charger_id}")

            except Exception as e:
                print(f"  ❌ Failed: {e}")

    async def create_tariff(self):
        """Create global tariff"""
        print("💵 Creating tariff...")

        existing = await Tariff.filter(is_global=True).first()
        if existing:
            print(f"  ⏭️  Global tariff exists: ₹{existing.rate_per_kwh}/kWh")
            return

        await Tariff.create(rate_per_kwh=Decimal("12.00"), is_global=True)
        print("  ✅ Created global tariff: ₹12.00/kWh")

    async def create_sample_transactions(self):
        """Create some sample charging transactions"""
        print("⚡ Creating sample transactions...")

        if not self.users or not self.chargers:
            print("  ⚠️  No users or chargers - skipping transactions")
            return

        regular_users = [u for u in self.users if u.role == UserRoleEnum.USER]
        if not regular_users:
            print("  ⚠️  No regular users - skipping transactions")
            return

        for i in range(5):
            user = random.choice(regular_users)
            charger = random.choice(self.chargers)

            start_time = datetime.now() - timedelta(days=random.randint(1, 30))
            end_time = start_time + timedelta(minutes=random.randint(30, 120))
            energy = random.uniform(10, 40)

            try:
                txn = await Transaction.create(
                    user=user,
                    charger=charger,
                    start_meter_kwh=1000 + i * 100,
                    end_meter_kwh=1000 + i * 100 + energy,
                    energy_consumed_kwh=energy,
                    end_time=end_time,
                    transaction_status=TransactionStatusEnum.COMPLETED,
                    stop_reason="Completed normally"
                )
                # Update start_time
                txn.start_time = start_time
                await txn.save()

                self.transactions.append(txn)
                print(f"  ✅ Transaction #{txn.id}: {energy:.1f} kWh at {charger.name}")
            except Exception as e:
                print(f"  ❌ Failed: {e}")

    async def seed_all(self):
        """Run all seeding operations"""
        print("=" * 60)
        print("🐳 Docker Development Database Seeder")
        print("=" * 60)

        if self.clerk_admin_id:
            print(f"✅ CLERK_ADMIN_ID detected - you'll be seeded as admin")
        else:
            print("💡 Tip: Set CLERK_ADMIN_ID=your_clerk_id to seed yourself as admin")

        print()

        try:
            await self.init_db()

            await self.create_users()
            await self.create_wallets()
            await self.create_stations_and_chargers()
            await self.create_tariff()
            await self.create_sample_transactions()

            print()
            print("=" * 60)
            print("🎉 Seeding completed!")
            print("=" * 60)
            print(f"📊 Summary:")
            print(f"   Users: {len(self.users)}")
            print(f"   Stations: {len(self.stations)}")
            print(f"   Chargers: {len(self.chargers)}")
            print(f"   Transactions: {len(self.transactions)}")

            if self.clerk_admin_id:
                print()
                print("🔐 Your admin account is ready - refresh the browser!")
            else:
                print()
                print("⚠️  To login as admin, run:")
                print(f"   CLERK_ADMIN_ID=your_clerk_user_id python scripts/seed_docker.py")

        except Exception as e:
            print(f"❌ Error during seeding: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            await self.close_db()

async def main():
    seeder = DockerSeeder()
    await seeder.seed_all()

if __name__ == "__main__":
    asyncio.run(main())
