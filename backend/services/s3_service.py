"""S3 persistence for GST invoice PDFs.

Lazy upload: PDFs are generated on demand at the download endpoint, uploaded
to S3 on first request, and `gst_invoice.pdf_url` is populated with the S3
key. Subsequent requests redirect to a presigned URL.

Env vars:
- AWS_S3_INVOICE_BUCKET — bucket name (per-env)
- AWS_REGION — defaults to ap-south-1
- Credentials resolved via boto3's default chain (EC2 instance role in prod;
  ~/.aws/credentials with `voltlync` profile for local dev).
"""

import logging
import os
import re
from functools import lru_cache
from typing import Optional

import boto3
from botocore.config import Config

logger = logging.getLogger("ocpp-server")

PRESIGN_DEFAULT_EXPIRY = 900  # 15 minutes
_INVOICE_NUMBER_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _bucket() -> str:
    bucket = os.getenv("AWS_S3_INVOICE_BUCKET")
    if not bucket:
        raise RuntimeError(
            "AWS_S3_INVOICE_BUCKET is not configured — cannot persist invoice PDFs"
        )
    return bucket


@lru_cache(maxsize=1)
def _client():
    region = os.getenv("AWS_REGION", "ap-south-1")
    profile = os.getenv("AWS_PROFILE")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client(
        "s3",
        region_name=region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _build_key(invoice) -> str:
    """invoices/{FY}/{franchisee_or_voltlync}/{sanitized_invoice_number}.pdf"""
    fy = invoice.financial_year or "unknown-fy"
    owner = f"F{invoice.franchisee_id}" if invoice.franchisee_id else "voltlync"
    safe_number = _INVOICE_NUMBER_SAFE.sub("_", invoice.invoice_number or f"inv-{invoice.id}")
    return f"invoices/{fy}/{owner}/{safe_number}.pdf"


def upload_invoice_pdf(invoice, pdf_bytes: bytes) -> str:
    """Upload PDF bytes to S3. Returns the S3 key.

    Caller is responsible for persisting the returned key onto
    `gst_invoice.pdf_url`.
    """
    key = _build_key(invoice)
    _client().put_object(
        Bucket=_bucket(),
        Key=key,
        Body=pdf_bytes,
        ContentType="application/pdf",
        ContentDisposition=f'inline; filename="{invoice.invoice_number}.pdf"',
        ServerSideEncryption="AES256",
    )
    logger.info("Uploaded invoice PDF to s3://%s/%s", _bucket(), key)
    return key


def generate_presigned_url(key: str, expires_in: int = PRESIGN_DEFAULT_EXPIRY) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires_in,
    )


def download_pdf(key: str) -> Optional[bytes]:
    try:
        resp = _client().get_object(Bucket=_bucket(), Key=key)
        return resp["Body"].read()
    except _client().exceptions.NoSuchKey:
        return None
