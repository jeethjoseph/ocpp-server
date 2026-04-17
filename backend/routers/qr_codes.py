"""Admin endpoints for managing Razorpay QR codes on chargers"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
import logging

from auth_middleware import require_admin
from models import (
    Charger, ChargerQRCode, QRPayment, QRPaymentStatusEnum,
    Franchisee, FranchiseeStatusEnum,
)
from services.razorpay_service import (
    razorpay_service, build_qr_payee_name, build_qr_description,
)
from tortoise.functions import Count, Sum

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/qr-codes", tags=["QR Codes"])


class CreateQRCodeRequest(BaseModel):
    charger_id: int


async def _resolve_qr_owner(charger: Charger) -> tuple[Optional[Franchisee], Optional[str]]:
    """Decide which Razorpay account owns a QR created for this charger.

    Returns (franchisee, account_id_for_header). When the charger's station
    is linked to an ACTIVE franchisee with a Razorpay linked account, the
    QR is scoped to that account via X-Razorpay-Account. Otherwise the QR
    falls back to being owned by the platform (account_id=None).

    This is what gets the franchisee's registered business name rendered
    on the QR image (RBI Route payer-payee transparency).
    """
    await charger.fetch_related("station__franchisee")
    station = charger.station
    if not station or not station.franchisee:
        return None, None
    franchisee = station.franchisee
    if (
        franchisee.status == FranchiseeStatusEnum.ACTIVE
        and franchisee.razorpay_account_id
    ):
        return franchisee, franchisee.razorpay_account_id
    # Franchisee exists but Razorpay onboarding isn't complete — fall back
    # to platform ownership. Admin can regenerate later.
    return franchisee, None


async def _create_qr_for_charger(charger: Charger) -> dict:
    """Create a QR code for a charger, auto-scoping to the franchisee's
    linked account when possible. Returns the Razorpay response merged
    with our internal ChargerQRCode fields."""
    franchisee, account_id = await _resolve_qr_owner(charger)
    business_name = franchisee.business_name if franchisee else None
    charger_name = charger.name or charger.charge_point_string_id

    result = razorpay_service.create_qr_code(
        payee_name=build_qr_payee_name(business_name, charger_name),
        description=build_qr_description(business_name, charger_name),
        account_id=account_id,
    )

    qr_code = await ChargerQRCode.create(
        charger=charger,
        razorpay_qr_code_id=result["id"],
        image_url=result.get("image_url", ""),
        short_url=result.get("short_url"),
        is_active=True,
        owner_razorpay_account_id=account_id,
    )
    return {
        "id": qr_code.id,
        "charger_id": charger.id,
        "charger_name": charger.name,
        "charge_point_string_id": charger.charge_point_string_id,
        "razorpay_qr_code_id": qr_code.razorpay_qr_code_id,
        "image_url": qr_code.image_url,
        "short_url": qr_code.short_url,
        "is_active": qr_code.is_active,
        "owner": "franchisee" if account_id else "platform",
        "owner_razorpay_account_id": account_id,
        "franchisee_name": business_name,
        "created_at": qr_code.created_at.isoformat(),
    }


@router.post("")
async def create_qr_code(request: CreateQRCodeRequest, admin_user=Depends(require_admin())):
    """Create a Razorpay QR code for a charger.

    When the charger's station belongs to an ACTIVE franchisee with a
    Razorpay linked account, the QR is scoped to that account so the
    rendered QR image displays the franchisee's business name (RBI
    Route payer-payee transparency). Otherwise falls back to a
    platform-owned QR.
    """
    charger = await Charger.filter(id=request.charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    existing = await ChargerQRCode.filter(charger=charger, is_active=True).first()
    if existing:
        raise HTTPException(status_code=400, detail="Active QR code already exists for this charger")

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    try:
        return await _create_qr_for_charger(charger)
    except Exception as e:
        logger.error(f"Failed to create QR code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{qr_id}/regenerate")
async def regenerate_qr_code(qr_id: int, admin_user=Depends(require_admin())):
    """Close the existing QR and create a new one under today's ownership.

    Used to upgrade a platform-owned QR to a franchisee-owned one after
    the franchisee completes Razorpay onboarding, or after any change
    that should refresh the rendered payee label on the QR image.
    """
    qr = await ChargerQRCode.filter(id=qr_id).prefetch_related("charger").first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    # Close the existing QR first (best-effort: Razorpay side may already
    # be closed; proceed to create the replacement regardless).
    if qr.is_active:
        try:
            razorpay_service.close_qr_code(
                qr.razorpay_qr_code_id,
                account_id=qr.owner_razorpay_account_id,
            )
        except Exception as e:
            logger.warning("Razorpay close failed during regenerate (continuing): %s", e)
        qr.is_active = False
        await qr.save()

    try:
        return await _create_qr_for_charger(qr.charger)
    except Exception as e:
        logger.error(f"Failed to regenerate QR code: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_qr_codes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    search: Optional[str] = None,
    admin_user=Depends(require_admin()),
):
    """List all QR codes with charger info and payment stats"""
    query = ChargerQRCode.all().prefetch_related("charger")

    if status == "active":
        query = query.filter(is_active=True)
    elif status == "inactive":
        query = query.filter(is_active=False)

    if search:
        query = query.filter(charger__name__icontains=search)

    total = await query.count()
    qr_codes = await query.order_by("-created_at").offset((page - 1) * limit).limit(limit)

    results = []
    for qr in qr_codes:
        # Get payment stats
        payment_count = await QRPayment.filter(charger_qr_code_id=qr.id).count()
        total_revenue_result = await QRPayment.filter(
            charger_qr_code_id=qr.id,
            status__in=[QRPaymentStatusEnum.COMPLETED, QRPaymentStatusEnum.REFUNDED, QRPaymentStatusEnum.CHARGING]
        ).annotate(total=Sum("amount_paid")).values("total")
        total_revenue = total_revenue_result[0]["total"] if total_revenue_result and total_revenue_result[0]["total"] else 0

        results.append({
            "id": qr.id,
            "charger_id": qr.charger.id,
            "charger_name": qr.charger.name,
            "charge_point_string_id": qr.charger.charge_point_string_id,
            "razorpay_qr_code_id": qr.razorpay_qr_code_id,
            "image_url": qr.image_url,
            "short_url": qr.short_url,
            "is_active": qr.is_active,
            "payment_count": payment_count,
            "total_revenue": float(total_revenue),
            "created_at": qr.created_at.isoformat(),
        })

    return {"data": results, "total": total, "page": page, "limit": limit}


@router.get("/charger/{charger_id}")
async def get_qr_code_by_charger(charger_id: int, admin_user=Depends(require_admin())):
    """Get QR code for a specific charger"""
    qr = await ChargerQRCode.filter(charger_id=charger_id).prefetch_related("charger").order_by("-is_active", "-created_at").first()
    if not qr:
        return None

    payment_count = await QRPayment.filter(charger_qr_code_id=qr.id).count()

    return {
        "id": qr.id,
        "charger_id": qr.charger.id,
        "charger_name": qr.charger.name,
        "charge_point_string_id": qr.charger.charge_point_string_id,
        "razorpay_qr_code_id": qr.razorpay_qr_code_id,
        "image_url": qr.image_url,
        "short_url": qr.short_url,
        "is_active": qr.is_active,
        "payment_count": payment_count,
        "created_at": qr.created_at.isoformat(),
    }


@router.get("/{qr_id}")
async def get_qr_code(qr_id: int, admin_user=Depends(require_admin())):
    """Get QR code details with payment summary stats"""
    qr = await ChargerQRCode.filter(id=qr_id).prefetch_related("charger").first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")

    # Payment stats
    payment_count = await QRPayment.filter(charger_qr_code_id=qr.id).count()

    stats_query = QRPayment.filter(
        charger_qr_code_id=qr.id,
        status__in=[QRPaymentStatusEnum.COMPLETED, QRPaymentStatusEnum.REFUNDED, QRPaymentStatusEnum.CHARGING]
    )
    total_revenue_result = await stats_query.annotate(total=Sum("amount_paid")).values("total")
    total_revenue = total_revenue_result[0]["total"] if total_revenue_result and total_revenue_result[0]["total"] else 0

    total_refunds_result = await QRPayment.filter(
        charger_qr_code_id=qr.id,
        status=QRPaymentStatusEnum.REFUNDED
    ).annotate(total=Sum("refund_amount")).values("total")
    total_refunds = total_refunds_result[0]["total"] if total_refunds_result and total_refunds_result[0]["total"] else 0

    return {
        "id": qr.id,
        "charger_id": qr.charger.id,
        "charger_name": qr.charger.name,
        "charge_point_string_id": qr.charger.charge_point_string_id,
        "razorpay_qr_code_id": qr.razorpay_qr_code_id,
        "image_url": qr.image_url,
        "short_url": qr.short_url,
        "is_active": qr.is_active,
        "created_at": qr.created_at.isoformat(),
        "payment_count": payment_count,
        "total_revenue": float(total_revenue),
        "total_refunds": float(total_refunds),
    }


@router.post("/{qr_id}/close")
async def close_qr_code(qr_id: int, admin_user=Depends(require_admin())):
    """Close a QR code on Razorpay and mark inactive"""
    qr = await ChargerQRCode.filter(id=qr_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")

    if not qr.is_active:
        raise HTTPException(status_code=400, detail="QR code already inactive")

    try:
        razorpay_service.close_qr_code(
            qr.razorpay_qr_code_id,
            account_id=qr.owner_razorpay_account_id,
        )
    except Exception as e:
        logger.warning(f"Failed to close QR on Razorpay (marking inactive anyway): {e}")

    qr.is_active = False
    await qr.save()

    return {"message": "QR code closed", "id": qr.id}


@router.get("/{qr_id}/payments")
async def get_qr_payments(
    qr_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    admin_user=Depends(require_admin()),
):
    """Get paginated payment history for a QR code"""
    qr = await ChargerQRCode.filter(id=qr_id).first()
    if not qr:
        raise HTTPException(status_code=404, detail="QR code not found")

    query = QRPayment.filter(charger_qr_code_id=qr_id)
    if status:
        try:
            status_enum = QRPaymentStatusEnum(status)
            query = query.filter(status=status_enum)
        except ValueError:
            pass

    total = await query.count()
    payments = await query.order_by("-created_at").offset((page - 1) * limit).limit(limit)

    results = []
    for p in payments:
        results.append({
            "id": p.id,
            "razorpay_payment_id": p.razorpay_payment_id,
            "amount_paid": str(p.amount_paid),
            "customer_vpa": p.customer_vpa,
            "customer_name": p.customer_name,
            "customer_contact": p.customer_contact,
            "energy_cost": str(p.energy_cost) if p.energy_cost else None,
            "gst_amount": str(p.gst_amount) if p.gst_amount else None,
            "platform_fee": str(p.platform_fee) if p.platform_fee is not None else None,
            "razorpay_commission": str(p.razorpay_commission) if p.razorpay_commission is not None else None,
            "razorpay_gst": str(p.razorpay_gst) if p.razorpay_gst is not None else None,
            "fee_source": p.fee_source,
            "refund_amount": str(p.refund_amount) if p.refund_amount else None,
            "status": p.status.value,
            "failure_reason": p.failure_reason,
            "transaction_id": p.transaction_id,
            "created_at": p.created_at.isoformat(),
        })

    return {"data": results, "total": total, "page": page, "limit": limit}
