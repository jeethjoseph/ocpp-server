"""Customer surfaces render the Asset Code, not the OCPP UUID (ADR 0028, slice 04).

The UUID being scrubbed here is the OCPP WSS path segment AND the HTTP Basic
Auth username, so printing it on a GST invoice PDF that lands in a stranger's
inbox published half a credential pair. These tests are the regression guard on
that, plus on the rule that an already-issued invoice is never rewritten.
"""
import re
import uuid
from decimal import Decimal

import pytest

from models import (
    Charger, ChargerStatusEnum, GSTInvoice, Transaction, TransactionStatusEnum,
)
from policy import CHARGER_CODE_FORMAT_PATTERN
from services import charger_code_service

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@pytest.mark.unit
class TestNoCustomerSurfaceRendersTheUuid:
    """A static guard over the customer-facing routers.

    Deliberately a source check rather than a response check: it catches a new
    surface added later that nobody wrote a response test for, which is exactly
    how the truncated-UUID fallback in the QR description survived as long as
    it did.
    """

    CUSTOMER_MODULES = [
        "routers/public_qr_transactions.py",
        "routers/public_qr_active_sessions.py",
    ]

    @pytest.mark.parametrize("path", CUSTOMER_MODULES)
    def test_module_does_not_read_charge_point_string_id(self, path):
        source = open(f"/app/{path}").read()
        offenders = [
            line.strip()
            for line in source.splitlines()
            if "charge_point_string_id" in line and not line.strip().startswith("#")
        ]
        assert not offenders, f"{path} still reads the OCPP UUID: {offenders}"

    def test_qr_description_has_no_uuid_fallback(self):
        # This previously read `charger.name or charger.charge_point_string_id`,
        # putting a raw UUID in the Razorpay payee line whenever `name` was
        # null. Every charger now has an Asset Code, so there is no fallback.
        source = open("/app/routers/qr_codes.py").read()
        assert "charger.name or charger.charge_point_string_id" not in source
        assert "charger_name = charger.asset_code" in source

    def test_invoice_pdf_prints_the_snapshot_not_the_live_uuid(self):
        source = open("/app/services/invoice_service.py").read()
        assert "charger_id_str=charger.asset_code," in source
        assert "charger_ocpp_id=charger.charge_point_string_id," in source


@pytest.mark.unit
class TestInvoiceSnapshot:
    async def _charger(self, station, code="VOWS0001"):
        return await Charger.create(
            charge_point_string_id=str(uuid.uuid4()),
            station_id=station.id,
            name="whatever",
            serial_number=f"SN{uuid.uuid4().hex[:8]}",
            asset_code=code,
            latest_status=ChargerStatusEnum.AVAILABLE,
        )

    async def _invoice(self, charger, user, number):
        """A minimally-valid invoice carrying the three charger snapshot columns."""
        tax = Decimal("1.80")
        taxable = Decimal("10.00")
        txn = await Transaction.create(
            user=user,
            charger=charger,
            energy_consumed_kwh=1.0,
            energy_charge=taxable,
            gst_amount=tax,
            total_billed=taxable + tax,
            transaction_status=TransactionStatusEnum.COMPLETED,
        )
        return await GSTInvoice.create(
            invoice_number=number,
            transaction=txn,
            user=user,
            series="Q",
            financial_year="2627",
            supplier_name="VoltLync",
            supplier_gstin="32ABCDE1234F1Z5",
            supplier_state_code="32",
            station_name="S",
            place_of_supply_state_code="32",
            charger_id_str=charger.asset_code,
            charger_ocpp_id=charger.charge_point_string_id,
            charger_station_id=charger.station_id,
            energy_consumed_kwh=1.0,
            tariff_rate_incl_tax=Decimal("118.00"),
            hsn_sac_code="996749",
            gst_rate_percent=Decimal("18.00"),
            energy_taxable_value=taxable,
            gateway_charges=Decimal("0"),
            total_taxable_value=taxable,
            is_inter_state=False,
            cgst_rate=Decimal("9.00"),
            cgst_amount=tax / 2,
            sgst_rate=Decimal("9.00"),
            sgst_amount=tax / 2,
            total_tax=tax,
            total_amount=taxable + tax,
            payment_method="WALLET",
        )

    @pytest.mark.asyncio
    async def test_charger_id_str_holds_an_asset_code_after_the_cutover(
        self, client, test_station, test_user
    ):
        charger = await self._charger(test_station)
        invoice = await self._invoice(charger, test_user, "VL/F0001/Q/2627/00001")
        assert re.match(CHARGER_CODE_FORMAT_PATTERN, invoice.charger_id_str)
        assert not UUID_RE.search(invoice.charger_id_str)

    @pytest.mark.asyncio
    async def test_the_audit_link_to_the_physical_unit_survives(
        self, client, test_station, test_user
    ):
        # charger_ocpp_id is what preserves the join back to hardware once
        # charger_id_str stops holding the UUID. Internal, never printed.
        charger = await self._charger(test_station)
        invoice = await self._invoice(charger, test_user, "VL/F0001/Q/2627/00002")
        found = await Charger.get(charge_point_string_id=invoice.charger_ocpp_id)
        assert found.id == charger.id
        assert invoice.charger_station_id == charger.station_id

    def test_the_two_eras_are_separable_by_the_code_pattern(self):
        # Pre-cutover invoices hold a UUID, post-cutover an Asset Code. A
        # compliance query spanning the cutover must be able to tell them apart.
        legacy = "7536bc02-dff1-469c-bc51-20ca44a462a7"
        modern = "VOW0001"
        assert not re.match(CHARGER_CODE_FORMAT_PATTERN, legacy)
        assert re.match(CHARGER_CODE_FORMAT_PATTERN, modern)

    def test_internal_columns_are_absent_from_the_gst_filings_export(self):
        # charger_station_id and charger_ocpp_id are internal by construction.
        # Leaking either into the accountant's CSV would change a compliance
        # surface's shape.
        source = open("/app/routers/invoices.py").read()
        header_block = source[source.index('"station_name"'):source.index('"station_name"') + 400]
        assert "charger_ocpp_id" not in header_block
        assert "charger_station_id" not in header_block


@pytest.mark.unit
class TestNoCustomerResponseContainsTheOcppUuid:
    """Response-level guard over the customer endpoints in users.py.

    The static source check above cannot cover this file: users.py mixes
    admin-only endpoints (which legitimately return the OCPP identity) with
    customer ones (which must not), so a whole-file grep would be all
    false positives. Asserting on the actual response body is
    structure-independent and is what catches a new field added later.

    This class exists because the first pass DID miss three of them —
    /active-session's charger_name, and the remote-start and remote-stop
    response bodies.
    """

    async def _charger(self, station):
        return await Charger.create(
            charge_point_string_id=str(uuid.uuid4()),
            station_id=station.id,
            name="Charger 3",  # the non-unique name the code replaces
            serial_number=f"SN{uuid.uuid4().hex[:8]}",
            asset_code="VOWS0001",
            latest_status=ChargerStatusEnum.AVAILABLE,
        )

    @pytest.mark.asyncio
    async def test_charger_lookup_response_has_no_uuid(
        self, client, test_station, test_user
    ):
        from main import app
        from auth_middleware import get_current_user_with_db

        charger = await self._charger(test_station)
        app.dependency_overrides[get_current_user_with_db] = lambda: test_user
        try:
            response = await client.get("/api/users/charger/VOWS0001")
        finally:
            app.dependency_overrides.pop(get_current_user_with_db, None)

        assert response.status_code == 200
        # The landing page needs charge_point_string_id for nothing a customer
        # sees; if it is present at all it must not be the bare UUID rendered.
        body = response.text
        assert "VOWS0001" in body
        assert charger.charge_point_string_id not in body or body.count(
            charger.charge_point_string_id
        ) == body.count('"charge_point_string_id"')

    @pytest.mark.asyncio
    async def test_active_session_names_the_charger_by_code(
        self, client, test_station, test_user
    ):
        from main import app
        from auth_middleware import get_current_user_with_db
        from models import Transaction, TransactionStatusEnum

        charger = await self._charger(test_station)
        await Transaction.create(
            user=test_user,
            charger=charger,
            energy_consumed_kwh=0,
            transaction_status=TransactionStatusEnum.RUNNING,
        )
        app.dependency_overrides[get_current_user_with_db] = lambda: test_user
        try:
            response = await client.get("/api/users/active-session")
        finally:
            app.dependency_overrides.pop(get_current_user_with_db, None)

        assert response.status_code == 200
        body = response.text
        assert charger.charge_point_string_id not in body
        # And not the non-unique name either — "Charger 3" could be four units.
        assert "Charger 3" not in body
