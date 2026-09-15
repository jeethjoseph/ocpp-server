#!/usr/bin/env python3
"""One-shot backfill: strip Razorpay's "unknown payer" placeholders from
QR payments and the GST invoices issued from them.

From 2026-09-04 (fleet-wide 2026-09-09) Razorpay started stamping UPI QR
payments it cannot attribute with ``email=void@razorpay.com`` and
``contact=919999999999`` instead of leaving those fields empty. The webhook
parser used the email as a customer-name fallback, so invoices printed
"BILLED TO: void@razorpay.com". The parser now scrubs both placeholders
(see ``scrub_razorpay_placeholder_*`` in ``services/qr_payment_service.py``);
this script repairs the rows written before that fix shipped.

What it changes:
  * ``qr_payment.customer_name``    -> NULL where it is the placeholder email
  * ``qr_payment.customer_contact`` -> NULL where it is the placeholder contact
  * ``app_user.phone_number``       -> NULL where it is the placeholder contact
    (the UPI_GUEST created from the first placeholder payment stored it)
  * ``gst_invoice.customer_name``   -> ``customer_identifier`` (the payer's
    UPI ID, the same fallback the issuer would have used) where it is the
    placeholder email
  * ``gst_invoice.pdf_url``         -> NULL on those invoices, so the next
    download regenerates the PDF and overwrites the cached S3 object (the
    S3 key is deterministic per invoice number)

It does NOT re-attribute ``qr_payment.user_id`` / ``transaction.user_id``:
the placeholder contact also short-circuited the phone-first user lookup
and merged distinct payers into one UPI_GUEST user. Undoing that touches
session ownership and is a separate, explicitly-approved step.

Usage (dev):
    docker exec ocpp-backend python scripts/backfill_razorpay_placeholder_identity.py           # dry-run
    docker exec ocpp-backend python scripts/backfill_razorpay_placeholder_identity.py --apply   # commit

Usage (staging / prod): `docker exec` runs as root there, but the deps are a
`pip install --user` under /home/app, so point Python at them explicitly:
    docker exec -e PYTHONPATH=/home/app/.local/lib/python3.11/site-packages \
        ocpp-backend-prod python scripts/backfill_razorpay_placeholder_identity.py [--apply]
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill_razorpay_placeholder_identity")

PLACEHOLDER_EMAIL = "void@razorpay.com"
PLACEHOLDER_CONTACTS = ("919999999999", "+919999999999", "9999999999")


async def _report_payments(QRPayment, User) -> int:
    named = await QRPayment.filter(customer_name=PLACEHOLDER_EMAIL).count()
    contact = await QRPayment.filter(customer_contact__in=PLACEHOLDER_CONTACTS).count()
    users = await User.filter(phone_number__in=PLACEHOLDER_CONTACTS).count()
    logger.info("qr_payment rows with placeholder customer_name:    %d", named)
    logger.info("qr_payment rows with placeholder customer_contact: %d", contact)
    logger.info("app_user rows with placeholder phone_number:       %d", users)
    return named + contact + users


async def _report_invoices(GSTInvoice) -> int:
    invoices = await GSTInvoice.filter(customer_name=PLACEHOLDER_EMAIL).all()
    cached = sum(1 for inv in invoices if inv.pdf_url)
    logger.info(
        "gst_invoice rows with placeholder customer_name:   %d (%d with cached PDF)",
        len(invoices), cached,
    )
    for inv in invoices:
        logger.info(
            "  id=%-5d %-18s -> %s%s",
            inv.id, inv.invoice_number, inv.customer_identifier or "(no identifier)",
            "  [pdf cached]" if inv.pdf_url else "",
        )
    return len(invoices)


async def _apply(QRPayment, GSTInvoice, User) -> None:
    from tortoise.expressions import F

    n1 = await QRPayment.filter(customer_name=PLACEHOLDER_EMAIL).update(customer_name=None)
    n2 = await QRPayment.filter(customer_contact__in=PLACEHOLDER_CONTACTS).update(
        customer_contact=None
    )
    n0 = await User.filter(phone_number__in=PLACEHOLDER_CONTACTS).update(phone_number=None)
    n3 = await GSTInvoice.filter(
        customer_name=PLACEHOLDER_EMAIL, customer_identifier__isnull=False,
    ).update(customer_name=F("customer_identifier"), pdf_url=None)
    n4 = await GSTInvoice.filter(
        customer_name=PLACEHOLDER_EMAIL, customer_identifier__isnull=True,
    ).update(customer_name=None, pdf_url=None)
    logger.info(
        "\n✅ qr_payment: %d names + %d contacts cleared; app_user: %d phones "
        "cleared; gst_invoice: %d re-named to UPI ID, %d cleared (PDF cache "
        "dropped on all).", n1, n2, n0, n3, n4,
    )


async def run(apply: bool) -> int:
    from database import init_db, close_db
    from models import GSTInvoice, QRPayment, User

    await init_db()
    try:
        total = await _report_payments(QRPayment, User)
        total += await _report_invoices(GSTInvoice)
        if total == 0:
            logger.info("Nothing to do.")
            return 0
        if not apply:
            logger.info("\nDry-run only. Re-run with --apply to commit.")
            return total
        await _apply(QRPayment, GSTInvoice, User)
        return total
    finally:
        await close_db()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Commit the update. Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
