#!/usr/bin/env python3
"""
Seed script for OCPP Server database
Creates comprehensive sample data for development and testing
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal
import random
from typing import List

# Add the parent directory to the path so we can import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from models import (
    User, UserRoleEnum, AuthProviderEnum,
    Wallet, WalletTransaction, TransactionTypeEnum,
    PaymentGateway, VehicleProfile, ValidVehicleProfile,
    ChargingStation, Charger, ChargerStatusEnum, Connector,
    Tariff, Transaction, TransactionStatusEnum,
    MeterValue, OCPPLog, MessageDirectionEnum
)
from tortoise_config import TORTOISE_ORM

class DatabaseSeeder:
    def __init__(self):
        self.users = []
        self.stations = []
        self.chargers = []
        self.vehicles = []
        self.transactions = []

    async def init_db(self):
        """Initialize database connection"""
        await Tortoise.init(config=TORTOISE_ORM)
        print("✅ Database connection established")

    async def close_db(self):
        """Close database connection"""
        await Tortoise.close_connections()
        print("✅ Database connection closed")

    async def create_users(self):
        """Create sample users with different roles and profiles"""
        print("👥 Creating users...")
        
        # Admin users
        admin_data = [
            {
                "email": "admin@ocpp.com",
                "full_name": "System Administrator",
                "role": UserRoleEnum.ADMIN,
                "phone_number": "+1234567890",
                "is_email_verified": True,
                "terms_accepted_at": datetime.now(),
                "rfid_card_id": "ADMIN001"
            },
            {
                "email": "manager@ocpp.com", 
                "full_name": "Station Manager",
                "role": UserRoleEnum.ADMIN,
                "phone_number": "+1234567891",
                "is_email_verified": True,
                "terms_accepted_at": datetime.now(),
                "rfid_card_id": "ADMIN002"
            }
        ]
        
        # Regular EV drivers
        driver_data = [
            {
                "email": "alice.driver@email.com",
                "full_name": "Alice Johnson",
                "phone_number": "+1555000001",
                "rfid_card_id": "USER001",
                "preferred_language": "en",
                "notification_preferences": {"email": True, "sms": False, "push": True}
            },
            {
                "email": "bob.tesla@email.com",
                "full_name": "Bob Tesla",
                "phone_number": "+1555000002", 
                "rfid_card_id": "USER002",
                "preferred_language": "en",
                "notification_preferences": {"email": True, "sms": True, "push": True}
            },
            {
                "email": "carol.green@email.com",
                "full_name": "Carol Green",
                "phone_number": "+1555000003",
                "rfid_card_id": "USER003",
                "preferred_language": "es",
                "notification_preferences": {"email": False, "sms": True, "push": True}
            },
            {
                "email": "david.volt@email.com",
                "full_name": "David Volt",
                "phone_number": "+1555000004",
                "rfid_card_id": "USER004",
                "clerk_user_id": "clerk_david_123",
                "auth_provider": AuthProviderEnum.CLERK
            },
            {
                "email": "emma.electric@email.com",
                "full_name": "Emma Electric",
                "phone_number": "+1555000005",
                "rfid_card_id": "USER005",
                "auth_provider": AuthProviderEnum.GOOGLE,
                "avatar_url": "https://example.com/avatars/emma.jpg"
            }
        ]
        
        # Create admin users
        for admin in admin_data:
            try:
                user = await User.create(**admin)
                self.users.append(user)
                print(f"  ✅ Created admin: {user.email}")
            except Exception as e:
                print(f"  ❌ Failed to create admin {admin['email']}: {str(e)}")
            
        # Create driver users
        for driver in driver_data:
            driver.update({
                "role": UserRoleEnum.USER,
                "is_email_verified": True,
                "terms_accepted_at": datetime.now(),
                "last_login": datetime.now() - timedelta(days=random.randint(1, 30))
            })
            try:
                user = await User.create(**driver)
                self.users.append(user)
                print(f"  ✅ Created user: {user.email}")
            except Exception as e:
                print(f"  ❌ Failed to create user {driver['email']}: {str(e)}")

    async def create_wallets_and_transactions(self):
        """Create wallets and transaction history for users"""
        print("💰 Creating wallets and transactions...")
        
        # Refresh users from database to get current IDs after any truncation
        fresh_users = await User.all()
        print(f"  Found {len(fresh_users)} users in database")
        
        for user in fresh_users:
            # Create wallets for ALL users (admins and regular users)
            # Admins can also be charged for transactions they start
            if user.role == UserRoleEnum.USER:
                # Regular users get random balance
                initial_balance = Decimal(random.uniform(50, 500)).quantize(Decimal('0.01'))
            else:
                # Admins start with a higher balance for testing
                initial_balance = Decimal(random.uniform(1000, 2000)).quantize(Decimal('0.01'))
                
            wallet = await Wallet.create(
                user=user,
                balance=initial_balance
            )
            
            # Create some top-up transactions (only for regular users to keep it simple)
            if user.role == UserRoleEnum.USER:
                top_up_count = random.randint(2, 5)
                for i in range(top_up_count):
                    amount = Decimal(random.uniform(25, 100)).quantize(Decimal('0.01'))
                    await WalletTransaction.create(
                        wallet=wallet,
                        amount=amount,
                        type=TransactionTypeEnum.TOP_UP,
                        description=f"Top-up via payment gateway #{i+1}",
                        payment_metadata={
                            "gateway": "stripe",
                            "payment_method": random.choice(["card", "bank_transfer"]),
                            "transaction_id": f"txn_{random.randint(100000, 999999)}"
                        },
                        created_at=datetime.now() - timedelta(days=random.randint(1, 60))
                    )
            
            print(f"  ✅ Created wallet for {user.email} with balance ₹{initial_balance}")

    async def create_payment_gateways(self):
        """Create payment gateway configurations"""
        print("💳 Creating payment gateways...")
        
        gateways = [
            {
                "name": "Stripe",
                "api_key": "sk_test_stripe_key_placeholder",
                "webhook_secret": "whsec_stripe_placeholder",
                "status": True,
                "config": {
                    "supported_methods": ["card", "bank_transfer"],
                    "currencies": ["USD", "INR", "EUR"],
                    "webhook_url": "https://api.ocpp.com/webhooks/stripe"
                },
                "default_currency": "USD"
            },
            {
                "name": "Razorpay",
                "api_key": "rzp_test_key_placeholder", 
                "webhook_secret": "rzp_webhook_secret_placeholder",
                "status": True,
                "config": {
                    "supported_methods": ["card", "upi", "netbanking", "wallet"],
                    "currencies": ["INR"],
                    "webhook_url": "https://api.ocpp.com/webhooks/razorpay"
                },
                "default_currency": "INR"
            }
        ]
        
        for gateway_data in gateways:
            gateway = await PaymentGateway.create(**gateway_data)
            print(f"  ✅ Created payment gateway: {gateway.name}")

    async def create_vehicle_profiles(self):
        """Create vehicle profiles and valid vehicle types"""
        print("🚗 Creating vehicle profiles...")
        
        # Valid vehicle types (for validation)
        valid_vehicles = [
            {"make": "Tesla", "model": "Model 3", "year": 2023},
            {"make": "Tesla", "model": "Model S", "year": 2023},
            {"make": "Tesla", "model": "Model Y", "year": 2022},
            {"make": "Nissan", "model": "Leaf", "year": 2023},
            {"make": "Chevrolet", "model": "Bolt EV", "year": 2022},
            {"make": "BMW", "model": "i3", "year": 2021},
            {"make": "Audi", "model": "e-tron", "year": 2023},
            {"make": "Ford", "model": "Mustang Mach-E", "year": 2022},
            {"make": "Hyundai", "model": "Kona Electric", "year": 2023},
            {"make": "Volkswagen", "model": "ID.4", "year": 2022}
        ]
        
        for vehicle_data in valid_vehicles:
            await ValidVehicleProfile.create(**vehicle_data)
            
        # User vehicle profiles
        user_vehicles = [
            {"user": self.users[2], "make": "Tesla", "model": "Model 3", "year": 2023},
            {"user": self.users[3], "make": "Tesla", "model": "Model S", "year": 2022},
            {"user": self.users[4], "make": "Nissan", "model": "Leaf", "year": 2023},
            {"user": self.users[5], "make": "BMW", "model": "i3", "year": 2021},
            {"user": self.users[6], "make": "Tesla", "model": "Model Y", "year": 2023},
        ]
        
        for vehicle_data in user_vehicles:
            vehicle = await VehicleProfile.create(**vehicle_data)
            self.vehicles.append(vehicle)
            print(f"  ✅ Created vehicle: {vehicle.make} {vehicle.model} for {vehicle_data['user'].email}")

    async def create_charging_infrastructure(self):
        """Create charging stations, chargers, and connectors"""
        print("🔌 Creating charging infrastructure...")
        
        # Charging stations with realistic locations
        stations_data = [
            {
                "name": "Downtown Plaza Station",
                "latitude": 37.7749,
                "longitude": -122.4194,
                "address": "123 Market St, San Francisco, CA 94105"
            },
            {
                "name": "Airport Express Charging",
                "latitude": 37.6213,
                "longitude": -122.3790,
                "address": "San Francisco International Airport, CA 94128"
            },
            {
                "name": "Shopping Mall Fast Charge",
                "latitude": 37.4419,
                "longitude": -122.1430,
                "address": "1 Hacker Way, Menlo Park, CA 94025"
            },
            {
                "name": "Highway Rest Stop",
                "latitude": 37.3861,
                "longitude": -122.0839,
                "address": "Highway 101, Mountain View, CA 94041"
            },
            {
                "name": "University Campus Station", 
                "latitude": 37.4275,
                "longitude": -122.1697,
                "address": "450 Serra Mall, Stanford, CA 94305"
            }
        ]
        
        for station_data in stations_data:
            station = await ChargingStation.create(**station_data)
            self.stations.append(station)
            print(f"  ✅ Created station: {station.name}")
            
            # Create 2-4 chargers per station
            charger_count = random.randint(2, 4)
            for i in range(charger_count):
                charger_data = {
                    "charge_point_string_id": f"{station.name.replace(' ', '_').upper()}_{i+1:02d}",
                    "station": station,
                    "name": f"Charger {i+1}",
                    "model": random.choice(["FastCharge Pro", "UltraCharge Max", "SpeedCharge Elite"]),
                    "vendor": random.choice(["ChargePoint", "EVgo", "Electrify America"]),
                    "serial_number": f"SN{random.randint(100000, 999999)}",
                    "firmware_version": f"v{random.randint(1,3)}.{random.randint(0,9)}.{random.randint(0,9)}",
                    "iccid": f"ICCID{random.randint(10000000000000000000, 99999999999999999999)}",
                    "imsi": f"IMSI{random.randint(100000000000000, 999999999999999)}",
                    "meter_type": "Smart Energy Meter",
                    "meter_serial_number": f"MET{random.randint(100000, 999999)}",
                    "latest_status": random.choice([
                        ChargerStatusEnum.AVAILABLE,
                        ChargerStatusEnum.PREPARING,
                        ChargerStatusEnum.CHARGING,
                        ChargerStatusEnum.UNAVAILABLE,
                        ChargerStatusEnum.FAULTED
                    ]),
                    "last_heart_beat_time": datetime.now() - timedelta(minutes=random.randint(1, 30))
                }
                
                charger = await Charger.create(**charger_data)
                self.chargers.append(charger)
                
                # Create connectors for each charger (1-2 connectors)
                connector_count = random.randint(1, 2)
                for j in range(connector_count):
                    await Connector.create(
                        charger=charger,
                        connector_id=j + 1,
                        connector_type=random.choice(["CCS", "CHAdeMO", "Type 2"]),
                        max_power_kw=random.choice([50.0, 75.0, 100.0, 150.0, 250.0])
                    )
                
                print(f"    ✅ Created charger: {charger.charge_point_string_id} with {connector_count} connector(s)")

    async def create_tariffs(self):
        """Create tariff structures"""
        print("💵 Creating tariffs...")
        
        # Global default tariff
        await Tariff.create(
            rate_per_kwh=Decimal("0.35"),
            is_global=True
        )
        print("  ✅ Created global tariff: ₹0.35/kWh")
        
        # Specific tariffs for some chargers
        premium_chargers = random.sample(self.chargers, min(3, len(self.chargers)))
        for charger in premium_chargers:
            await Tariff.create(
                charger=charger,
                rate_per_kwh=Decimal(random.uniform(0.25, 0.50)).quantize(Decimal('0.01')),
                is_global=False
            )
            print(f"  ✅ Created specific tariff for {charger.charge_point_string_id}")

    async def create_charging_transactions(self):
        """Create realistic charging transactions with history"""
        print("⚡ Creating charging transactions...")
        
        # Create transactions for the past 90 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        transaction_count = random.randint(20, 40)
        
        # Get fresh users for transactions  
        fresh_users = await User.all()
        regular_users = [u for u in fresh_users if u.role == UserRoleEnum.USER]
        
        for _ in range(transaction_count):
            user = random.choice(regular_users)
            charger = random.choice(self.chargers)
            # Every transaction must have a vehicle (required by database schema)
            user_vehicles = [v for v in self.vehicles if v.user == user]
            if not user_vehicles:
                print(f"  ⚠️  No vehicle found for user {user.email}, skipping transaction")
                continue
            vehicle = random.choice(user_vehicles)
            
            # Random transaction timing
            transaction_start = start_date + timedelta(
                days=random.randint(0, 89),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )
            
            # Transaction parameters
            start_meter = random.uniform(1000, 50000)
            energy_consumed = random.uniform(10, 80)  # kWh
            end_meter = start_meter + energy_consumed
            
            # Transaction status and timing
            status = random.choices(
                list(TransactionStatusEnum),
                weights=[1, 1, 2, 1, 8, 6, 1, 1, 1],  # Bias towards COMPLETED and STOPPED, added weight for BILLING_FAILED
                k=1
            )[0]
            
            end_time = None
            if status in [TransactionStatusEnum.COMPLETED, TransactionStatusEnum.STOPPED, TransactionStatusEnum.CANCELLED]:
                end_time = transaction_start + timedelta(minutes=random.randint(30, 240))
            
            transaction = await Transaction.create(
                user=user,
                charger=charger,
                vehicle=vehicle,
                start_meter_kwh=start_meter,
                end_meter_kwh=end_meter if end_time else None,
                energy_consumed_kwh=energy_consumed if end_time else None,
                end_time=end_time,
                stop_reason=random.choice([
                    "User requested", "Completed normally", "Emergency stop", 
                    "Power failure", "Card removed"
                ]) if end_time else None,
                transaction_status=status
            )
            
            # Update start_time manually after creation if needed
            if transaction_start != transaction.start_time:
                transaction.start_time = transaction_start
                await transaction.save()
            
            self.transactions.append(transaction)
            
            # Create meter values for completed transactions
            if status in [TransactionStatusEnum.COMPLETED, TransactionStatusEnum.STOPPED] and end_time:
                meter_readings = random.randint(3, 10)
                time_delta = (end_time - transaction_start) / meter_readings
                
                for i in range(meter_readings):
                    reading_time = transaction_start + (time_delta * i)
                    reading_kwh = start_meter + (energy_consumed * (i / meter_readings))
                    
                    await MeterValue.create(
                        transaction=transaction,
                        reading_kwh=reading_kwh,
                        current=random.uniform(10, 50),  # Amperes
                        voltage=random.uniform(400, 480),  # Volts
                        power_kw=random.uniform(10, 50),  # kW
                        created_at=reading_time
                    )
            
            # Create wallet deduction for completed transactions
            if status in [TransactionStatusEnum.COMPLETED, TransactionStatusEnum.STOPPED] and end_time:
                wallet = await Wallet.get(user=user)
                cost = Decimal(energy_consumed * 0.35).quantize(Decimal('0.01'))  # Using default rate
                
                await WalletTransaction.create(
                    wallet=wallet,
                    amount=-cost,  # Negative for deduction
                    type=TransactionTypeEnum.CHARGE_DEDUCT,
                    description=f"Charging at {charger.charge_point_string_id}",
                    charging_transaction=transaction,
                    created_at=end_time
                )
                
                # Update wallet balance
                wallet.balance -= cost
                await wallet.save()
            
        print(f"  ✅ Created {transaction_count} charging transactions")

    async def create_ocpp_logs(self):
        """Create OCPP communication logs"""
        print("📋 Creating OCPP logs...")
        
        message_types = [
            "BootNotification", "Heartbeat", "StatusNotification", 
            "StartTransaction", "StopTransaction", "MeterValues",
            "Authorize", "RemoteStartTransaction", "RemoteStopTransaction"
        ]
        
        log_count = random.randint(50, 100)
        
        for _ in range(log_count):
            charger = random.choice(self.chargers)
            message_type = random.choice(message_types)
            direction = random.choice(list(MessageDirectionEnum))
            
            # Sample payloads based on message type
            payload = self._generate_ocpp_payload(message_type, charger, direction)
            
            await OCPPLog.create(
                charge_point_id=charger.charge_point_string_id,
                message_type=message_type,
                direction=direction,
                payload=payload,
                status=random.choice(["Accepted", "Rejected", "Pending"]),
                correlation_id=f"corr_{random.randint(100000, 999999)}",
                timestamp=datetime.now() - timedelta(
                    days=random.randint(0, 30),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59)
                )
            )
        
        print(f"  ✅ Created {log_count} OCPP log entries")

    def _generate_ocpp_payload(self, message_type: str, charger, direction: MessageDirectionEnum) -> dict:
        """Generate sample OCPP payload based on message type"""
        if message_type == "BootNotification":
            return {
                "chargePointVendor": charger.vendor,
                "chargePointModel": charger.model,
                "chargePointSerialNumber": charger.serial_number,
                "firmwareVersion": charger.firmware_version,
                "iccid": charger.iccid,
                "imsi": charger.imsi
            }
        elif message_type == "Heartbeat":
            return {}
        elif message_type == "StatusNotification":
            return {
                "connectorId": random.randint(0, 2),
                "status": charger.latest_status.value,
                "errorCode": "NoError",
                "timestamp": datetime.now().isoformat()
            }
        elif message_type == "StartTransaction":
            return {
                "connectorId": random.randint(1, 2),
                "idTag": f"USER{random.randint(1, 999):03d}",
                "meterStart": random.randint(1000, 50000),
                "timestamp": datetime.now().isoformat()
            }
        elif message_type == "MeterValues":
            return {
                "connectorId": random.randint(1, 2),
                "transactionId": random.randint(1, 1000),
                "meterValue": [{
                    "timestamp": datetime.now().isoformat(),
                    "sampledValue": [{
                        "value": str(random.randint(1000, 50000)),
                        "measurand": "Energy.Active.Import.Register",
                        "unit": "Wh"
                    }]
                }]
            }
        else:
            return {"messageType": message_type, "timestamp": datetime.now().isoformat()}

    async def seed_all(self):
        """Run all seeding operations"""
        print("🌱 Starting database seeding...")
        
        try:
            await self.init_db()
            
            await self.create_users()
            await self.create_wallets_and_transactions()  
            await self.create_payment_gateways()
            await self.create_vehicle_profiles()
            await self.create_charging_infrastructure()
            await self.create_tariffs()
            await self.create_charging_transactions()
            await self.create_ocpp_logs()
            
            print("\n🎉 Database seeding completed successfully!")
            print(f"📊 Summary:")
            print(f"   - Users: {len(self.users)}")
            print(f"   - Charging Stations: {len(self.stations)}")
            print(f"   - Chargers: {len(self.chargers)}")
            print(f"   - Vehicles: {len(self.vehicles)}")
            print(f"   - Transactions: {len(self.transactions)}")
            
        except Exception as e:
            print(f"❌ Error during seeding: {e}")
            raise
        finally:
            await self.close_db()

async def main():
    seeder = DatabaseSeeder()
    await seeder.seed_all()

if __name__ == "__main__":
    asyncio.run(main())