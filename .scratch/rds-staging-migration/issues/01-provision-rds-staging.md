Status: ready-for-human

# Provision RDS Postgres staging instance + supporting network resources

## What to build

Three AWS resources, created in order, in `ap-south-1` (Mumbai region) under the existing `voltlync` profile:

1. **RDS subnet group** `ocpp-rds-staging-subnet-group` spanning all 3 default-VPC subnets:
   - `subnet-00851a4482a20f5fb` (ap-south-1c)
   - `subnet-0ddec295aa5498f39` (ap-south-1a)
   - `subnet-0fcf1044213447822` (ap-south-1b)

2. **RDS security group** `ocpp-rds-staging-sg` in VPC `vpc-07318777c17ea9587`:
   - Inbound rule: TCP 5432 from source SG `sg-02d9c48a3163116f8` (the staging EC2 SG, named `ocpp-server-staging-sg`)
   - Outbound: default (all)
   - No `0.0.0.0/0` inbound rules

3. **RDS Postgres instance** `ocpp-staging-db`:
   - Engine: Postgres 15.x (match current `15.17`; pick latest 15 minor available in RDS)
   - Instance class: `db.t4g.micro`
   - Storage: 20 GB gp3 (auto-scaling enabled, max 100 GB)
   - Multi-AZ: **no** (Single-AZ)
   - Publicly accessible: **no**
   - Storage encryption: enabled (default KMS key is fine)
   - Backup retention: 14 days
   - Backup window: pick a low-traffic window (e.g. 19:00-20:00 UTC = 00:30-01:30 IST)
   - Maintenance window: pick a different low-traffic window (e.g. 20:30-21:30 UTC = 02:00-03:00 IST Sunday)
   - Master username: `ocpp_admin`
   - Master password: generate via `openssl rand -base64 32`, store in a password manager — this value is only used for one-time setup; do NOT commit it anywhere
   - Subnet group: the one created in step 1
   - VPC security group: the one created in step 2
   - Performance Insights: enabled (free for 7-day retention) — useful for the validation window
   - CloudWatch logs export: enable `postgresql` log type

## Why this approach over alternatives

| Alternative | Reason rejected |
|---|---|
| Aurora Postgres | Adds cost (~2x at idle) and learning curve. Vanilla RDS is the boring correct choice for a first managed-DB migration. |
| Multi-AZ from the start | $50+/mo extra for staging where downtime is acceptable. Right answer for prod, not staging. |
| Bigger instance (`db.t4g.small`) | Current Docker postgres uses 218MB RAM, 0.3% CPU. `db.t4g.micro` with 1GB has plenty of headroom and is upgradable in-place if needed. |
| Custom VPC with private subnets | Adds 1-2 hours of VPC work + NAT gateway (~$30/mo) for marginal security benefit. SG-restricted access in the default VPC is the standard pattern. |
| Storage encryption disabled | No reason to skip it; default KMS key adds no operational complexity. |
| 7-day backup retention | The cost delta between 7 and 14 days is rounding-error; the optionality is real for "restore to last Tuesday" debugging. |

## What to do (manual / aws cli)

This issue is `ready-for-human` because it's one-time AWS provisioning with a non-rotating master password. The commands below are reference; execute via Console or aws cli as preferred.

```bash
# 1. Subnet group
aws rds create-db-subnet-group \
  --profile voltlync \
  --db-subnet-group-name ocpp-rds-staging-subnet-group \
  --db-subnet-group-description "Staging RDS subnet group across 3 AZs" \
  --subnet-ids subnet-00851a4482a20f5fb subnet-0ddec295aa5498f39 subnet-0fcf1044213447822

# 2. Security group
aws ec2 create-security-group \
  --profile voltlync \
  --group-name ocpp-rds-staging-sg \
  --description "Allow Postgres 5432 from staging EC2 only" \
  --vpc-id vpc-07318777c17ea9587 \
  --query GroupId --output text
# Note the returned sg-XXXXX id. Then:
aws ec2 authorize-security-group-ingress \
  --profile voltlync \
  --group-id <new-sg-id> \
  --protocol tcp --port 5432 \
  --source-group sg-02d9c48a3163116f8

# 3. RDS instance
MASTER_PW=$(openssl rand -base64 32 | tr -d '/=+')
echo "Master password (store securely; not used at runtime): $MASTER_PW"
aws rds create-db-instance \
  --profile voltlync \
  --db-instance-identifier ocpp-staging-db \
  --db-instance-class db.t4g.micro \
  --engine postgres \
  --engine-version 15.7 \
  --master-username ocpp_admin \
  --master-user-password "$MASTER_PW" \
  --allocated-storage 20 \
  --max-allocated-storage 100 \
  --storage-type gp3 \
  --storage-encrypted \
  --vpc-security-group-ids <new-sg-id> \
  --db-subnet-group-name ocpp-rds-staging-subnet-group \
  --no-publicly-accessible \
  --backup-retention-period 14 \
  --preferred-backup-window "19:00-20:00" \
  --preferred-maintenance-window "sun:20:30-sun:21:30" \
  --enable-performance-insights \
  --performance-insights-retention-period 7 \
  --enable-cloudwatch-logs-exports postgresql \
  --auto-minor-version-upgrade \
  --copy-tags-to-snapshot
```

## Verification

After ~10 minutes, the instance should be `available`. Verify from a session connected to staging EC2:

```bash
# From staging EC2 via make staging-ssm
ENDPOINT=$(aws rds describe-db-instances \
  --profile voltlync \
  --db-instance-identifier ocpp-staging-db \
  --query 'DBInstances[0].Endpoint.Address' --output text)
echo "RDS endpoint: $ENDPOINT"

# Test connectivity (will prompt for master password)
sudo docker run --rm -it postgres:15-alpine psql \
  -h "$ENDPOINT" -U ocpp_admin -d postgres -c "SELECT version();"
```

Expected output: a `PostgreSQL 15.x on aarch64-...` line.

## What NOT to do in this issue

- **Do not create the app user (`ocpp_staging`) yet** — that's issue 04.
- **Do not update any `.env.staging` files yet** — that's issue 05 (cutover).
- **Do not change any backend code yet** — that's issue 02.
- **Do not delete or stop the Docker postgres** — the cutover preserves it as a rollback target.

## Definition of done

- All three AWS resources exist and are in `available` / active state
- `aws rds describe-db-instances` returns `DBInstanceStatus: available` for `ocpp-staging-db`
- Connectivity from staging EC2 to the RDS endpoint as `ocpp_admin` succeeds with TLS
- Master password is stored in a password manager (not in chat, not in git)
- The endpoint hostname is recorded somewhere accessible for the next issue
