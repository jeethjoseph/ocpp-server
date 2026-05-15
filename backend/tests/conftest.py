# tests/conftest.py
import pytest
import pytest_asyncio
import asyncio
import redis.asyncio as redis
import os
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise
from unittest.mock import patch, AsyncMock
from typing import AsyncGenerator

import sys
import os
# Add parent directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, connected_charge_points
from models import (
    ChargingStation, Charger, Connector, Transaction, OCPPLog, User, VehicleProfile,
    Tariff, Wallet, ChargerStatusEnum, UserRoleEnum,
)
from auth_middleware import get_current_user_with_db

# Test database configuration.
# Default targets the postgres container's hostname (`postgres`) since the
# expected runner is `docker exec ocpp-backend pytest ...` per CLAUDE.md.
# Override TEST_DATABASE_URL when running outside the container.
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgres://test_user:test_pass@postgres:5432/test_ocpp_db",
)

# Track whether the test schema has been (re)generated this pytest session.
# First test in a session drops the whole `public` schema and regenerates it,
# so column additions to models after a migration land without manual
# intervention. Subsequent tests in the same session reuse the schema and
# just clear rows in the per-function fixture below — keeps the sweep fast.
_SCHEMA_GENERATED_THIS_SESSION = False


@pytest.fixture(autouse=True)
def _flush_public_endpoint_rate_limit_keys():
    """Public endpoints (`/api/public/qr-transactions/*`) use a 20-req/min
    per-IP rate limiter backed by Redis (`public_qr_transactions:*`).
    Function-scoped autouse flush so every test starts with a clean
    window — otherwise the cumulative request count across the suite
    trips the limiter on the last few tests of `test_invoice_pdf_endpoint`
    (each test makes 1-2 requests but ~20 tests collectively cross the
    threshold within 60s). Cost is one Redis DEL per test (~ms).

    Uses the synchronous redis client (not asyncio) — calling
    `asyncio.run()` from inside a sync pytest fixture that's used
    alongside pytest-asyncio's async tests clashes with pytest-asyncio's
    event-loop management."""
    import redis as _sync_redis
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        client = _sync_redis.from_url(redis_url, decode_responses=True)
        keys = client.keys("ratelimit:public_qr_transactions:*")
        if keys:
            client.delete(*keys)
        client.close()
    except Exception:
        pass  # Redis unavailable in some test envs — non-fatal
    yield

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient, None]:
    """HTTP test client with mocked Redis"""
    # Mock Redis manager for all tests
    with patch('routers.chargers.redis_manager') as mock_redis:
        # Use dynamic approach to check what's in connected_charge_points
        async def mock_get_all_connected():
            return list(connected_charge_points.keys())
        
        async def mock_is_connected(charger_id):
            return charger_id in connected_charge_points
        
        mock_redis.get_all_connected_chargers = mock_get_all_connected
        mock_redis.is_charger_connected = mock_is_connected
        mock_redis.connect = AsyncMock(return_value=None)
        mock_redis.disconnect = AsyncMock(return_value=None)
        mock_redis.add_connected_charger = AsyncMock(return_value=True)
        mock_redis.remove_connected_charger = AsyncMock(return_value=True)
        mock_redis.get_charger_connected_at = AsyncMock(return_value=None)
        
        # Initialize test database.
        # Tortoise.init() internally calls close_all(discard=True) on any
        # existing connections. When a prior test exits inside an @atomic()
        # block (or its sync TestClient counterpart leaks into our loop),
        # the current connection is a TransactionWrapper that doesn't have
        # `_template`, and base_postgres.client.close() crashes with
        # AttributeError: 'TransactionWrapper' object has no attribute
        # '_template'. Bypass Tortoise's broken close path by purging the
        # connection storage directly before Tortoise.init runs its own
        # close_all (which would now find an empty registry).
        from tortoise import connections as _conn
        try:
            _conn._clear_storage()
        except Exception:
            pass
        Tortoise._inited = False
        config = {
            "connections": {"default": TEST_DB_URL},
            "apps": {
                "models": {
                    "models": ["models"],
                    "default_connection": "default",
                }
            },
        }
        await Tortoise.init(config=config)
        global _SCHEMA_GENERATED_THIS_SESSION
        if not _SCHEMA_GENERATED_THIS_SESSION:
            # First test in this session — wipe the public schema so any new
            # columns added to models are picked up, then regenerate.
            # `generate_schemas(safe=True)` (default) won't add columns to
            # existing tables, causing UndefinedColumnError surprises after
            # migrations land. This avoids the manual "drop test_ocpp_db" step.
            from tortoise import connections as _conn2
            conn = _conn2.get("default")
            await conn.execute_script(
                "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
            )
            await Tortoise.generate_schemas()
            _SCHEMA_GENERATED_THIS_SESSION = True
        else:
            await Tortoise.generate_schemas()

        # Clean up database before each test (order matters for FK constraints)
        from models import (
            WalletTransaction, MeterValue,
            CommissionLedgerEntry, FranchiseeStakeholder, Franchisee,
        )
        await MeterValue.all().delete()
        await CommissionLedgerEntry.all().delete()
        await FranchiseeStakeholder.all().delete()
        await WalletTransaction.all().delete()
        await Wallet.all().delete()
        await Transaction.all().delete()
        await Tariff.all().delete()
        await Connector.all().delete()
        await Charger.all().delete()
        await ChargingStation.all().delete()
        await Franchisee.all().delete()
        await OCPPLog.all().delete()
        await VehicleProfile.all().delete()
        await User.all().delete()
        connected_charge_points.clear()
        
        async with AsyncClient(
            transport=ASGITransport(app=app), 
            base_url="http://test"
        ) as ac:
            yield ac
        
        await Tortoise.close_connections()

# Test data fixtures
@pytest.fixture
async def test_station():
    """Create a test station"""
    return await ChargingStation.create(
        name="Test Station",
        latitude=12.9716,
        longitude=77.5946,
        address="Test Address"
    )

@pytest.fixture
async def test_charger(test_station):
    """Create a test charger"""
    import uuid
    charger = await Charger.create(
        charge_point_string_id=str(uuid.uuid4()),
        station_id=test_station.id,
        name="Test Charger",
        model="Model X",
        vendor="Vendor Y",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.AVAILABLE
    )
    # Create connectors
    await Connector.create(
        charger_id=charger.id,
        connector_id=1,
        connector_type="Type2",
        max_power_kw=22.0
    )
    return charger

@pytest.fixture
async def test_user():
    """Create a test user with a unique phone number and email"""
    import random
    suffix = random.randint(100000000, 999999999)
    return await User.create(
        email=f"test_{suffix}@voltlync.test",
        phone_number=f"9{suffix}",
    )

@pytest.fixture
async def test_vehicle(test_user):
    """Create a test vehicle profile for the user"""
    return await VehicleProfile.create(user=test_user)


@pytest.fixture
async def test_tariff(test_charger):
    """Create a charger-specific tariff with default 18% GST"""
    from decimal import Decimal
    return await Tariff.create(
        charger=test_charger,
        rate_per_kwh=Decimal("15.00"),
        gst_percent=Decimal("18.00"),
        is_global=False,
    )


@pytest.fixture
async def test_wallet(test_user):
    """Create a wallet for the test user, seeded to ₹500 via a COMPLETED
    TOP_UP row (balance is derived from the log; no stored column)."""
    from decimal import Decimal
    from models import WalletTransaction, TransactionTypeEnum
    wallet = await Wallet.create(user=test_user)
    await WalletTransaction.create(
        wallet=wallet,
        amount=Decimal("500.00"),
        type=TransactionTypeEnum.TOP_UP,
        description="Test seed top-up",
        payment_metadata={"status": "COMPLETED"},
    )
    return wallet


@pytest.fixture
async def test_franchisee():
    """Create a Franchisee row activated for transfers, past cooling period.

    Defaults aim at the happy-path: ACTIVE status, transfers_enabled=True,
    funds_on_hold=False, activated_at well outside the 24h cooling window.
    Override individual fields by passing a different fixture or by
    mutating the returned row in the test.
    """
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import random
    from models import Franchisee, FranchiseeStatusEnum
    suffix = random.randint(100000000, 999999999)
    return await Franchisee.create(
        business_name=f"Test Franchisee {suffix}",
        contact_name="Test Contact",
        contact_email=f"franchisee_{suffix}@voltlync.test",
        contact_phone=f"9{suffix}",
        commission_percent=Decimal("20.00"),
        tds_rate_percent=Decimal("10.00"),
        status=FranchiseeStatusEnum.ACTIVE,
        razorpay_account_id=f"acc_test_{suffix}",
        transfers_enabled=True,
        funds_on_hold=False,
        activated_at=datetime.now(timezone.utc) - timedelta(days=2),
    )


@pytest.fixture
async def test_commission_ledger_entry(test_franchisee, test_charger, test_user):
    """Create a CommissionLedgerEntry in PENDING state with consistent
    commission math (gross == sum of components).

    Requires `test_charger` + `test_user` so the linked Transaction row
    exists; mirrors the production process_settlement flow.
    """
    from decimal import Decimal
    from models import (
        CommissionLedgerEntry, SettlementStatusEnum, Transaction,
        TransactionStatusEnum,
    )
    txn = await Transaction.create(
        charger=test_charger,
        user=test_user,
        transaction_status=TransactionStatusEnum.COMPLETED,
    )
    # Math (TDS on post-commission earning):
    #   gross 1000 = refund 0 + pg 0 + gst 152.54 + commission 169.49
    #              + tds 67.80 + payout 610.17.
    # net_amount = 1000, net_excl_gst = 847.46, commission@20% = 169.49,
    # earning = 847.46 - 169.49 = 677.97, tds@10% = 67.80, payout = 610.17.
    return await CommissionLedgerEntry.create(
        transaction=txn,
        franchisee=test_franchisee,
        gross_amount=Decimal("1000.00"),
        payment_method="QR_UPI",
        razorpay_payment_id=f"pay_test_{txn.id}",
        refund_amount=Decimal("0.00"),
        pg_fee_amount=Decimal("0.00"),
        net_amount=Decimal("1000.00"),
        gst_collected=Decimal("152.54"),
        net_excl_gst=Decimal("847.46"),
        commission_percent=Decimal("20.00"),
        platform_commission=Decimal("169.49"),
        tds_rate_percent=Decimal("10.00"),
        tds_amount=Decimal("67.80"),
        transfer_fee=Decimal("0.00"),
        franchisee_payout=Decimal("610.17"),
        energy_consumed_kwh=10.0,
        tariff_rate_per_kwh=Decimal("15.00"),
        settlement_status=SettlementStatusEnum.PENDING,
        idempotency_key=f"txn_{txn.id}",
    )


@pytest.fixture
async def test_admin_user():
    """Create a test admin user. Use with `client_admin` to bypass admin auth.

    Why we override `get_current_user_with_db` and not `require_admin`:
    `require_admin` is a *factory* (auth_middleware.py:145-148) that returns a
    fresh closure on every call, so it can't be used as a stable key in
    `app.dependency_overrides`. Overriding the underlying DB-bound dependency
    gives every role check (admin / user / user_or_admin) a fake admin user.
    """
    import random
    suffix = random.randint(100000000, 999999999)
    return await User.create(
        email=f"admin_{suffix}@voltlync.test",
        phone_number=f"9{suffix}",
        role=UserRoleEnum.ADMIN,
        # rfid_card_id is required by remote-start endpoint — set a default
        # so admin tests can drive the endpoint without per-test setup
        rfid_card_id=f"ADMIN_RFID_{suffix}",
    )


@pytest.fixture
async def client_admin(client, test_admin_user):
    """HTTP test client with admin auth dependency overridden.

    Use this in place of `client` for tests that hit admin-only endpoints
    (anything that uses `require_admin()` or `require_user_or_admin()`).
    """
    app.dependency_overrides[get_current_user_with_db] = lambda: test_admin_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


@pytest.fixture
async def test_franchisee_user(test_franchisee):
    """Create a User with FRANCHISEE role linked to the test_franchisee row.

    Mirrors `test_admin_user`. Pairs with `client_franchisee` to exercise
    the portal endpoints under realistic auth: the User → Franchisee link is
    what ``require_franchisee()`` resolves.
    """
    import random
    suffix = random.randint(100000000, 999999999)
    user = await User.create(
        email=f"franchisee_user_{suffix}@voltlync.test",
        phone_number=f"9{suffix}",
        role=UserRoleEnum.FRANCHISEE,
    )
    test_franchisee.user = user
    await test_franchisee.save()
    return user


@pytest.fixture
async def client_franchisee(client, test_franchisee_user):
    """HTTP test client with FRANCHISEE auth dependency overridden.

    Use for `require_franchisee()` / `require_admin_or_franchisee()` paths.
    """
    app.dependency_overrides[get_current_user_with_db] = lambda: test_franchisee_user
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user_with_db, None)


# ============================================================================
# Sync test fixtures — for tests that need FastAPI's sync TestClient
# (in particular, OCPP WebSocket integration tests via websocket_connect()).
#
# httpx.AsyncClient does not support WebSocket. The async `client` fixture
# above is fine for HTTP tests. For WebSocket tests, use `sync_client_admin`.
# ============================================================================

TORTOISE_TEST_CONFIG = {
    "connections": {"default": TEST_DB_URL},
    "apps": {
        "models": {
            "models": ["models"],
            "default_connection": "default",
        }
    },
}


async def _init_test_db_async():
    """Initialize Tortoise with the test DB and generate schemas."""
    await Tortoise.init(config=TORTOISE_TEST_CONFIG)
    await Tortoise.generate_schemas()


async def _cleanup_test_db_async():
    """Delete all rows in FK-safe order."""
    from models import (
        WalletTransaction, MeterValue,
        CommissionLedgerEntry, FranchiseeStakeholder, Franchisee,
    )
    await MeterValue.all().delete()
    await CommissionLedgerEntry.all().delete()
    await FranchiseeStakeholder.all().delete()
    await WalletTransaction.all().delete()
    await Wallet.all().delete()
    await Transaction.all().delete()
    await Tariff.all().delete()
    await Connector.all().delete()
    await Charger.all().delete()
    await ChargingStation.all().delete()
    await Franchisee.all().delete()
    await OCPPLog.all().delete()
    await VehicleProfile.all().delete()
    await User.all().delete()
    connected_charge_points.clear()


async def _create_test_admin_user():
    """Create a fake admin user (sync-test counterpart of test_admin_user)."""
    import random
    suffix = random.randint(100000000, 999999999)
    return await User.create(
        email=f"sync_admin_{suffix}@voltlync.test",
        phone_number=f"9{suffix}",
        role=UserRoleEnum.ADMIN,
        rfid_card_id=f"SYNC_ADMIN_RFID_{suffix}",
    )


async def _create_test_charger_async(charge_point_string_id: str, station=None):
    """Create a test charger row (with default station if none provided)."""
    import uuid
    if station is None:
        station = await ChargingStation.create(
            name=f"Sync Station {uuid.uuid4().hex[:6]}",
            latitude=12.9716,
            longitude=77.5946,
            address="Sync Test Address",
        )
    charger = await Charger.create(
        charge_point_string_id=charge_point_string_id,
        station_id=station.id,
        name="Sync Test Charger",
        model="Model X",
        vendor="Vendor Y",
        serial_number=f"SN{uuid.uuid4().hex[:8]}",
        latest_status=ChargerStatusEnum.AVAILABLE,
    )
    await Connector.create(
        charger_id=charger.id,
        connector_id=1,
        connector_type="Type2",
        max_power_kw=22.0,
    )
    return charger


async def seed_charger(charge_point_string_id: str, station=None):
    """Async helper to create a Charger row before opening a WebSocket.

    `validate_and_connect_charger` requires the charger to exist in the DB
    before accepting an OCPP WebSocket connection — call this from any
    integration test that uses `sync_client_admin.websocket_connect()`.
    """
    return await _create_test_charger_async(charge_point_string_id, station)


def _build_admin_override():
    """Build a stub User object to inject as the authenticated admin.

    Returns a duck-typed User-like object — TestClient-based integration
    tests can't pre-seed the DB from the test thread (cross-loop issue
    with asyncpg), so the override returns a transient object instead of
    a persisted row. This is fine for endpoints that only check `.role`
    and `.rfid_card_id` on the auth subject.
    """
    class _StubAdmin:
        id = -1
        email = "stub_admin@voltlync.test"
        phone_number = "9000000000"
        role = UserRoleEnum.ADMIN
        rfid_card_id = "STUB_ADMIN_RFID"
        clerk_user_id = "stub_admin_clerk"
        is_active = True
    return _StubAdmin()


@pytest.fixture(scope="function")
def sync_client_admin():
    """FastAPI sync TestClient + Redis mocks + admin auth override.

    SYNC fixture (not async) — does NOT initialize Tortoise from the test
    side. Tortoise is initialized inside TestClient's worker thread+loop
    via the FastAPI app's startup event (`init_db()` in main.py). This
    avoids the cross-loop asyncpg violation that occurs when the test
    thread and TestClient's worker thread both try to use the same
    Tortoise connection pool.

    Tests that need DB rows (chargers, stations) should seed them via
    TestClient HTTP calls (POST /api/admin/stations, /api/admin/chargers)
    so the writes happen on TestClient's loop where Tortoise actually lives.

    Uses unique UUID IDs per test to avoid cross-test pollution without
    needing destructive DB cleanup.
    """
    from fastapi.testclient import TestClient

    # 1. Mock Redis across all modules that import redis_manager.
    #    `connected_charge_points` is the in-process dict managed by
    #    connection_manager — we read from it so the mock reflects what's
    #    actually connected via TestClient WebSockets in this test.
    import datetime as _dt

    async def _mock_get_all_connected():
        return list(connected_charge_points.keys())

    async def _mock_is_connected(charger_id):
        return charger_id in connected_charge_points

    async def _mock_get_connected_at(charger_id):
        # /api/charge-points filters out chargers where this returns None,
        # so we always return a timestamp for connected chargers.
        if charger_id in connected_charge_points:
            data = connected_charge_points[charger_id]
            return data.get("connected_at") or _dt.datetime.now(_dt.timezone.utc)
        return None

    redis_patches = [
        patch("main.redis_manager"),
        patch("routers.chargers.redis_manager"),
        patch("routers.ocpp_ws.redis_manager"),
        patch("core.connection_manager.redis_manager"),
    ]
    redis_mocks = [p.start() for p in redis_patches]
    for m in redis_mocks:
        m.get_all_connected_chargers = _mock_get_all_connected
        m.is_charger_connected = _mock_is_connected
        m.get_charger_connected_at = _mock_get_connected_at
        m.connect = AsyncMock(return_value=None)
        m.disconnect = AsyncMock(return_value=None)
        m.add_connected_charger = AsyncMock(return_value=True)
        m.remove_connected_charger = AsyncMock(return_value=True)

    # 2. Override admin auth — return a stub object (not a persisted row)
    app.dependency_overrides[get_current_user_with_db] = _build_admin_override

    try:
        # 3. Yield TestClient — sync interface, runs ASGI in its own thread.
        #    Entering the context fires the FastAPI startup event which
        #    initializes Tortoise inside TestClient's worker loop.
        with TestClient(app) as client:
            yield client
    finally:
        connected_charge_points.clear()
        for p in redis_patches:
            p.stop()
        app.dependency_overrides.pop(get_current_user_with_db, None)