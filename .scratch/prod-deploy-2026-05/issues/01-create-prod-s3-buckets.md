Status: ready-for-human

# Create prod S3 buckets for invoices + firmware

## What to build

Two S3 buckets in `ap-south-1` (Mumbai) under the `voltlync` AWS profile:

1. **`voltlync-invoices-prod`** — GST invoice PDFs
2. **`voltlync-firmware-prod`** — firmware binary files

Each needs server-side encryption, lifecycle policy, IAM access for the prod EC2 instance role, and (for invoices only) a CORS policy permitting cross-origin GET from `https://app.voltlync.com`.

Both buckets are referenced from the new env vars in issue 02 (`AWS_S3_INVOICE_BUCKET`, `AWS_S3_FIRMWARE_BUCKET`). The backend silently falls back to no-S3 behavior when the env var is empty — so creation needs to happen before env update so we're not stuck in degraded mode.

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Single bucket with `/invoices/` and `/firmware/` prefixes | Different retention requirements (invoices 7y for GST compliance, firmware ~1y). Different CORS needs. Separating cleanly avoids policy contortions. |
| Skip CORS on the invoice bucket | Frontend fetches PDF blobs cross-origin via presigned URLs. Without CORS the browser rejects the redirected response — see `feedback_s3_cors_for_pdf_fetch` memory. Burned us once already. |
| Public bucket with no IAM tightening | Invoices contain customer GSTIN + amounts — PII-adjacent. Private bucket with presigned URL access only. |

## What to do

### 1. Create the invoices bucket

```bash
aws s3api create-bucket \
  --profile voltlync \
  --bucket voltlync-invoices-prod \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1

aws s3api put-bucket-encryption \
  --profile voltlync \
  --bucket voltlync-invoices-prod \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
      "BucketKeyEnabled": true
    }]
  }'

aws s3api put-public-access-block \
  --profile voltlync \
  --bucket voltlync-invoices-prod \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# CORS for cross-origin PDF fetch from app.voltlync.com.
# Per feedback_s3_cors_for_pdf_fetch — required for the admin GST invoice viewer.
aws s3api put-bucket-cors \
  --profile voltlync \
  --bucket voltlync-invoices-prod \
  --cors-configuration '{
    "CORSRules": [{
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "HEAD"],
      "AllowedOrigins": ["https://app.voltlync.com"],
      "ExposeHeaders": ["ETag", "Content-Length", "Content-Type"],
      "MaxAgeSeconds": 3600
    }]
  }'
```

Lifecycle: 7-year retention for GST compliance, transition older objects to Glacier Instant Retrieval after 90 days to save cost:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --profile voltlync \
  --bucket voltlync-invoices-prod \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "invoices-retention",
      "Status": "Enabled",
      "Filter": {},
      "Transitions": [{
        "Days": 90,
        "StorageClass": "GLACIER_IR"
      }],
      "Expiration": {"Days": 2555}
    }]
  }'
```

### 2. Create the firmware bucket

```bash
aws s3api create-bucket \
  --profile voltlync \
  --bucket voltlync-firmware-prod \
  --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1

aws s3api put-bucket-encryption \
  --profile voltlync \
  --bucket voltlync-firmware-prod \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
      "BucketKeyEnabled": true
    }]
  }'

aws s3api put-public-access-block \
  --profile voltlync \
  --bucket voltlync-firmware-prod \
  --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# No CORS — chargers download firmware via short presigned URLs server-side.
# Lifecycle: 365-day retention for firmware (well past any device upgrade window).
aws s3api put-bucket-lifecycle-configuration \
  --profile voltlync \
  --bucket voltlync-firmware-prod \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "firmware-retention",
      "Status": "Enabled",
      "Filter": {},
      "Expiration": {"Days": 365}
    }]
  }'
```

### 3. Verify prod EC2 instance role can access both buckets

First identify the prod instance profile:

```bash
aws ec2 describe-instances \
  --profile voltlync \
  --instance-ids i-0df24c96c4d5e890a \
  --query 'Reservations[].Instances[].IamInstanceProfile' --output json
```

Take the role name from the returned ARN. Then attach an inline policy granting S3 access (replace `<ROLE_NAME>`):

```bash
aws iam put-role-policy \
  --profile voltlync \
  --role-name <ROLE_NAME> \
  --policy-name voltlync-prod-s3-access \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
        "Resource": [
          "arn:aws:s3:::voltlync-invoices-prod/*",
          "arn:aws:s3:::voltlync-firmware-prod/*"
        ]
      },
      {
        "Effect": "Allow",
        "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
        "Resource": [
          "arn:aws:s3:::voltlync-invoices-prod",
          "arn:aws:s3:::voltlync-firmware-prod"
        ]
      }
    ]
  }'
```

### 4. Validate from prod EC2

```bash
# From SSM session on prod EC2:
aws s3 ls s3://voltlync-invoices-prod
aws s3 ls s3://voltlync-firmware-prod

# Write + read a test object:
echo "test $(date)" > /tmp/s3-test.txt
aws s3 cp /tmp/s3-test.txt s3://voltlync-invoices-prod/healthcheck.txt
aws s3 cp s3://voltlync-invoices-prod/healthcheck.txt -
aws s3 rm s3://voltlync-invoices-prod/healthcheck.txt
# Repeat for firmware bucket.
```

### 5. Validate CORS from a browser

Open https://app.voltlync.com in a browser, then in DevTools console:

```javascript
fetch('https://voltlync-invoices-prod.s3.ap-south-1.amazonaws.com/', {mode: 'cors'})
  .then(r => console.log('CORS OK', r.status))
  .catch(e => console.error('CORS FAIL', e));
```

Expected: a 403 (the bucket is private — no anonymous list) but the preflight CORS check passes. If you see a CORS error in the console, the policy isn't right.

## Definition of done

- Both buckets exist, encrypted, public access blocked
- Invoice bucket has CORS allowing `https://app.voltlync.com` GET/HEAD
- Lifecycle policies configured (invoices 90d → Glacier-IR, 7y expiration; firmware 365d expiration)
- Prod EC2 role has IAM policy attached granting PUT/GET/DELETE/LIST on both buckets
- Write + read smoke test from prod EC2 succeeds for both buckets
- CORS preflight passes from app.voltlync.com origin
