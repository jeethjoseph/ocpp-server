# OCPP Server Makefile for Database Management

# Database configuration - load from .env file
include backend/.env
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

.PHONY: help db-reset db-reset-cloud db-first-time db-drop-user db-create-user db-drop db-create migrate seed setup-dev truncate-tables deploy-dry-run deploy deploy-force restart-service docker-dev docker-dev-detach docker-staging docker-staging-detach docker-prod docker-prod-detach docker-down docker-down-staging docker-down-prod docker-logs docker-logs-backend docker-logs-frontend docker-build docker-build-staging docker-build-prod docker-clean docker-migrate docker-staging-cert docker-prod-cert docker-cert-renew

help:
	@echo "Available commands:"
	@echo ""
	@echo "Docker Commands - Development:"
	@echo "  docker-dev         - Start development environment with hot-reload"
	@echo "  docker-dev-detach  - Start development environment (detached)"
	@echo "  docker-down        - Stop development containers"
	@echo "  docker-build       - Build development images"
	@echo ""
	@echo "Docker Commands - Staging:"
	@echo "  docker-staging         - Start staging environment"
	@echo "  docker-staging-detach  - Start staging environment (detached)"
	@echo "  docker-down-staging    - Stop staging containers"
	@echo "  docker-build-staging   - Build staging images"
	@echo "  docker-staging-cert    - Obtain SSL certificate for staging"
	@echo ""
	@echo "Docker Commands - Production:"
	@echo "  docker-prod         - Start production environment"
	@echo "  docker-prod-detach  - Start production environment (detached)"
	@echo "  docker-down-prod    - Stop production containers"
	@echo "  docker-build-prod   - Build production images"
	@echo "  docker-prod-cert    - Obtain SSL certificate for production"
	@echo ""
	@echo "Docker Commands - Common:"
	@echo "  docker-logs          - Follow all container logs"
	@echo "  docker-logs-backend  - Follow backend logs"
	@echo "  docker-logs-frontend - Follow frontend logs"
	@echo "  docker-migrate       - Run database migrations in Docker"
	@echo "  docker-clean         - Remove containers, volumes, and images"
	@echo "  docker-cert-renew    - Force SSL certificate renewal"
	@echo ""
	@echo "Database Management:"
	@echo "  db-reset        - Database reset (drop, recreate, migrate, seed)"
	@echo "  db-reset-cloud  - Cloud database reset (truncate tables, migrate, seed)"
	@echo "  db-first-time   - First-time setup (drop, recreate, init-db, seed)"
	@echo "  db-drop-user    - Drop database user"
	@echo "  db-create-user  - Create database user"
	@echo "  db-drop         - Drop database"
	@echo "  db-create       - Create database"
	@echo "  init-fresh-db   - Initialize fresh database with schema"
	@echo "  migrate         - Run database migrations (for existing DB)"
	@echo "  seed            - Run seed script"
	@echo "  setup-dev       - Initial development setup"
	@echo ""
	@echo "Deployment:"
	@echo "  deploy-dry-run  - Show what would be deployed (no changes)"
	@echo "  deploy          - Deploy to production (with confirmation)"
	@echo "  deploy-force    - Deploy without confirmation (use with caution!)"
	@echo "  restart-service - Restart the production service"

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

# Run seed script
seed:
	@echo "🌱 Seeding database..."
	cd $(BACKEND_DIR) && source .venv/bin/activate && python scripts/seed_data.py

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

# Deployment configuration
REMOTE_USER=root
REMOTE_HOST=lyncpower.com
REMOTE_PATH=/root/ocpp_server/
LOCAL_PATH=./backend/
SERVICE_NAME=ocpp-server

# Common rsync exclusions
RSYNC_EXCLUDES=--exclude '.git/' \
	--exclude '.gitignore' \
	--exclude '__pycache__/' \
	--exclude '*.pyc' \
	--exclude '*.pyo' \
	--exclude '*.py[cod]' \
	--exclude '.env' \
	--exclude '.env.local' \
	--exclude '.env.production' \
	--exclude '.env.staging' \
	--exclude '.env.example' \
	--exclude '.venv/' \
	--exclude 'venv/' \
	--exclude 'env/' \
	--exclude '.idea/' \
	--exclude '.vscode/' \
	--exclude 'test.html' \
	--exclude 'dump.rdb' \
	--exclude '.claude/' \
	--exclude '*.sql' \
	--exclude '*.dump' \
	--exclude '*.log' \
	--exclude 'logs/' \
	--exclude 'docs/' \
	--exclude 'firmware_files/' \
	--exclude 'node_modules/' \
	--exclude 'npm-debug.log' \
	--exclude 'yarn-debug.log' \
	--exclude 'yarn-error.log' \
	--exclude '.next/' \
	--exclude 'out/' \
	--exclude 'dist/' \
	--exclude 'build/' \
	--exclude '.DS_Store' \
	--exclude '._*' \
	--exclude 'certs/' \
	--exclude 'app/' \
	--exclude 'frontend/'

# Deployment dry run (shows what would be transferred)
deploy-dry-run:
	@echo "🔍 Running deployment dry-run to $(REMOTE_USER)@$(REMOTE_HOST)..."
	@echo "   This will show what files would be transferred/deleted"
	@echo ""
	rsync -avzn --delete $(RSYNC_EXCLUDES) $(LOCAL_PATH) $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PATH)
	@echo ""
	@echo "✅ Dry-run complete. Review the changes above."

# Full deployment (with confirmation)
deploy: deploy-dry-run
	@echo ""
	@echo "⚠️  Ready to deploy to production!"
	@read -p "Do you want to proceed with deployment? (yes/no): " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		echo "🚀 Starting deployment..."; \
		rsync -avz --delete $(RSYNC_EXCLUDES) $(LOCAL_PATH) $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PATH); \
		if [ $$? -eq 0 ]; then \
			echo "✅ Files deployed successfully!"; \
			echo "🔄 Restarting service $(SERVICE_NAME)..."; \
			ssh $(REMOTE_USER)@$(REMOTE_HOST) "systemctl restart $(SERVICE_NAME) && systemctl status $(SERVICE_NAME) --no-pager"; \
			if [ $$? -eq 0 ]; then \
				echo "✅ Service restarted successfully!"; \
				echo "✅ Deployment complete!"; \
			else \
				echo "⚠️  Service restart failed! Check logs with: ssh $(REMOTE_USER)@$(REMOTE_HOST) 'systemctl status $(SERVICE_NAME)'"; \
				exit 1; \
			fi \
		else \
			echo "❌ Deployment failed!"; \
			exit 1; \
		fi \
	else \
		echo "❌ Deployment cancelled."; \
		exit 1; \
	fi

# Quick deploy (no confirmation - use with caution!)
deploy-force:
	@echo "🚀 Deploying to $(REMOTE_USER)@$(REMOTE_HOST) (no confirmation)..."
	rsync -avz --delete $(RSYNC_EXCLUDES) $(LOCAL_PATH) $(REMOTE_USER)@$(REMOTE_HOST):$(REMOTE_PATH)
	@echo "✅ Files deployed successfully!"
	@echo "🔄 Restarting service $(SERVICE_NAME)..."
	@ssh $(REMOTE_USER)@$(REMOTE_HOST) "systemctl restart $(SERVICE_NAME) && systemctl status $(SERVICE_NAME) --no-pager"
	@echo "✅ Deployment complete!"

# Restart the production service
restart-service:
	@echo "🔄 Restarting service $(SERVICE_NAME) on $(REMOTE_HOST)..."
	@ssh $(REMOTE_USER)@$(REMOTE_HOST) "systemctl restart $(SERVICE_NAME) && systemctl status $(SERVICE_NAME) --no-pager"
	@echo "✅ Service restarted!"

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

# Run seed script in Docker
docker-seed:
	@echo "🌱 Seeding database in Docker..."
	docker compose exec backend python scripts/seed_data.py
	@echo "✅ Database seeded!"

# Run Docker-specific seed script (supports CLERK_ADMIN_ID)
# Usage: make docker-seed-dev CLERK_ADMIN_ID=user_xxxxx
docker-seed-dev:
	@echo "🌱 Seeding Docker database for development..."
	@if [ -n "$(CLERK_ADMIN_ID)" ]; then \
		echo "📌 Using CLERK_ADMIN_ID: $(CLERK_ADMIN_ID)"; \
		docker compose exec -e CLERK_ADMIN_ID=$(CLERK_ADMIN_ID) backend python scripts/seed_docker.py; \
	else \
		echo "💡 Tip: Run with CLERK_ADMIN_ID=your_id to seed yourself as admin"; \
		docker compose exec backend python scripts/seed_docker.py; \
	fi

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