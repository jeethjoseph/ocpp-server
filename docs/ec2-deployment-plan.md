# EC2 Deployment Plan - OCPP Server (PowerLync)

## Architecture

```
                    Internet
                       |
              [Route 53 / DNS]
                       |
              [EC2 t3.medium]
              +------------------------+
              |  Docker Compose        |
              |  +------------------+  |
              |  | Nginx (443/80)   |  |   SSL termination, reverse proxy
              |  +------------------+  |
              |     |          |       |
              |  +------+  +-------+  |
              |  |Backend|  |Frontend| |   FastAPI :8000, Next.js :3000
              |  +------+  +-------+  |
              |     |                  |
              |  +------+  +-------+  |
              |  |Postgres| | Redis | |   Data layer
              |  +------+  +-------+  |
              |                        |
              |  [Certbot]             |   Auto SSL renewal
              +------------------------+
              |  SSM Agent             |   SSH-less management
              +------------------------+
```

---

## 1. EC2 Instance Sizing

### Recommendation: t3.medium (2 vCPU, 4GB RAM)

| Service    | Memory Reserved | Memory Limit | CPU Reserved | CPU Limit |
|------------|----------------|--------------|--------------|-----------|
| Postgres   | 512M           | 1G           | 0.5          | 1.0       |
| Redis      | -              | 512M         | -            | 0.5       |
| Backend    | 1G             | 2G           | 1.0          | 2.0       |
| Frontend   | 512M           | 1G           | 0.5          | 1.0       |
| Nginx      | ~64M           | ~128M        | ~0.1         | ~0.25     |
| OS+Docker  | ~400M          | -            | -            | -         |
| **Total**  | **~2.5G**      | **~4.6G**    | **~2.1**     | **~4.75** |

**Why NOT t3.small (2 vCPU, 2GB)?**
- Only 2GB total. After OS + Docker overhead (~400MB) = ~1.6GB for 5 containers.
- Next.js build spikes to ~1GB. Backend + Postgres need 1.5GB minimum.
- No headroom for traffic spikes or on-server Docker builds.

**t3.medium (~$30/mo)** gives comfortable 4GB with room for builds and spikes.

> t3.small CAN work for staging with reduced limits and 2GB swap. See Appendix A.

### Storage
- 30GB gp3 EBS (default) is sufficient
- Docker images + DB data + logs ~ 10-15GB
- Monitor with `df -h`, expand if needed

---

## 2. AWS Setup via CLI

### Prerequisites

```bash
# Install AWS CLI
brew install awscli       # macOS

# Configure credentials
aws configure
# Enter: Access Key, Secret Key, Region (ap-south-1), Output format (json)
```

### 2.1 Create VPC (or use default)

Using default VPC is fine for a single-server setup. If you want a dedicated VPC:

```bash
# Create VPC
VPC_ID=$(aws ec2 create-vpc \
    --cidr-block 10.0.0.0/16 \
    --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=ocpp-vpc}]' \
    --query 'Vpc.VpcId' --output text)

# Enable DNS hostnames (required for SSM)
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames

# Create public subnet
SUBNET_ID=$(aws ec2 create-subnet \
    --vpc-id $VPC_ID \
    --cidr-block 10.0.1.0/24 \
    --availability-zone ap-south-1a \
    --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=ocpp-public}]' \
    --query 'Subnet.SubnetId' --output text)

# Create and attach internet gateway
IGW_ID=$(aws ec2 create-internet-gateway \
    --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=ocpp-igw}]' \
    --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --internet-gateway-id $IGW_ID --vpc-id $VPC_ID

# Route table - add default route to IGW
RTB_ID=$(aws ec2 describe-route-tables \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'RouteTables[0].RouteTableId' --output text)
aws ec2 create-route --route-table-id $RTB_ID --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID

# Associate subnet with route table
aws ec2 associate-route-table --route-table-id $RTB_ID --subnet-id $SUBNET_ID

# Enable auto-assign public IP
aws ec2 modify-subnet-attribute --subnet-id $SUBNET_ID --map-public-ip-on-launch
```

### 2.2 Create Security Group

```bash
SG_ID=$(aws ec2 create-security-group \
    --group-name ocpp-server-sg \
    --description "OCPP Server - HTTP, HTTPS only (SSM for shell access)" \
    --vpc-id $VPC_ID \
    --query 'GroupId' --output text)

# HTTP (certbot ACME challenge + HTTPS redirect)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0

# HTTPS (web UI, REST API, WSS for OCPP chargers)
aws ec2 authorize-security-group-ingress \
    --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0
```

**No port 22 needed.** SSM Session Manager provides shell access without SSH.

| Port | Purpose |
|------|---------|
| 80   | HTTP redirect + ACME challenge |
| 443  | HTTPS: web UI, REST API, WSS (OCPP chargers) |

### 2.3 Create IAM Role for EC2 (SSM Access)

```bash
# Create trust policy file
cat > /tmp/ec2-trust-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "ec2.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
}
EOF

# Create role
aws iam create-role \
    --role-name OcppServerEC2Role \
    --assume-role-policy-document file:///tmp/ec2-trust-policy.json

# Attach SSM managed policy (required for Session Manager)
aws iam attach-role-policy \
    --role-name OcppServerEC2Role \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

# (Optional) Attach CloudWatch for log shipping
aws iam attach-role-policy \
    --role-name OcppServerEC2Role \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy

# Create instance profile and attach role
aws iam create-instance-profile --instance-profile-name OcppServerProfile
aws iam add-role-to-instance-profile \
    --instance-profile-name OcppServerProfile \
    --role-name OcppServerEC2Role
```

### 2.4 Create IAM User for Deployment (local machine)

This user can start SSM sessions and manage the EC2 instance.

```bash
aws iam create-user --user-name ocpp-deployer

# Create policy
cat > /tmp/deployer-policy.json << 'EOF'
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "SSMSessionAccess",
            "Effect": "Allow",
            "Action": [
                "ssm:StartSession",
                "ssm:TerminateSession",
                "ssm:ResumeSession",
                "ssm:DescribeSessions",
                "ssm:GetConnectionStatus"
            ],
            "Resource": "*"
        },
        {
            "Sid": "EC2Describe",
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeVolumes"
            ],
            "Resource": "*"
        },
        {
            "Sid": "EC2InstanceControl",
            "Effect": "Allow",
            "Action": [
                "ec2:StartInstances",
                "ec2:StopInstances",
                "ec2:RebootInstances"
            ],
            "Resource": "arn:aws:ec2:*:*:instance/*",
            "Condition": {
                "StringEquals": {"ec2:ResourceTag/Name": "ocpp-server-prod"}
            }
        }
    ]
}
EOF

aws iam put-user-policy \
    --user-name ocpp-deployer \
    --policy-name OcppDeployerPolicy \
    --policy-document file:///tmp/deployer-policy.json

# Create access keys
aws iam create-access-key --user-name ocpp-deployer
# Save the AccessKeyId and SecretAccessKey
```

### 2.5 Launch EC2 Instance

```bash
# Find latest Amazon Linux 2023 AMI
AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)

# Launch instance
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type t3.medium \
    --subnet-id $SUBNET_ID \
    --security-group-ids $SG_ID \
    --iam-instance-profile Name=OcppServerProfile \
    --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=ocpp-server-prod}]' \
    --query 'Instances[0].InstanceId' --output text)

echo "Instance ID: $INSTANCE_ID"

# Wait for instance to be running
aws ec2 wait instance-running --instance-ids $INSTANCE_ID
```

### 2.6 Allocate Elastic IP

```bash
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
ELASTIC_IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC_ID --query 'Addresses[0].PublicIp' --output text)

aws ec2 associate-address --instance-id $INSTANCE_ID --allocation-id $ALLOC_ID

echo "Elastic IP: $ELASTIC_IP"
# Point your domain DNS A record to this IP
```

---

## 3. Connect via SSM

### Install SSM Plugin (local machine)

```bash
# macOS
brew install --cask session-manager-plugin

# Verify
session-manager-plugin --version
```

### Connect to Instance

```bash
# Start SSM session
aws ssm start-session --target $INSTANCE_ID

# Or with port forwarding (e.g., to access postgres directly)
aws ssm start-session --target $INSTANCE_ID \
    --document-name AWS-StartPortForwardingSession \
    --parameters '{"portNumber":["5432"],"localPortNumber":["15432"]}'
```

### (Optional) SSH over SSM

Add to `~/.ssh/config` for seamless `ssh` and `scp`:

```
Host ocpp-prod
    HostName <INSTANCE_ID>
    User ec2-user
    ProxyCommand aws ssm start-session --target %h --document-name AWS-StartSSHSession --parameters 'portNumber=%p'
```

Then: `ssh ocpp-prod` or `scp file.txt ocpp-prod:~/`

---

## 4. Server Setup (via SSM session)

### 4.1 Install Docker

```bash
# Update system
sudo dnf update -y

# Install Docker
sudo dnf install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker ec2-user

# Install Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Verify (re-login for group change)
exit
# Start new SSM session
docker compose version
```

### 4.2 Install Git & Make

```bash
sudo dnf install -y git make
```

### 4.3 Clone Repo & Checkout Deploy Branch

```bash
cd /home/ec2-user
git clone <REPO_URL> ocpp-server
cd ocpp-server
git checkout deploy
```

### 4.4 Create Environment File

```bash
# Copy the example and fill in values
cp .env.prod.example .env.prod

# Generate a strong DB password
openssl rand -base64 32

# Edit .env.prod with your values
nano .env.prod

chmod 600 .env.prod
```

See `.env.prod.example` for the full list of required and optional variables.

---

## 5. DNS Setup

Point domain to the Elastic IP:

| Record | Name | Value |
|--------|------|-------|
| A      | @    | `<ELASTIC_IP>` |
| A      | www  | `<ELASTIC_IP>` |

Verify: `dig +short <YOUR_DOMAIN>`

---

## 6. Deployment Workflow

### Git Branch Strategy

```
main ──────────── development (PRs merge here)
  \
   deploy ─────── production EC2
```

### Deploy Flow

```bash
# FROM LOCAL MACHINE:
make prod-push                 # Force push current branch -> origin/deploy

# ON EC2 (via SSM):
aws ssm start-session --target <INSTANCE_ID>
cd ~/ocpp-server
make prod-deploy               # Pulls + rebuilds (runs migrations automatically)
```

### First Deployment

```bash
# On EC2 (via SSM)
cd ~/ocpp-server

# Start everything (nginx starts with self-signed cert)
make prod-up

# Wait ~30s for services to stabilize, then get real SSL cert
# (DNS must be pointing to this IP first)
make prod-cert
```

---

## 7. Makefile Commands

### From Local Machine
| Command | Description |
|---------|-------------|
| `make prod-push` | Force push current branch to `origin/deploy` |

### On EC2 (via SSM)
| Command | Description |
|---------|-------------|
| `make prod-deploy` | Pull + rebuild (full deploy) |
| `make prod-up` | Start all services |
| `make prod-down` | Stop all services |
| `make prod-rebuild` | Rebuild and restart |
| `make prod-logs` | Follow all logs |
| `make prod-logs-backend` | Backend logs |
| `make prod-logs-frontend` | Frontend logs |
| `make prod-logs-nginx` | Nginx logs |
| `make prod-ps` | Container status |
| `make prod-cert` | Obtain/renew SSL |
| `make prod-migrate` | Run DB migrations |
| `make prod-backup-db` | Backup database |
| `make prod-cache-clear` | Clear Redis |
| `make prod-health` | Health check |
| `make prod-stats` | Docker resource usage |
| `make prod-shell` | Python shell in backend |
| `make prod-bash` | Bash in backend |

---

## 8. OCPP-Specific Considerations

- **Single Worker**: `WORKERS=1` because OCPP WebSocket connection state is in-memory. Multiple workers would lose track of connected chargers.
- **WebSocket Timeouts**: Nginx configured with 1-hour timeout for `/ocpp/` path for long-lived charger connections.
- **No sticky sessions needed**: Single worker handles all connections.
- **Scaling beyond one server**: Would need Redis-backed OCPP session state (future work).

---

## 9. Monitoring & Maintenance

### Health Checks
All containers have Docker HEALTHCHECK configured. Nginx proxies `/health` to backend.

### Database Backups

```bash
# Manual backup
make prod-backup-db

# Automated daily backup (add to crontab on EC2)
crontab -e
# Add: 0 3 * * * cd /home/ec2-user/ocpp-server && make prod-backup-db
```

### Docker Cleanup (periodic)
```bash
docker image prune -f          # Remove dangling images
docker system prune -f         # More aggressive cleanup
```

---

## 10. Security Checklist

- [ ] No port 22 in security group (SSM only)
- [ ] EC2 role has minimal permissions (SSM + CloudWatch only)
- [ ] `.env.prod` has `chmod 600`, not in git
- [ ] API docs blocked in production nginx (`/docs`, `/openapi.json`, `/redoc`)
- [ ] HSTS, CSP, security headers in nginx prod config
- [ ] Database password is strong (`openssl rand -base64 32`)
- [ ] Certbot auto-renews SSL (runs every 12h in container)
- [ ] Daily database backups configured

---

## 11. Estimated Monthly Cost (ap-south-1 Mumbai)

| Resource | Spec | Cost/mo |
|----------|------|---------|
| EC2 t3.medium | 2 vCPU, 4GB | ~$30 |
| EBS gp3 30GB | Storage | ~$2.50 |
| Elastic IP | (attached to running instance) | $0 |
| Data Transfer | ~50GB out | ~$4.50 |
| **Total** | | **~$37/mo** |

---

## Appendix A: t3.small Budget Mode

If budget is critical, t3.small (2 vCPU, 2GB, ~$15/mo) can work with:

### Add 2GB Swap
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Reduced Resource Limits
| Service  | Memory Limit | CPU Limit |
|----------|-------------|-----------|
| Postgres | 384M        | 0.5       |
| Redis    | 128M        | 0.25      |
| Backend  | 768M        | 1.0       |
| Frontend | 384M        | 0.5       |
| Nginx    | 64M         | 0.1       |

### Trade-offs
- Swap usage degrades performance under load
- Docker builds on-server may OOM (consider building images locally)
- OK for staging or low-traffic production (<10 concurrent chargers)

## Appendix B: Full AWS CLI Setup Script

For convenience, all the AWS CLI commands above combined into a single script.
Create as `scripts/aws-setup.sh` and run section by section.

```bash
#!/bin/bash
# AWS EC2 Setup for OCPP Server
# Run section by section, not all at once.
# Adjust variables at the top before running.

set -euo pipefail

REGION="ap-south-1"
INSTANCE_TYPE="t3.medium"
VOLUME_SIZE=30
TAG_NAME="ocpp-server-prod"

echo "=== Creating IAM Role ==="
aws iam create-role \
    --role-name OcppServerEC2Role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'
aws iam attach-role-policy \
    --role-name OcppServerEC2Role \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam create-instance-profile --instance-profile-name OcppServerProfile
aws iam add-role-to-instance-profile \
    --instance-profile-name OcppServerProfile \
    --role-name OcppServerEC2Role
echo "Waiting for instance profile to propagate..."
sleep 10

echo "=== Creating Security Group ==="
SG_ID=$(aws ec2 create-security-group \
    --group-name ocpp-server-sg \
    --description "OCPP Server - HTTP/HTTPS only" \
    --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0
echo "Security Group: $SG_ID"

echo "=== Launching EC2 Instance ==="
AMI_ID=$(aws ec2 describe-images \
    --owners amazon \
    --filters "Name=name,Values=al2023-ami-2023*-x86_64" "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' --output text)
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id $AMI_ID \
    --instance-type $INSTANCE_TYPE \
    --security-group-ids $SG_ID \
    --iam-instance-profile Name=OcppServerProfile \
    --block-device-mappings "[{\"DeviceName\":\"/dev/xvda\",\"Ebs\":{\"VolumeSize\":$VOLUME_SIZE,\"VolumeType\":\"gp3\"}}]" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$TAG_NAME}]" \
    --query 'Instances[0].InstanceId' --output text)
echo "Instance: $INSTANCE_ID"
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

echo "=== Allocating Elastic IP ==="
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
aws ec2 associate-address --instance-id $INSTANCE_ID --allocation-id $ALLOC_ID
ELASTIC_IP=$(aws ec2 describe-addresses --allocation-ids $ALLOC_ID --query 'Addresses[0].PublicIp' --output text)

echo ""
echo "============================================"
echo "Setup complete!"
echo "Instance ID: $INSTANCE_ID"
echo "Elastic IP:  $ELASTIC_IP"
echo "Connect:     aws ssm start-session --target $INSTANCE_ID"
echo "============================================"
```
