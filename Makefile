# OCPP Server Makefile for Database Management

# Load environment - backend/.env for local dev, .env.prod/.env.staging for EC2
# On EC2 prod: backend/.env doesn't exist (skipped), .env.prod provides prod values
# On EC2 staging: backend/.env doesn't exist (skipped), .env.staging provides staging values
# On local: backend/.env provides dev values, .env.prod/.env.staging don't exist (skipped)
-include backend/.env
-include .env.prod
-include .env.staging
export

# Fallback to local database if not set in .env
DB_HOST ?= localhost
DB_PORT ?= 5432  
DB_USER ?= ocpp_user
DB_PASSWORD ?= ocpp_password
DB_NAME ?= ocpp_db
PG_SUPERUSER=$(shell whoami)

# Directories
BACKEND_DIR=backend
SCRIPTS_DIR=$(BACKEND_DIR)/scripts

.PHONY: help db-reset db-reset-cloud db-first-time db-drop-user db-create-user db-drop db-create migrate seed setup-dev truncate-tables
.PHONY: docker-dev docker-dev-detach docker-staging docker-staging-detach docker-prod docker-prod-detach docker-down docker-down-staging docker-down-prod docker-logs docker-logs-backend docker-logs-frontend docker-build docker-build-staging docker-build-prod docker-clean docker-migrate docker-staging-cert docker-prod-cert docker-cert-renew
.PHONY: prod-push prod-pull prod-up prod-down prod-deploy prod-rebuild prod-rebuild-service prod-rebuild-clean prod-nuke prod-restart prod-prune prod-prune-if-needed prod-logs prod-logs-backend prod-logs-frontend prod-logs-nginx prod-ps prod-cert prod-migrate prod-backup-db prod-restore-db prod-cache-clear prod-health prod-stats prod-shell prod-bash prod-ssm prod-db-reset prod-seed
.PHONY: staging-push staging-pull staging-up staging-down staging-deploy staging-rebuild staging-rebuild-service staging-rebuild-clean staging-nuke staging-restart staging-logs staging-logs-backend staging-logs-frontend staging-logs-nginx staging-ps staging-cert staging-migrate staging-backup-db staging-restore-db staging-cache-clear staging-health staging-stats staging-shell staging-bash staging-ssm staging-db-reset staging-seed staging-rds-shell

help:
	@echo "OCPP Server - Available Commands"
	@echo ""
	@echo "=============== PRODUCTION (EC2 via SSM) ==============="
	@echo ""
	@echo "Deployment (from local machine):"
	@echo "  make prod-push           Force push current branch to origin/deploy"
	@echo ""
	@echo "Deployment (on EC2 server via SSM):"
	@echo "  make prod-deploy         Pull + rebuild (full deploy)"
	@echo "  make prod-pull           Force pull origin/deploy"
	@echo "  make prod-rebuild        Rebuild containers"
	@echo "  make prod-rebuild-service SERVICE=backend  Rebuild one service"
	@echo "  make prod-rebuild-clean  Full clean rebuild (removes images)"
	@echo ""
	@echo "Services:"
	@echo "  make prod-up             Start production services"
	@echo "  make prod-down           Stop production services"
	@echo "  make prod-restart        Restart all services"
	@echo "  make prod-nuke           Remove everything + volumes (DANGEROUS)"
	@echo "  make prod-ps             Show container status"
	@echo "  make prod-stats          Resource usage snapshot"
	@echo "  make prod-health         Health check"
	@echo ""
	@echo "Logs:"
	@echo "  make prod-logs           View all logs"
	@echo "  make prod-logs-backend   View backend logs"
	@echo "  make prod-logs-frontend  View frontend logs"
	@echo "  make prod-logs-nginx     View nginx logs"
	@echo ""
	@echo "Database & Cache:"
	@echo "  make prod-migrate        Run database migrations"
	@echo "  make prod-backup-db      Backup database to backups/"
	@echo "  make prod-restore-db     Restore DB from newest dump (or DUMP=path)"
	@echo "  make prod-db-reset       Reset database (DANGEROUS)"
	@echo "  make prod-seed           Run seed script"
	@echo "  make prod-cache-clear    Clear all Redis cache"
	@echo ""
	@echo "Disk maintenance:"
	@echo "  make prod-prune          Prune build cache + dangling images (safe; volumes untouched)"
	@echo ""
	@echo "SSL & Shell:"
	@echo "  make prod-cert           Obtain/renew SSL certificate"
	@echo "  make prod-shell          Open Python shell in backend"
	@echo "  make prod-bash           Open bash in backend"
	@echo "  make prod-ssm            Start SSM shell on the prod EC2 host"
	@echo ""
	@echo "=============== STAGING (EC2 via SSM) ==============="
	@echo ""
	@echo "Deployment (from local machine):"
	@echo "  make staging-push           Force push current branch to origin/develop"
	@echo ""
	@echo "Deployment (on staging EC2 via SSM):"
	@echo "  make staging-deploy         Pull + rebuild (full deploy)"
	@echo "  make staging-pull           Force pull origin/develop"
	@echo "  make staging-rebuild        Rebuild containers"
	@echo "  make staging-rebuild-service SERVICE=backend  Rebuild one service"
	@echo "  make staging-rebuild-clean  Full clean rebuild (removes images)"
	@echo ""
	@echo "Services:"
	@echo "  make staging-up             Start staging services"
	@echo "  make staging-down           Stop staging services"
	@echo "  make staging-restart        Restart all services"
	@echo "  make staging-nuke           Remove everything + volumes (DANGEROUS)"
	@echo "  make staging-ps             Show container status"
	@echo "  make staging-stats          Resource usage snapshot"
	@echo "  make staging-health         Health check"
	@echo ""
	@echo "Logs:"
	@echo "  make staging-logs           View all logs"
	@echo "  make staging-logs-backend   View backend logs"
	@echo "  make staging-logs-frontend  View frontend logs"
	@echo "  make staging-logs-nginx     View nginx logs"
	@echo ""
	@echo "Database & Cache:"
	@echo "  make staging-migrate        Run database migrations"
	@echo "  make staging-backup-db      Backup database to backups/"
	@echo "  make staging-restore-db     Restore DB from newest dump (or DUMP=path)"
	@echo "  make staging-db-reset       Reset database (DANGEROUS)"
	@echo "  make staging-seed           Run seed script"
	@echo "  make staging-cache-clear    Clear all Redis cache"
	@echo ""
	@echo "Disk maintenance:"
	@echo "  make staging-prune          Prune build cache + dangling images (safe; volumes untouched)"
	@echo ""
	@echo "SSL & Shell:"
	@echo "  make staging-cert           Obtain/renew SSL certificate"
	@echo "  make staging-shell          Open Python shell in backend"
	@echo "  make staging-bash           Open bash in backend"
	@echo "  make staging-ssm            Start SSM shell on the staging EC2 host"
	@echo "  make staging-rds-shell      Open psql shell against staging RDS"
	@echo ""
	@echo "=============== DEVELOPMENT (local) ==============="
	@echo ""
	@echo "Docker:"
	@echo "  make docker-dev          Start dev environment with hot-reload"
	@echo "  make docker-dev-detach   Start dev environment (detached)"
	@echo "  make docker-down         Stop dev containers"
	@echo "  make docker-build        Build dev images"
	@echo "  make docker-clean        Remove containers, volumes, images"
	@echo "  make docker-logs         Follow all container logs"
	@echo "  make docker-migrate      Run database migrations"
	@echo ""
	@echo "Database (local):"
	@echo "  make db-reset            Database reset (drop, recreate, migrate, seed)"
	@echo "  make db-first-time       First-time setup (drop, recreate, init-db, seed)"
	@echo "  make migrate             Run database migrations"
	@echo "  make seed                Run seed script"
	@echo "  make setup-dev           Initial development setup"

# Complete database reset (uses existing migrations)
db-reset: db-drop db-drop-user db-create-user db-create migrate seed
	@echo "✅ Database reset complete!"

# Cloud database reset (for managed databases like Neon)
db-reset-cloud: truncate-tables migrate seed
	@echo "✅ Cloud database reset complete!"

# First-time setup (only use when no migrations exist yet)
db-first-time: db-drop db-drop-user db-create-user db-create init-fresh-db seed
	@echo "✅ First-time database setup complete!"

# Drop database user
db-drop-user:
	@echo "🗑️  Dropping database user..."
	@echo "   Reassigning owned objects..."
	-psql -U $(PG_SUPERUSER) -d postgres -c "REASSIGN OWNED BY $(DB_USER) TO $(PG_SUPERUSER);"
	-psql -U $(PG_SUPERUSER) -d postgres -c "DROP OWNED BY $(DB_USER);"
	-psql -U $(PG_SUPERUSER) -d postgres -c "DROP USER IF EXISTS $(DB_USER);"

# Create database user
db-create-user:
	@echo "👤 Creating database user..."
	psql -U $(PG_SUPERUSER) -d postgres -c "CREATE USER $(DB_USER) WITH ENCRYPTED PASSWORD '$(DB_PASSWORD)';"
	psql -U $(PG_SUPERUSER) -d postgres -c "ALTER USER $(DB_USER) CREATEDB;"

# Drop database
db-drop:
	@echo "🗑️  Dropping database..."
	@echo "   Terminating active connections..."
	-psql -U $(PG_SUPERUSER) -d postgres -c "SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '$(DB_NAME)' AND pid <> pg_backend_pid();"
	-psql -U $(PG_SUPERUSER) -d postgres -c "DROP DATABASE IF EXISTS $(DB_NAME);"

# Create database
db-create:
	@echo "🗄️  Creating database..."
	psql -U $(PG_SUPERUSER) -d postgres -c "CREATE DATABASE $(DB_NAME) OWNER $(DB_USER);"
	psql -U $(PG_SUPERUSER) -d postgres -c "GRANT ALL PRIVILEGES ON DATABASE $(DB_NAME) TO $(DB_USER);"

# Initialize fresh database (creates initial migration and applies it)
init-fresh-db:
	@echo "🔄 Setting up fresh database..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && aerich init-db

# Run migrations
migrate:
	@echo "🔄 Running migrations..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && aerich upgrade

# Run seed script (via docker exec — orchestrates seed_docker + seed_franchisees)
# Usage:
#   make seed
#   CLERK_ADMIN_ID=user_xxx ADMIN_EMAIL=you@example.com make seed
seed:
	@echo "🌱 Seeding database via docker exec..."
	@docker exec \
		-e CLERK_ADMIN_ID=$(CLERK_ADMIN_ID) \
		-e ADMIN_EMAIL=$(ADMIN_EMAIL) \
		-e CLERK_USER_ID=$(CLERK_USER_ID) \
		-e USER_EMAIL=$(USER_EMAIL) \
		ocpp-backend python scripts/seed_all.py

# Initial development setup (for first time)
setup-dev: db-create-user db-create
	@echo "🛠️  Setting up development environment..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && aerich init-db
	@echo "✅ Development setup complete! Run 'make seed' to add sample data."

# Install dependencies (bonus target)
install:
	@echo "📦 Installing backend dependencies..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && pip install -r requirements.txt

# Test database connection
test-connection:
	@echo "🔗 Testing database connection..."
	psql -U $(DB_USER) -h $(DB_HOST) -p $(DB_PORT) -d $(DB_NAME) -c "SELECT 'Connection successful!' as status;"

# Test migration system (generate and apply a test migration)
test-migrations:
	@echo "🧪 Testing migration system..."
	@echo "   Generating test migration..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && aerich migrate --name test_migration
	@echo "   Applying test migration..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && aerich upgrade
	@echo "✅ Migration system working correctly!"

# Truncate tables (for cloud databases where you can't drop/create DB)
truncate-tables:
	@echo "🗑️  Truncating all tables..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && python scripts/truncate_tables.py

# =============================================================================
# PRODUCTION DEPLOYMENT (Git-based, EC2 via SSM)
# =============================================================================
# Deploy branch: origin/deploy
# Workflow: prod-push (local) -> SSM into EC2 -> prod-deploy (on server)
# See docs/ec2-deployment-plan.md for full setup guide.

PROD_COMPOSE = docker compose -f docker-compose.prod.yml --env-file .env.prod

# Force push current branch to origin/deploy (run from local machine)
prod-push:
	@echo "Force pushing current branch to origin/deploy..."
	git push origin HEAD:deploy --force
	@echo "Pushed to origin/deploy. Now SSM into EC2 and run: make prod-deploy"

# Force pull from origin/deploy (run on EC2 server)
prod-pull:
	@echo "Pulling from origin/deploy..."
	git fetch origin
	git reset --hard origin/deploy
	@echo "Updated to origin/deploy"

# Start production services
prod-up:
	$(PROD_COMPOSE) up -d

# Stop production services
prod-down:
	$(PROD_COMPOSE) down

# Rebuild and restart production (after pull)
prod-rebuild:
	$(PROD_COMPOSE) up -d --build --force-recreate
	@echo "Waiting for services to stabilize..."
	@sleep 5
	@if ! $(PROD_COMPOSE) exec -T nginx test -d /etc/letsencrypt/archive 2>/dev/null; then \
		echo ""; \
		echo "=============================================="; \
		echo "WARNING: No Let's Encrypt certificate found!"; \
		echo "Currently using self-signed certificate."; \
		echo "Run 'make prod-cert' to obtain a real certificate."; \
		echo "=============================================="; \
	else \
		echo "Let's Encrypt certificate found."; \
	fi

# Full deploy sequence (run on EC2 after SSM).
# `prod-prune-if-needed` runs between pull and rebuild: it's a no-op when
# disk is healthy, and self-heals when the build cache has bloated past
# 85% root-volume usage. Mirrors the staging routine — keeps deploys fast
# in the common case, never fails on ENOSPC mid-build.
prod-deploy: prod-pull prod-prune-if-needed prod-rebuild
	@echo "Production deployment complete!"

# Manual disk cleanup. Safe by construction:
#   - builder prune: drops build cache only (not images, not containers, not volumes)
#   - image prune: drops dangling images (NOT in use by running containers)
# Volumes are untouched, so postgres/redis/firmware data are safe.
# Run when you see `df -h /` getting tight or want a deliberate cleanup.
.PHONY: prod-prune
prod-prune:
	@echo "Pruning Docker build cache..."
	sudo docker builder prune -af
	@echo "Pruning dangling images..."
	sudo docker image prune -af
	@echo "Disk usage after prune:"
	@df -h / | tail -2

# Conditional version used by prod-deploy. Prunes only when root-volume
# usage exceeds 85%. The shell logic must be on one line (Make runs each
# recipe line in its own subshell) — kept readable via backslash continuations.
.PHONY: prod-prune-if-needed
prod-prune-if-needed:
	@USAGE=$$(df / | tail -1 | awk '{print $$5}' | tr -d %); \
	if [ "$$USAGE" -gt 85 ]; then \
		echo "Disk at $$USAGE%, pruning build cache + dangling images..."; \
		sudo docker builder prune -af; \
		sudo docker image prune -af; \
		df -h / | tail -2; \
	else \
		echo "Disk at $$USAGE%, no prune needed (threshold 85%)"; \
	fi

# Restart all services without rebuilding
prod-restart:
	# `up -d` re-reads --env-file and recreates containers whose config
	# changed (plain `docker compose restart` does NOT re-read env vars —
	# it just bounces the process inside the existing container).
	$(PROD_COMPOSE) up -d

# Rebuild a single service (usage: make prod-rebuild-service SERVICE=backend)
prod-rebuild-service:
	$(PROD_COMPOSE) up -d --build --force-recreate --no-deps $(SERVICE)

# Full clean rebuild (removes images, rebuilds from scratch)
prod-rebuild-clean:
	$(PROD_COMPOSE) down --rmi local
	$(PROD_COMPOSE) up -d --build

# Nuke everything including volumes (DANGEROUS - destroys DB data)
prod-nuke:
	@echo "WARNING: This will destroy ALL data including the database!"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	$(PROD_COMPOSE) down -v --rmi local
	@echo "All containers, volumes, and images removed."

# View production logs — last 100 lines + live tail.
# For full history pipe `$(PROD_COMPOSE) logs > prod.log` (no -f) and grep.
prod-logs:
	$(PROD_COMPOSE) logs --tail=100 -f

# View specific service logs — last 100 lines + live tail.
prod-logs-backend:
	$(PROD_COMPOSE) logs --tail=100 -f backend

prod-logs-frontend:
	$(PROD_COMPOSE) logs --tail=100 -f frontend

prod-logs-nginx:
	$(PROD_COMPOSE) logs --tail=100 -f nginx

# Run migrations on production
prod-migrate:
	$(PROD_COMPOSE) exec backend aerich upgrade

# Open Python shell on production backend
prod-shell:
	$(PROD_COMPOSE) exec backend python -c "import IPython; IPython.start_ipython()" 2>/dev/null || \
	$(PROD_COMPOSE) exec backend python

# Open bash on production backend container
prod-bash:
	$(PROD_COMPOSE) exec backend bash

# SSH into the production EC2 instance via AWS SSM (no inbound SSH required)
prod-ssm:
	aws ssm start-session --target i-0df24c96c4d5e890a --profile voltlync

# Show production container status
prod-ps:
	$(PROD_COMPOSE) ps

# Resource monitoring (single snapshot)
prod-stats:
	docker stats --no-stream

# Health check
prod-health:
	@curl -sf http://localhost/health && echo " Health check passed" || echo " Health check failed"

# Obtain/renew Let's Encrypt SSL certificate
prod-cert:
	@echo "Obtaining SSL certificate..."
	@echo "Clearing any existing certificates..."
	$(PROD_COMPOSE) run --rm --entrypoint "" certbot \
		sh -c "rm -rf /etc/letsencrypt/live/$${DOMAIN_NAME}* /etc/letsencrypt/renewal/$${DOMAIN_NAME}* /etc/letsencrypt/archive/$${DOMAIN_NAME}*"
	@echo "Requesting certificate from Let's Encrypt..."
	$(PROD_COMPOSE) run --rm --entrypoint "" certbot \
		certbot certonly --webroot --webroot-path=/var/www/certbot \
		--email $${CERTBOT_EMAIL} --agree-tos --no-eff-email \
		-d $${DOMAIN_NAME}
	@echo "Restarting nginx to load new certificate..."
	$(PROD_COMPOSE) restart nginx
	@echo "SSL certificate installed!"

# Clear all Redis cache
prod-cache-clear:
	@echo "Clearing ALL Redis cache on production..."
	@echo "Press Ctrl+C to cancel, or wait 3 seconds to continue..."
	@sleep 3
	$(PROD_COMPOSE) exec redis redis-cli FLUSHALL
	@echo "Cache cleared!"

# Backup production database (saves to host filesystem)
prod-backup-db:
	@echo "Backing up production database..."
	@mkdir -p backups
	$(PROD_COMPOSE) exec -T postgres sh -c 'pg_dump -U $$POSTGRES_USER $$POSTGRES_DB' > backups/prod_backup_$$(date +%Y%m%d_%H%M%S).sql
	@echo "Backup saved to backups/"
	@ls -lh backups/prod_backup_*.sql | tail -1

# Restore production database from a backup file.
# Usage:   make prod-restore-db                     (uses newest backups/prod_backup_*.sql)
#          make prod-restore-db DUMP=backups/x.sql  (use a specific file)
# WARNING: Drops and recreates the prod DB before restore — destroys current state.
prod-restore-db:
	@echo "WARNING: Restoring prod DB will DROP all current data."
	@echo "Press Ctrl+C in 5s to cancel..."
	@sleep 5
	$(eval DUMP ?= $(shell ls -t backups/prod_backup_*.sql 2>/dev/null | head -1))
	@if [ -z "$(DUMP)" ] || [ ! -f "$(DUMP)" ]; then \
		echo "ERROR: no dump file found. Pass DUMP=path/to/file.sql or run prod-backup-db first."; \
		exit 1; \
	fi
	@echo "Restoring from $(DUMP)..."
	$(PROD_COMPOSE) stop backend frontend
	$(PROD_COMPOSE) exec -T postgres sh -c 'psql -U $$POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $$POSTGRES_DB;"'
	$(PROD_COMPOSE) exec -T postgres sh -c 'psql -U $$POSTGRES_USER -d postgres -c "CREATE DATABASE $$POSTGRES_DB OWNER $$POSTGRES_USER;"'
	$(PROD_COMPOSE) exec -T postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB' < $(DUMP)
	$(PROD_COMPOSE) start backend frontend
	@echo "Restore complete from $(DUMP). Backend + frontend restarted."

# Reset production database (DANGEROUS - requires confirmation)
prod-db-reset:
	@echo "WARNING: This will delete the production database!"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	@echo "Stopping backend to release DB connections..."
	$(PROD_COMPOSE) stop backend
	$(PROD_COMPOSE) exec postgres sh -c 'psql -U $$POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $$POSTGRES_DB;"'
	$(PROD_COMPOSE) exec postgres sh -c 'psql -U $$POSTGRES_USER -d postgres -c "CREATE DATABASE $$POSTGRES_DB OWNER $$POSTGRES_USER;"'
	@echo "Database reset. Rebuilding backend (entrypoint runs migrations)..."
	$(PROD_COMPOSE) up -d --build backend
	@echo "Database reset complete!"

# Run seed script on production
prod-seed:
	$(PROD_COMPOSE) exec backend python scripts/seed_data.py

# =============================================================================
# STAGING DEPLOYMENT (Git-based, EC2 via SSM)
# =============================================================================
# Deploy branch: origin/develop
# Workflow: staging-push (local) -> SSM into staging EC2 -> staging-deploy (on server)

STAGING_COMPOSE = docker compose -f docker-compose.staging.yml --env-file .env.staging

# Force push current branch to origin/develop (run from local machine)
staging-push:
	@echo "Force pushing current branch to origin/develop..."
	git push origin HEAD:develop --force
	@echo "Pushed to origin/develop. Now SSM into staging EC2 and run: make staging-deploy"

# Force pull from origin/develop (run on staging EC2 server)
staging-pull:
	@echo "Pulling from origin/develop..."
	git fetch origin
	git reset --hard origin/develop
	@echo "Updated to origin/develop"

# Start staging services
staging-up:
	$(STAGING_COMPOSE) up -d

# Stop staging services
staging-down:
	$(STAGING_COMPOSE) down

# Rebuild and restart staging (after pull)
staging-rebuild:
	$(STAGING_COMPOSE) up -d --build --force-recreate
	@echo "Waiting for services to stabilize..."
	@sleep 5
	@if ! $(STAGING_COMPOSE) exec -T nginx test -d /etc/letsencrypt/archive 2>/dev/null; then \
		echo ""; \
		echo "=============================================="; \
		echo "WARNING: No Let's Encrypt certificate found!"; \
		echo "Currently using self-signed certificate."; \
		echo "Run 'make staging-cert' to obtain a real certificate."; \
		echo "=============================================="; \
	else \
		echo "Let's Encrypt certificate found."; \
	fi

# Full deploy sequence (run on staging EC2 after SSM).
# `staging-prune-if-needed` runs between pull and rebuild: it's a no-op
# when disk is healthy, and self-heals when the build cache has bloated
# past 85% root-volume usage. This is the trade-off documented in
# CLAUDE.md — keep deploys fast in the common case, never fail on
# ENOSPC mid-build.
staging-deploy: staging-pull staging-prune-if-needed staging-rebuild
	@echo "Staging deployment complete!"

# Manual disk cleanup. Safe by construction:
#   - builder prune: drops build cache only (not images, not containers, not volumes)
#   - image prune: drops dangling images (NOT in use by running containers)
# Volumes are untouched, so postgres/redis/firmware data are safe.
# Run when you see `df -h /` getting tight or want a deliberate cleanup.
.PHONY: staging-prune
staging-prune:
	@echo "Pruning Docker build cache..."
	sudo docker builder prune -af
	@echo "Pruning dangling images..."
	sudo docker image prune -af
	@echo "Disk usage after prune:"
	@df -h / | tail -2

# Conditional version used by staging-deploy. Prunes only when root-volume
# usage exceeds 85%. The shell logic must be on one line (Make runs each
# recipe line in its own subshell) — kept readable via backslash continuations.
.PHONY: staging-prune-if-needed
staging-prune-if-needed:
	@USAGE=$$(df / | tail -1 | awk '{print $$5}' | tr -d %); \
	if [ "$$USAGE" -gt 85 ]; then \
		echo "Disk at $$USAGE%, pruning build cache + dangling images..."; \
		sudo docker builder prune -af; \
		sudo docker image prune -af; \
		df -h / | tail -2; \
	else \
		echo "Disk at $$USAGE%, no prune needed (threshold 85%)"; \
	fi

# Restart all services without rebuilding
staging-restart:
	# `up -d` re-reads --env-file and recreates containers whose config
	# changed (plain `docker compose restart` does NOT re-read env vars —
	# it just bounces the process inside the existing container).
	$(STAGING_COMPOSE) up -d

# Rebuild a single service (usage: make staging-rebuild-service SERVICE=backend)
staging-rebuild-service:
	$(STAGING_COMPOSE) up -d --build --force-recreate --no-deps $(SERVICE)

# Full clean rebuild (removes images, rebuilds from scratch)
staging-rebuild-clean:
	$(STAGING_COMPOSE) down --rmi local
	$(STAGING_COMPOSE) up -d --build

# Nuke everything including volumes (DANGEROUS - destroys DB data)
staging-nuke:
	@echo "WARNING: This will destroy ALL staging data including the database!"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	$(STAGING_COMPOSE) down -v --rmi local
	@echo "All staging containers, volumes, and images removed."

# View staging logs — last 100 lines + live tail.
# For full history pipe `$(STAGING_COMPOSE) logs > staging.log` (no -f) and grep.
staging-logs:
	$(STAGING_COMPOSE) logs --tail=100 -f

# View specific service logs — last 100 lines + live tail.
staging-logs-backend:
	$(STAGING_COMPOSE) logs --tail=100 -f backend

staging-logs-frontend:
	$(STAGING_COMPOSE) logs --tail=100 -f frontend

staging-logs-nginx:
	$(STAGING_COMPOSE) logs --tail=100 -f nginx

# Run migrations on staging
staging-migrate:
	$(STAGING_COMPOSE) exec backend aerich upgrade

# Open Python shell on staging backend
staging-shell:
	$(STAGING_COMPOSE) exec backend python -c "import IPython; IPython.start_ipython()" 2>/dev/null || \
	$(STAGING_COMPOSE) exec backend python

# Open bash on staging backend container
staging-bash:
	$(STAGING_COMPOSE) exec backend bash

# SSH into the staging EC2 instance via AWS SSM (no inbound SSH required)
staging-ssm:
	aws ssm start-session --target i-00fd9fb3c2b48932a --profile voltlync

# Show staging container status
staging-ps:
	$(STAGING_COMPOSE) ps

# Resource monitoring (single snapshot)
staging-stats:
	docker stats --no-stream

# Health check
staging-health:
	@curl -sf http://localhost/health && echo " Health check passed" || echo " Health check failed"

# Obtain/renew Let's Encrypt SSL certificate
staging-cert:
	@echo "Obtaining SSL certificate for staging..."
	@echo "Clearing any existing certificates..."
	$(STAGING_COMPOSE) run --rm --entrypoint "" certbot \
		sh -c "rm -rf /etc/letsencrypt/live/$${DOMAIN_NAME}* /etc/letsencrypt/renewal/$${DOMAIN_NAME}* /etc/letsencrypt/archive/$${DOMAIN_NAME}*"
	@echo "Requesting certificate from Let's Encrypt..."
	$(STAGING_COMPOSE) run --rm --entrypoint "" certbot \
		certbot certonly --webroot --webroot-path=/var/www/certbot \
		--email $${CERTBOT_EMAIL} --agree-tos --no-eff-email \
		-d $${DOMAIN_NAME}
	@echo "Restarting nginx to load new certificate..."
	$(STAGING_COMPOSE) restart nginx
	@echo "SSL certificate installed for staging!"

# Clear all Redis cache
staging-cache-clear:
	@echo "Clearing ALL Redis cache on staging..."
	$(STAGING_COMPOSE) exec redis redis-cli FLUSHALL
	@echo "Staging cache cleared!"

# Open a psql shell against the staging RDS instance.
# Reads connection params from the backend container's env so the secret
# doesn't have to leave .env.staging. Works equally for pre-cutover Docker
# postgres (DB_HOST=postgres) and post-cutover RDS.
staging-rds-shell:
	@if [ -z "$$($(STAGING_COMPOSE) ps -q backend)" ]; then \
		echo "ERROR: backend container not running. Run 'make staging-up' first."; \
		exit 1; \
	fi
	$(STAGING_COMPOSE) exec backend sh -c \
		'PGPASSWORD=$$DB_PASSWORD psql -h $$DB_HOST -p $$DB_PORT -U $$DB_USER -d $$DB_NAME'

# Backups: post-RDS-migration this is handled by RDS automated snapshots + PITR.
# Pre-migration this still wrote a pg_dump from Docker postgres to backups/.
# We keep the target name as a discoverability anchor but redirect the user
# to the new model instead of silently doing the wrong thing.
staging-backup-db:
	@echo "============================================================"
	@echo "Staging now uses RDS — automated backups are managed by AWS:"
	@echo "  - Daily automated snapshots (14-day retention)"
	@echo "  - Point-in-time recovery to any second in the window"
	@echo ""
	@echo "View snapshots:"
	@echo "  AWS Console -> RDS -> ocpp-staging-db -> Maintenance & backups"
	@echo "  aws rds describe-db-snapshots --profile voltlync \\"
	@echo "    --db-instance-identifier ocpp-staging-db"
	@echo ""
	@echo "Trigger an on-demand snapshot:"
	@echo "  aws rds create-db-snapshot --profile voltlync \\"
	@echo "    --db-instance-identifier ocpp-staging-db \\"
	@echo "    --db-snapshot-identifier ocpp-staging-manual-\$$(date +%Y%m%d-%H%M%S)"
	@echo ""
	@echo "For ad-hoc psql access:    make staging-rds-shell"
	@echo "============================================================"
	@exit 1

staging-restore-db:
	@echo "============================================================"
	@echo "Staging now uses RDS — restores go through the RDS console:"
	@echo "  - Point-in-time: AWS Console -> RDS -> ocpp-staging-db ->"
	@echo "                   Actions -> Restore to point in time"
	@echo "  - From snapshot: AWS Console -> RDS -> Snapshots ->"
	@echo "                   <snapshot> -> Actions -> Restore snapshot"
	@echo ""
	@echo "Either path creates a NEW RDS instance; you then either"
	@echo "swap DB_HOST in .env.staging or use the new endpoint directly."
	@echo "============================================================"
	@exit 1

# Reset staging database (DANGEROUS).
# Post-RDS-migration this targets the RDS instance, not a Docker volume.
# Requires typing the exact phrase to confirm — no muscle-memory drops.
staging-db-reset:
	@HOST=$$(grep -E '^DB_HOST=' .env.staging | cut -d= -f2); \
	echo "==========================================================="; \
	echo "WARNING: This will DROP and recreate the staging database."; \
	echo "Target host: $$HOST"; \
	echo ""; \
	echo "If the host above is an RDS endpoint, this destroys data"; \
	echo "that RDS automated backups can still recover, but it WILL"; \
	echo "take staging down until migrations re-run."; \
	echo ""; \
	echo "Type 'reset staging db' to confirm, anything else aborts:"; \
	echo "==========================================================="; \
	read confirm; [ "$$confirm" = "reset staging db" ] || (echo "Aborted."; exit 1)
	@echo "Stopping backend to release DB connections..."
	$(STAGING_COMPOSE) stop backend
	$(STAGING_COMPOSE) exec backend sh -c \
		'PGPASSWORD=$$DB_PASSWORD psql -h $$DB_HOST -p $$DB_PORT -U $$DB_USER -d postgres \
		 -c "DROP DATABASE IF EXISTS $$DB_NAME; CREATE DATABASE $$DB_NAME OWNER $$DB_USER;"' \
		2>/dev/null || true
	@echo "Database reset. Rebuilding backend (entrypoint runs migrations)..."
	$(STAGING_COMPOSE) up -d --build backend
	@echo "Staging database reset complete!"

# Run seed script on staging
staging-seed:
	$(STAGING_COMPOSE) exec backend python scripts/seed_data.py

# ===========================================
# Docker Commands
# ===========================================

# Start development environment with hot-reload
docker-dev:
	@echo "🐳 Starting development environment..."
	docker compose up --build

# Start development environment (detached)
docker-dev-detach:
	@echo "🐳 Starting development environment (detached)..."
	docker compose up --build -d
	@echo "✅ Development environment started!"
	@echo "   Frontend: http://localhost:3000"
	@echo "   Backend:  http://localhost:8000"
	@echo "   API Docs: http://localhost:8000/docs"

# Start production environment
docker-prod:
	@echo "🐳 Starting production environment..."
	docker compose -f docker-compose.prod.yml up --build

# Start production environment (detached)
docker-prod-detach:
	@echo "🐳 Starting production environment (detached)..."
	docker compose -f docker-compose.prod.yml up --build -d
	@echo "✅ Production environment started!"

# Stop development containers
docker-down:
	@echo "🛑 Stopping development containers..."
	docker compose down
	@echo "✅ Development containers stopped!"

# Stop production containers
docker-down-prod:
	@echo "🛑 Stopping production containers..."
	docker compose -f docker-compose.prod.yml down
	@echo "✅ Production containers stopped!"

# Follow all container logs
docker-logs:
	docker compose logs -f

# Follow backend logs
docker-logs-backend:
	docker compose logs -f backend

# Follow frontend logs
docker-logs-frontend:
	docker compose logs -f frontend

# Build development images
docker-build:
	@echo "🔨 Building development images..."
	docker compose build

# Build production images
docker-build-prod:
	@echo "🔨 Building production images..."
	docker compose -f docker-compose.prod.yml build

# Remove containers, volumes, and images
docker-clean:
	@echo "🧹 Cleaning up Docker resources..."
	docker compose down -v --rmi local
	docker compose -f docker-compose.prod.yml down -v --rmi local 2>/dev/null || true
	docker system prune -f
	@echo "✅ Docker cleanup complete!"

# Run database migrations in Docker
docker-migrate:
	@echo "🔄 Running database migrations in Docker..."
	docker compose exec backend aerich upgrade
	@echo "✅ Migrations complete!"

# Initialize fresh database in Docker
docker-init-db:
	@echo "🔄 Initializing fresh database in Docker..."
	docker compose exec backend aerich init-db
	@echo "✅ Database initialized!"

# Run seed orchestrator in Docker (alias for `seed`, kept for docs compatibility)
docker-seed: seed
	@echo "✅ Database seeded!"

# Run Docker-specific seed orchestrator (supports CLERK_ADMIN_ID + ADMIN_EMAIL)
# Usage: make docker-seed-dev CLERK_ADMIN_ID=user_xxxxx ADMIN_EMAIL=you@example.com
docker-seed-dev:
	@echo "🌱 Seeding Docker database for development..."
	@if [ -n "$(CLERK_ADMIN_ID)" ]; then \
		echo "📌 Using CLERK_ADMIN_ID: $(CLERK_ADMIN_ID)"; \
	else \
		echo "💡 Tip: Run with CLERK_ADMIN_ID=your_id to seed yourself as admin"; \
	fi
	@docker compose exec \
		-e CLERK_ADMIN_ID=$(CLERK_ADMIN_ID) \
		-e ADMIN_EMAIL=$(ADMIN_EMAIL) \
		-e CLERK_USER_ID=$(CLERK_USER_ID) \
		-e USER_EMAIL=$(USER_EMAIL) \
		backend python scripts/seed_all.py

# Reset Docker database completely (WARNING: destroys all data)
docker-db-reset:
	@echo "⚠️  WARNING: This will destroy ALL Docker database data!"
	@echo "   Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	@echo "🗑️  Stopping and removing containers with volumes..."
	docker compose down -v
	@echo "🔄 Starting fresh database..."
	docker compose up -d postgres redis
	@echo "⏳ Waiting for database to be ready (10s)..."
	@sleep 10
	@echo "🔄 Starting backend (will auto-create tables)..."
	docker compose up -d backend
	@echo "⏳ Waiting for backend to initialize (15s)..."
	@sleep 15
	@echo "🔄 Starting remaining services..."
	docker compose up -d
	@echo ""
	@echo "✅ Docker database reset complete!"
	@echo ""
	@echo "📋 Next steps:"
	@echo "   1. Get your Clerk User ID from browser DevTools or Clerk Dashboard"
	@echo "   2. Run: make docker-seed-dev CLERK_ADMIN_ID=user_xxxxx"
	@echo "   3. Refresh your browser"

# ===========================================
# Staging Docker Commands
# ===========================================

# Start staging environment
docker-staging:
	@echo "🐳 Starting staging environment..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging up --build

# Start staging environment (detached)
docker-staging-detach:
	@echo "🐳 Starting staging environment (detached)..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging up --build -d
	@echo "✅ Staging environment started!"
	@echo "   URL: https://$${DOMAIN_NAME}"

# Stop staging containers
docker-down-staging:
	@echo "🛑 Stopping staging containers..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging down
	@echo "✅ Staging containers stopped!"

# Build staging images
docker-build-staging:
	@echo "🔨 Building staging images..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging build

# Run migrations in staging
docker-staging-migrate:
	@echo "🔄 Running migrations in staging..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging exec backend aerich upgrade
	@echo "✅ Staging migrations complete!"

# ===========================================
# SSL Certificate Commands
# ===========================================

# Obtain SSL certificate for staging
docker-staging-cert:
	@echo "🔐 Obtaining SSL certificate for staging..."
	@echo "   Make sure DOMAIN_NAME and CERTBOT_EMAIL are set in .env.staging"
	docker compose -f docker-compose.staging.yml --env-file .env.staging exec certbot \
		certbot certonly --webroot --webroot-path=/var/www/certbot \
		--email $${CERTBOT_EMAIL} --agree-tos --no-eff-email \
		-d $${DOMAIN_NAME}
	@echo "🔄 Restarting nginx to load new certificate..."
	docker compose -f docker-compose.staging.yml --env-file .env.staging restart nginx
	@echo "✅ SSL certificate obtained for staging!"

# Obtain SSL certificate for production
docker-prod-cert:
	@echo "🔐 Obtaining SSL certificate for production..."
	@echo "   Make sure DOMAIN_NAME and CERTBOT_EMAIL are set in .env.prod"
	docker compose -f docker-compose.prod.yml --env-file .env.prod exec certbot \
		certbot certonly --webroot --webroot-path=/var/www/certbot \
		--email $${CERTBOT_EMAIL} --agree-tos --no-eff-email \
		-d $${DOMAIN_NAME}
	@echo "🔄 Restarting nginx to load new certificate..."
	docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx
	@echo "✅ SSL certificate obtained for production!"

# Force certificate renewal (for staging or prod)
docker-cert-renew:
	@echo "🔄 Forcing certificate renewal..."
	@if [ -f .env.staging ]; then \
		docker compose -f docker-compose.staging.yml --env-file .env.staging exec certbot certbot renew --force-renewal; \
		docker compose -f docker-compose.staging.yml --env-file .env.staging restart nginx; \
	elif [ -f .env.prod ]; then \
		docker compose -f docker-compose.prod.yml --env-file .env.prod exec certbot certbot renew --force-renewal; \
		docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx; \
	else \
		echo "❌ No .env.staging or .env.prod file found!"; \
		exit 1; \
	fi
	@echo "✅ Certificate renewal complete!"

# View certificate status
docker-cert-status:
	@echo "📜 Certificate status..."
	@if [ -f .env.staging ]; then \
		docker compose -f docker-compose.staging.yml --env-file .env.staging exec certbot certbot certificates; \
	elif [ -f .env.prod ]; then \
		docker compose -f docker-compose.prod.yml --env-file .env.prod exec certbot certbot certificates; \
	else \
		echo "❌ No .env.staging or .env.prod file found!"; \
	fi

# ===========================================
# Production Docker Commands (updated)
# ===========================================

# Start production environment with env file
docker-prod-env:
	@echo "🐳 Starting production environment..."
	docker compose -f docker-compose.prod.yml --env-file .env.prod up --build

# Start production environment detached with env file
docker-prod-env-detach:
	@echo "🐳 Starting production environment (detached)..."
	docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d
	@echo "✅ Production environment started!"

# Run migrations in production
docker-prod-migrate:
	@echo "🔄 Running migrations in production..."
	docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend aerich upgrade
	@echo "✅ Production migrations complete!"