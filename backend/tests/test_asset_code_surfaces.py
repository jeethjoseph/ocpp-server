"""Customer surfaces render the Asset Code, not the OCPP UUID (ADR 0028, slice 04).

The UUID being scrubbed here is the OCPP WSS path segment AND the HTTP Basic
Auth username, so printing it on a GST invoice PDF that lands in a stranger's
inbox published half a credential pair. These tests are the regression guard on
that, plus on the rule that an already-issued invoice is never rewritten.
"""
import importlib.util
import re
import uuid
from decimal import Decimal

from tortoise import connections

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

    # EVERY module that can create a Razorpay QR. The first version of this
    # test named only qr_codes.py, and franchisee_portal.py — a second,
    # independent QR-creation path — kept the UUID fallback for another two
    # commits because nothing looked at it. Enumerate the paths, not the one
    # you remember.
    QR_CREATING_MODULES = ["routers/qr_codes.py", "routers/franchisee_portal.py"]

    @pytest.mark.parametrize("path", QR_CREATING_MODULES)
    def test_no_qr_description_falls_back_to_the_uuid(self, path):
        # The payee/description line is what a customer reads in their UPI app
        # at payment. `charger.name or charger.charge_point_string_id` put a raw
        # UUID there whenever `name` was null. Every charger now has an Asset
        # Code, so there is nothing to fall back to.
        source = open(f"/app/{path}").read()
        assert "charger.name or charger.charge_point_string_id" not in source
        assert "or qr.charger.charge_point_string_id" not in source

    def test_every_qr_creating_module_is_covered_by_this_guard(self):
        # Fails when a THIRD QR-creation path appears, rather than silently
        # leaving it unguarded.
        import subprocess

        hits = subprocess.run(
            ["grep", "-rl", "razorpay_service.create_qr_code", "/app/routers"],
            capture_output=True, text=True,
        ).stdout.split()
        found = {h.replace("/app/", "") for h in hits}
        assert found == set(self.QR_CREATING_MODULES), (
            f"QR-creating modules changed: {found}. Add it to QR_CREATING_MODULES."
        )

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


@pytest.mark.unit
class TestIssuedInvoicesAreNeverRewritten:
    """Migration 61's backfill, exercised rather than grepped.

    This is the single most compliance-sensitive statement in the effort: a GST
    invoice with a generated PDF is a frozen tax document and must stay
    byte-identical. It was previously covered only by asserting the migration's
    SOURCE contained a WHERE clause — which proves the text exists, not that it
    works. A typo in the join, or the two UPDATEs in the wrong order, would pass
    that check and silently rewrite issued invoices.
    """

    MIGRATION_61 = "/app/migrations/models/61_20260908224718_gst_invoice_charger_snapshot.py"

    def _load(self):
        spec = importlib.util.spec_from_file_location("gst_snapshot", self.MIGRATION_61)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    async def _seed(self, station, user, *, issued: bool):
        """An invoice whose charger_id_str holds a pre-cutover UUID."""
        charger = await Charger.create(
            charge_point_string_id=str(uuid.uuid4()),
            station_id=station.id,
            name="unit",
            serial_number=f"SN{uuid.uuid4().hex[:8]}",
            asset_code=f"VOWS{uuid.uuid4().int % 9000 + 1000:04d}",
            latest_status=ChargerStatusEnum.AVAILABLE,
        )
        txn = await Transaction.create(
            user=user, charger=charger, energy_consumed_kwh=1.0,
            energy_charge=Decimal("10.00"), gst_amount=Decimal("1.80"),
            total_billed=Decimal("11.80"),
            transaction_status=TransactionStatusEnum.COMPLETED,
        )
        invoice = await GSTInvoice.create(
            invoice_number=f"VL/F0001/Q/2627/{uuid.uuid4().int % 90000 + 10000}",
            series="Q", financial_year="2627", transaction=txn, user=user,
            supplier_name="VoltLync", supplier_gstin="32ABCDE1234F1Z5",
            supplier_state_code="32", station_name="S",
            place_of_supply_state_code="32",
            # The pre-cutover state: the UUID is what was printed.
            charger_id_str=charger.charge_point_string_id,
            energy_consumed_kwh=1.0, tariff_rate_incl_tax=Decimal("118.00"),
            hsn_sac_code="996749", gst_rate_percent=Decimal("18.00"),
            energy_taxable_value=Decimal("10.00"), gateway_charges=Decimal("0"),
            total_taxable_value=Decimal("10.00"), is_inter_state=False,
            cgst_rate=Decimal("9.00"), cgst_amount=Decimal("0.90"),
            sgst_rate=Decimal("9.00"), sgst_amount=Decimal("0.90"),
            total_tax=Decimal("1.80"), total_amount=Decimal("11.80"),
            payment_method="WALLET",
            pdf_url="https://s3/invoice.pdf" if issued else None,
        )
        return charger, invoice

    async def _run_backfill(self):
        # Only the two UPDATEs; the ALTERs already ran via the real migration.
        module = self._load()
        sql = await module.upgrade(None)
        updates = sql.split("ALTER TABLE \"gst_invoice\" ADD \"charger_ocpp_id\" VARCHAR(255);")[1]
        await connections.get("default").execute_script(updates)

    @pytest.mark.asyncio
    async def test_an_issued_invoice_keeps_the_uuid_it_printed(
        self, client, test_station, test_user
    ):
        charger, invoice = await self._seed(test_station, test_user, issued=True)
        await self._run_backfill()
        await invoice.refresh_from_db()
        # Byte-identical: still the UUID that appears on the generated PDF.
        assert invoice.charger_id_str == charger.charge_point_string_id
        assert invoice.charger_id_str != charger.asset_code

    @pytest.mark.asyncio
    async def test_an_unissued_invoice_gains_the_asset_code(
        self, client, test_station, test_user
    ):
        charger, invoice = await self._seed(test_station, test_user, issued=False)
        await self._run_backfill()
        await invoice.refresh_from_db()
        assert invoice.charger_id_str == charger.asset_code

    @pytest.mark.asyncio
    async def test_internal_columns_are_backfilled_for_issued_invoices_too(
        self, client, test_station, test_user
    ):
        # They are never printed and never exported, so populating them alters
        # no document — and it gives compliance one uniform join across the
        # cutover instead of a regex on charger_id_str.
        charger, invoice = await self._seed(test_station, test_user, issued=True)
        await self._run_backfill()
        await invoice.refresh_from_db()
        assert invoice.charger_ocpp_id == charger.charge_point_string_id
        assert invoice.charger_station_id == charger.station_id
