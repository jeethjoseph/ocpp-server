#!/usr/bin/env python3
"""
Franchisee seed for the dev environment.

Run inside the backend container:
    docker exec ocpp-backend python scripts/seed_franchisees.py

Creates three franchisees representing different lifecycle states, plus one
stakeholder for the ACTIVE one, and links two existing stations to it so
station ownership rendering can be exercised end-to-end.

Idempotent on Franchisee.contact_email and FranchiseeStakeholder (franchisee,
email). Station ownership is only set when the FK is currently NULL — manual
admin changes via the UI won't be clobbered on re-run.

Run order: seed_docker.py first (provides the stations to link).
"""

import asyncio
import os
import sys
from datetime import timedelta
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise

from models import (
    ChargingStation,
    Franchisee,
    FranchiseeBusinessTypeEnum,
    FranchiseeStakeholder,
    FranchiseeStatusEnum,
)
from scripts._db import build_tortoise_config, utc_now


FRANCHISEES_DATA = [
    {
        "business_name": "Bangalore EV Partners",
        "business_type": FranchiseeBusinessTypeEnum.PRIVATE_LIMITED,
        "contact_name": "Ravi Kumar",
        "contact_email": "ravi@bangaloreevpartners.test",
        "contact_phone": "+919812345670",
        "address": "12 MG Road, Bangalore",
        "pan_number": "AAACB1234D",
        "gstin": "29AAACB1234D1Z5",
        "tan_number": "BLRA12345B",
        "city": "Bangalore",
        "state": "Karnataka",
        "state_code": "29",
        "pincode": "560001",
        "bank_account_name": "Bangalore EV Partners Pvt Ltd",
        "bank_account_number": "00112233445566",
        "bank_ifsc_code": "HDFC0000001",
        "bank_account_type": "current",
        "razorpay_account_id": "acc_test_active_001",
        "razorpay_account_status": "activated",
        "razorpay_product_id": "acc_prd_test_001",
        "transfers_enabled": True,
        "funds_on_hold": False,
        "commission_percent": Decimal("20.00"),
        "tds_rate_percent": Decimal("10.00"),
        "tds_pan_verified": True,
        "status": FranchiseeStatusEnum.ACTIVE,
        "stakeholder": {
            "name": "Ravi Kumar",
            "email": "ravi@bangaloreevpartners.test",
            "phone_primary": "+919812345670",
            "pan_number": "ABCPK1234D",
            "residential_street": "12 MG Road",
            "residential_city": "Bangalore",
            "residential_state": "Karnataka",
            "residential_postal_code": "560001",
        },
        "station_names": ["MG Road Station", "Koramangala Hub"],
    },
    {
        "business_name": "Pending KYC LLP",
        "business_type": FranchiseeBusinessTypeEnum.LLP,
        "contact_name": "Sneha Iyer",
        "contact_email": "sneha@pendingkyc.test",
        "contact_phone": "+919812345671",
        "pan_number": "AAFCP5678E",
        "gstin": "29AAFCP5678E1Z2",
        "razorpay_account_id": "acc_test_pending_002",
        "razorpay_account_status": "under_review",
        "transfers_enabled": False,
        "funds_on_hold": False,
        "status": FranchiseeStatusEnum.KYC_UNDER_REVIEW,
        "stakeholder": None,
        "station_names": [],
    },
    {
        "business_name": "Suspended Owner",
        "business_type": FranchiseeBusinessTypeEnum.PROPRIETORSHIP,
        "contact_name": "Anil Singh",
        "contact_email": "anil@suspended.test",
        "contact_phone": "+919812345672",
        "razorpay_account_id": "acc_test_suspended_003",
        "razorpay_account_status": "suspended",
        "transfers_enabled": False,
        "funds_on_hold": True,
        "status": FranchiseeStatusEnum.SUSPENDED,
        "status_reason": "Test seed: simulating suspension",
        "stakeholder": None,
        "station_names": [],
    },
]


class FranchiseeSeeder:
    def __init__(self):
        self.created: list[Franchisee] = []
        self.stakeholder_count = 0
        self.stations_linked = 0
        self._owns_connection = False

    async def init_db(self):
        if Tortoise._inited:
            return
        await Tortoise.init(config=build_tortoise_config())
        self._owns_connection = True
        print("✅ Database connection established")

    async def close_db(self):
        if self._owns_connection:
            await Tortoise.close_connections()
            print("✅ Database connection closed")

    async def create_franchisees(self):
        print("🏢 Creating franchisees...")
        for raw in FRANCHISEES_DATA:
            data = dict(raw)
            stakeholder = data.pop("stakeholder", None)
            station_names = data.pop("station_names", [])

            franchisee = await self._upsert_franchisee(data)
            self.created.append(franchisee)

            if stakeholder:
                await self._upsert_stakeholder(franchisee, stakeholder)
            for name in station_names:
                await self._link_station(franchisee, name)

    async def _upsert_franchisee(self, data: dict) -> Franchisee:
        defaults = {**data}
        if defaults["status"] == FranchiseeStatusEnum.ACTIVE:
            defaults["activated_at"] = utc_now() - timedelta(days=30)
            defaults["kyc_submitted_at"] = utc_now() - timedelta(days=32)
            defaults["kyc_verified_at"] = utc_now() - timedelta(days=30)
        elif defaults["status"] == FranchiseeStatusEnum.KYC_UNDER_REVIEW:
            defaults["kyc_submitted_at"] = utc_now() - timedelta(days=5)
        elif defaults["status"] == FranchiseeStatusEnum.SUSPENDED:
            defaults["activated_at"] = utc_now() - timedelta(days=60)
            defaults["deactivated_at"] = utc_now() - timedelta(days=3)

        contact_email = defaults.pop("contact_email")
        franchisee, created = await Franchisee.get_or_create(
            contact_email=contact_email, defaults=defaults
        )
        marker = "✅ Created" if created else "⏭️  Exists"
        print(f"  {marker}: {franchisee.business_name} [{franchisee.status.value}]")
        return franchisee

    async def _upsert_stakeholder(self, franchisee: Franchisee, data: dict):
        existing = await FranchiseeStakeholder.filter(
            franchisee=franchisee, email=data["email"]
        ).first()
        if existing:
            print(f"    ⏭️  Stakeholder exists: {data['name']}")
            return
        await FranchiseeStakeholder.create(franchisee=franchisee, **data)
        self.stakeholder_count += 1
        print(f"    ✅ Stakeholder: {data['name']}")

    async def _link_station(self, franchisee: Franchisee, station_name: str):
        station = await ChargingStation.filter(name=station_name).first()
        if not station:
            print(f"    ⚠️  Station '{station_name}' not found — run seed_docker.py first")
            return
        if station.franchisee_id is not None:
            current = await Franchisee.filter(id=station.franchisee_id).first()
            owner = current.business_name if current else f"#{station.franchisee_id}"
            print(f"    ⏭️  Station '{station_name}' already owned by {owner}")
            return
        station.franchisee = franchisee
        await station.save()
        self.stations_linked += 1
        print(f"    ✅ Linked station '{station_name}' to {franchisee.business_name}")

    async def seed_all(self):
        print("=" * 60)
        print("🏢 Franchisee Seeder")
        print("=" * 60)
        await self.init_db()
        try:
            await self.create_franchisees()
        finally:
            await self.close_db()
        print()
        print("=" * 60)
        print("🎉 Franchisee seeding completed")
        print(f"   Franchisees: {len(self.created)}  Stakeholders: {self.stakeholder_count}  "
              f"Stations linked: {self.stations_linked}")
        print("=" * 60)


async def main():
    await FranchiseeSeeder().seed_all()


if __name__ == "__main__":
    asyncio.run(main())
