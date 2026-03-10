"""Admin endpoints for managing Razorpay QR codes on chargers"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
import logging

from auth_middleware import require_admin
from models import Charger, ChargerQRCode, QRPayment, QRPaymentStatusEnum
from services.razorpay_service import razorpay_service
from tortoise.functions import Count, Sum

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/qr-codes", tags=["QR Codes"])


class CreateQRCodeRequest(BaseModel):
    charger_id: int


@router.post("")
async def create_qr_code(request: CreateQRCodeRequest, admin_user=Depends(require_admin())):
    """Create a Razorpay QR code for a charger"""
    charger = await Charger.filter(id=request.charger_id).first()
    if not charger:
        raise HTTPException(status_code=404, detail="Charger not found")

    # Check if QR already exists
    existing = await ChargerQRCode.filter(charger=charger).first()
    if existing:
        raise HTTPException(status_code=400, detail="QR code already exists for this charger")

    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay not configured")

    try:
        result = razorpay_service.create_qr_code(
            charger_id=charger.id,
            charge_point_string_id=charger.charge_point_string_id,
            name=charger.name or charger.charge_point_string_id,
        )

        qr_code = await ChargerQRCode.create(
            charger=charger,
            razorpay_qr_code_id=result["id"],
            image_url=result.get("image_url", ""),
            short_url=result.get("short_url"),
            is_active=True,
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
            "created_at": qr_code.created_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Failed to create QR code: {e}", exc_info=True)
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
    qr = await ChargerQRCode.filter(charger_id=charger_id).prefetch_related("charger").first()
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
        razorpay_service.close_qr_code(qr.razorpay_qr_code_id)
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
            "platform_fee": str(p.platform_fee) if p.platform_fee else None,
            "refund_amount": str(p.refund_amount) if p.refund_amount else None,
            "status": p.status.value,
            "failure_reason": p.failure_reason,
            "transaction_id": p.transaction_id,
            "created_at": p.created_at.isoformat(),
        })

    return {"data": results, "total": total, "page": page, "limit": limit}
