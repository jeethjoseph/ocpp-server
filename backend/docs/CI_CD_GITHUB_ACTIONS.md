# GitHub Actions CI/CD for OCPP Server

## Overview

Automated deployment pipeline using GitHub Actions to deploy your FastAPI OCPP server to Vultr VPS.

**Deployment Flow:**
```
Local Dev → Git Push to main → GitHub Actions → SSH to Vultr → Deploy & Restart
```

**Deployment Time:** ~2 minutes per deployment
**Setup Time:** 15 minutes (one-time)
**Cost:** Free (within GitHub free tier)

---

## Architecture

```
┌─────────────────┐
│  Developer      │
│  Local Machine  │
└────────┬────────┘
         │ git push main
         ▼
┌─────────────────────────────────────────────┐
│            GitHub Repository                │
│  ┌────────────────────────────────────┐    │
│  │  .github/workflows/deploy.yml      │    │
│  └────────────┬───────────────────────┘    │
└───────────────┼────────────────────────────┘
                │ Triggers on push
                ▼
┌─────────────────────────────────────────────┐
│       GitHub Actions Runner (Ubuntu)        │
│                                             │
│  Steps:                                     │
│  1. Checkout code                          │
│  2. Setup SSH key                          │
│  3. SSH to Vultr                           │
│  4. Git pull latest code                   │
│  5. Install dependencies                   │
│  6. Run migrations                         │
│  7. Restart systemd service                │
│  8. Verify service is running              │
└───────────────┼─────────────────────────────┘
                │ SSH: root@139.84.209.71
                ▼
┌─────────────────────────────────────────────┐
│         Vultr VPS (139.84.209.71)          │
│                                             │
│  /root/ocpp_server/                        │
│    ├── .venv/                              │
│    ├── main.py                             │
│    ├── requirements.txt                    │
│    └── ... (other files)                   │
│                                             │
│  systemd: ocpp-server.service              │
└─────────────────────────────────────────────┘
```

---

## Setup Guide

### Step 1: Prepare Vultr Server (5 minutes)

SSH into your server and create a deployment key:

```bash
# SSH to Vultr
ssh root@139.84.209.71

# Navigate to SSH directory
cd ~/.ssh

# Generate deployment key
ssh-keygen -t ed25519 -f github_deploy -C "github-actions-deploy" -N ""

# Add public key to authorized_keys
cat github_deploy.pub >> authorized_keys

# Set correct permissions
chmod 600 github_deploy
chmod 644 github_deploy.pub
chmod 600 authorized_keys

# Display private key - COPY THIS FOR GITHUB
echo "==== COPY ENTIRE OUTPUT BELOW (including BEGIN/END lines) ===="
cat github_deploy
echo "=============================================================="
```

**Copy the entire private key output** (you'll need it for GitHub Secrets)

---

### Step 2: Initialize Git on Server (2 minutes)

```bash
# While still on Vultr server
cd /root/ocpp_server

# Check if git is initialized
git status

# If not initialized, run:
git init
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git

# Configure git user
git config user.name "Vultr Server"
git config user.email "deploy@vultr.com"

# Pull latest code
git fetch origin
git checkout main
git pull origin main
```

---

### Step 3: Configure GitHub Secrets (3 minutes)

1. Go to your GitHub repository
2. Navigate to: **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Add these secrets:

| Secret Name | Value | Example |
|-------------|-------|---------|
| `VULTR_SSH_KEY` | Paste the private key from Step 1 | `-----BEGIN OPENSSH PRIVATE KEY-----`<br>`...`<br>`-----END OPENSSH PRIVATE KEY-----` |
| `VULTR_HOST` | Your Vultr IP address | `139.84.209.71` |
| `VULTR_USER` | SSH username | `root` |
| `DEPLOY_PATH` | Deployment directory | `/root/ocpp_server` |

**⚠️ Security:** Never commit these values to your repository!

---

### Step 4: Create GitHub Actions Workflow (5 minutes)

Create the workflow file in your repository:

**Location:** `.github/workflows/deploy.yml`

```yaml
name: Deploy to Vultr

on:
  push:
    branches:
      - main  # Deploy only when pushing to main branch
    paths:
      - 'backend/**'  # Only deploy when backend code changes

  workflow_dispatch:  # Allow manual trigger from GitHub UI

jobs:
  deploy:
    name: Deploy to Vultr Server
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup SSH
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.VULTR_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          ssh-keyscan -H ${{ secrets.VULTR_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy to Vultr
        run: |
          ssh -i ~/.ssh/deploy_key ${{ secrets.VULTR_USER }}@${{ secrets.VULTR_HOST }} << 'ENDSSH'
            set -e

            echo "🚀 Starting deployment..."

            # Navigate to project directory
            cd ${{ secrets.DEPLOY_PATH }}

            # Pull latest code
            echo "📥 Pulling latest code..."
            git fetch origin
            git reset --hard origin/main

            # Activate virtual environment
            echo "🐍 Activating virtual environment..."
            source .venv/bin/activate

            # Install/update dependencies
            echo "📦 Installing dependencies..."
            pip install -r requirements.txt --quiet

            # Run database migrations (if using Aerich)
            echo "🗄️  Running migrations..."
            aerich upgrade || echo "No migrations to run"

            # Restart systemd service
            echo "🔄 Restarting service..."
            sudo systemctl restart ocpp-server

            # Wait for service to start
            sleep 3

            # Verify service is running
            if sudo systemctl is-active --quiet ocpp-server; then
              echo "✅ Deployment successful!"
              sudo systemctl status ocpp-server --no-pager -l
            else
              echo "❌ Service failed to start!"
              sudo systemctl status ocpp-server --no-pager -l
              exit 1
            fi

            echo "🎉 Deployment complete!"
          ENDSSH

      - name: Deployment summary
        if: always()
        run: |
          if [ ${{ job.status }} == 'success' ]; then
            echo "✅ Deployment succeeded"
          else
            echo "❌ Deployment failed - check logs above"
          fi
```

---

### Step 5: Commit and Push Workflow

On your local machine:

```bash
# Navigate to your project
cd /Users/raalshasan/makaratech/idofthings/ocpp-server

# Create workflow directory
mkdir -p .github/workflows

# Create the workflow file
nano .github/workflows/deploy.yml
# Paste the YAML content above, save and exit

# Add to git
git add .github/workflows/deploy.yml

# Commit
git commit -m "Add GitHub Actions deployment workflow"

# Push to trigger deployment
git push origin main
```

---

## Testing the Deployment

### Test 1: Manual Trigger

1. Go to GitHub → Your Repository → **Actions** tab
2. Click **Deploy to Vultr** workflow (left sidebar)
3. Click **Run workflow** button (right side)
4. Select `main` branch
5. Click **Run workflow**
6. Watch the deployment progress

### Test 2: Automatic Trigger

```bash
# Make a small change to backend code
cd backend
echo "# Test deployment" >> README.md

# Commit and push
git add README.md
git commit -m "test: Trigger automatic deployment"
git push origin main

# Visit GitHub Actions tab to watch deployment
```

---

## Daily Development Workflow

### Pattern 1: Direct to Main (Simple)

```bash
# 1. Make changes
vim backend/main.py

# 2. Test locally
cd backend
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 3. Commit and push
git add .
git commit -m "feat: Add new feature"
git push origin main

# 4. Automatic deployment happens!
# Watch on GitHub Actions tab
```

### Pattern 2: Feature Branches (Recommended)

```bash
# 1. Create feature branch
git checkout -b feature/new-feature

# 2. Make changes and test
# ... edit files ...

# 3. Commit to feature branch
git add .
git commit -m "feat: Add new feature"
git push origin feature/new-feature

# 4. Create Pull Request on GitHub
# - Review changes
# - Get team approval

# 5. Merge PR to main
# - Click "Merge pull request" on GitHub
# - Automatic deployment triggers!
```

---

## Understanding the Workflow

### Trigger Conditions

```yaml
on:
  push:
    branches:
      - main              # Only main branch
    paths:
      - 'backend/**'      # Only when backend/ files change

  workflow_dispatch:      # Manual trigger button
```

**What triggers deployment:**
- ✅ Push to `main` branch with changes in `backend/` folder
- ✅ Pull Request merged to `main` with backend changes
- ✅ Manual trigger from GitHub Actions UI

**What does NOT trigger:**
- ❌ Push to other branches (e.g., `develop`, `feature/*`)
- ❌ Changes only in `frontend/` or other folders
- ❌ Draft pull requests

### Deployment Steps Explained

```yaml
# 1. Checkout code
- uses: actions/checkout@v4
# Downloads your repository code to GitHub runner

# 2. Setup SSH
- run: |
    echo "${{ secrets.VULTR_SSH_KEY }}" > ~/.ssh/deploy_key
    chmod 600 ~/.ssh/deploy_key
# Creates SSH key file from GitHub Secret

# 3. Deploy via SSH
ssh -i ~/.ssh/deploy_key root@139.84.209.71 << 'ENDSSH'
  cd /root/ocpp_server
  git pull origin main                    # Get latest code
  source .venv/bin/activate              # Activate Python env
  pip install -r requirements.txt        # Update dependencies
  aerich upgrade                         # Run DB migrations
  systemctl restart ocpp-server          # Restart service
ENDSSH
```

---

## Customization Options

### Option 1: Add Testing Before Deploy

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      - name: Run tests
        run: |
          cd backend
          pytest tests/

  deploy:
    needs: test  # Only deploy if tests pass
    runs-on: ubuntu-latest
    # ... deployment steps ...
```

### Option 2: Deploy to Multiple Environments

```yaml
on:
  push:
    branches:
      - main      # Production
      - develop   # Staging

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Set environment
        run: |
          if [ "${{ github.ref }}" == "refs/heads/main" ]; then
            echo "DEPLOY_HOST=${{ secrets.PROD_HOST }}" >> $GITHUB_ENV
          else
            echo "DEPLOY_HOST=${{ secrets.STAGING_HOST }}" >> $GITHUB_ENV
          fi

      - name: Deploy
        run: |
          ssh -i ~/.ssh/deploy_key root@${{ env.DEPLOY_HOST }} << 'ENDSSH'
            # ... deployment commands ...
          ENDSSH
```

### Option 3: Health Check Verification

```yaml
- name: Verify deployment
  run: |
    sleep 5

    # Test health endpoint (add this to your FastAPI app)
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" https://yourdomain.com/health)

    if [ $RESPONSE -eq 200 ]; then
      echo "✅ Health check passed"
    else
      echo "❌ Health check failed (HTTP $RESPONSE)"
      exit 1
    fi
```

### Option 4: Slack Notifications

Add to your workflow:

```yaml
- name: Notify Slack on success
  if: success()
  run: |
    curl -X POST -H 'Content-type: application/json' \
      --data '{"text":"✅ Deployment to Vultr successful!"}' \
      ${{ secrets.SLACK_WEBHOOK_URL }}

- name: Notify Slack on failure
  if: failure()
  run: |
    curl -X POST -H 'Content-type: application/json' \
      --data '{"text":"❌ Deployment to Vultr failed!"}' \
      ${{ secrets.SLACK_WEBHOOK_URL }}
```

---

## Troubleshooting

### Issue: "Permission denied (publickey)"

**Cause:** SSH key not correctly configured

**Solution:**
```bash
# On Vultr server, verify key is in authorized_keys
cat ~/.ssh/authorized_keys | grep github

# Verify key format in GitHub Secrets
# Must include -----BEGIN OPENSSH PRIVATE KEY----- and -----END OPENSSH PRIVATE KEY-----
```

### Issue: "git pull" fails with conflicts

**Cause:** Local changes on server conflict with repository

**Solution:**
```bash
# Change deployment command to force reset
git fetch origin
git reset --hard origin/main  # This discards local changes
```

### Issue: Service fails to restart

**Check logs:**
```bash
ssh root@139.84.209.71
journalctl -u ocpp-server -n 100 --no-pager
```

**Common causes:**
- Missing environment variables
- Database connection failure
- Syntax error in code
- Port already in use

### Issue: Workflow doesn't trigger

**Check:**
1. Are you pushing to `main` branch?
2. Did you change files in `backend/` folder?
3. Check GitHub Actions tab for disabled workflows

**Enable workflow:**
- GitHub → Actions → Select workflow → Enable workflow

---

## Monitoring Deployments

### View Deployment Logs

**GitHub Actions:**
1. Go to repository → **Actions** tab
2. Click on the deployment run
3. Click on **Deploy to Vultr Server** job
4. Expand steps to see logs

**Server Logs:**
```bash
# SSH to server
ssh root@139.84.209.71

# View service logs
journalctl -u ocpp-server -f

# View recent deployments
journalctl -u ocpp-server --since "1 hour ago"
```

### Deployment History

GitHub keeps:
- ✅ Full logs for 90 days
- ✅ Deployment timestamps
- ✅ Who triggered deployment
- ✅ Commit hash deployed

---

## Rollback Procedure

### Manual Rollback

```bash
# SSH to server
ssh root@139.84.209.71

cd /root/ocpp_server

# View recent commits
git log --oneline -n 10

# Rollback to previous version
git reset --hard <commit-hash>

# Reinstall dependencies (if needed)
source .venv/bin/activate
pip install -r requirements.txt

# Restart service
systemctl restart ocpp-server

# Verify
systemctl status ocpp-server
```

### Automated Rollback (Future Enhancement)

Add to workflow:

```yaml
- name: Rollback on failure
  if: failure()
  run: |
    ssh -i ~/.ssh/deploy_key root@${{ secrets.VULTR_HOST }} << 'ENDSSH'
      cd /root/ocpp_server
      git reset --hard HEAD~1
      systemctl restart ocpp-server
    ENDSSH
```

---

## Best Practices

### 1. Branching Strategy

```
main (production - auto-deploy)
  ├── develop (optional staging)
  ├── feature/add-authentication
  ├── feature/improve-logging
  └── hotfix/critical-bug
```

**Rules:**
- ✅ `main` branch is always deployable
- ✅ Create feature branches for new work
- ✅ Test before merging to `main`
- ✅ Use Pull Requests for code review

### 2. Commit Messages

Use conventional commits:

```bash
feat: Add user authentication
fix: Resolve WebSocket timeout issue
docs: Update deployment guide
refactor: Simplify database queries
test: Add unit tests for billing
```

### 3. Environment Variables

**Never commit secrets!**

✅ Store in `.env` file on server (not in git)
✅ Reference in systemd service file
❌ Don't hardcode in Python code
❌ Don't commit to repository

### 4. Database Migrations

```bash
# Create migration
aerich migrate --name "add_user_table"

# Migrations are auto-applied during deployment
# via: aerich upgrade
```

### 5. Zero-Downtime Deployments (Future)

Current setup has ~3 second downtime during restart.

For zero-downtime:
- Use multiple Uvicorn workers
- Graceful reload instead of restart
- Or use Docker with rolling updates (future enhancement)

---

## Cost & Performance

### GitHub Actions Usage

**Free Tier:**
- Public repos: Unlimited minutes
- Private repos: 2000 minutes/month

**Typical Deployment:**
- Duration: ~2 minutes per deployment
- Monthly usage (30 deploys): 60 minutes
- **Well within free tier**

### Server Impact

- CPU usage during deployment: ~10%
- Memory usage: Minimal
- Downtime: ~3 seconds (service restart)
- Network: ~10MB (git pull + dependencies)

---

## Next Steps

### Immediate (After Initial Setup)
- [ ] Test manual deployment trigger
- [ ] Test automatic deployment on git push
- [ ] Verify logs and monitoring

### Short-term (This Week)
- [ ] Add health check endpoint to FastAPI
- [ ] Set up deployment notifications
- [ ] Document rollback procedure for team

### Medium-term (This Month)
- [ ] Add automated testing before deploy
- [ ] Create staging environment (optional)
- [ ] Set up database backups before deploy

### Long-term (Future)
- [ ] Implement blue-green deployments
- [ ] Add performance monitoring
- [ ] Consider containerization (Docker)

---

## Summary

**What You Get:**
- ✅ Automated deployments on every push to `main`
- ✅ Manual deployment trigger when needed
- ✅ Full deployment history and logs
- ✅ Simple rollback capability
- ✅ Zero cost (GitHub free tier)

**Time Investment:**
- Initial setup: 15 minutes
- Per deployment: 0 minutes (automatic)
- Monitoring: 2 minutes per deployment

**Reliability:**
- Same process every time
- No manual errors
- Logged and auditable
- Easy to debug

Ready to implement? Start with Step 1!
