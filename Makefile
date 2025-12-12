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

.PHONY: help db-reset db-reset-cloud db-first-time db-drop-user db-create-user db-drop db-create migrate seed setup-dev truncate-tables deploy-dry-run deploy deploy-force restart-service

help:
	@echo "Available commands:"
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
	--exclude 'firmware_files/*.bin' \
	--exclude 'firmware_files/*.hex' \
	--exclude 'firmware_files/*.fw' \
	--exclude 'backend/firmware_files/*.bin' \
	--exclude 'backend/firmware_files/*.hex' \
	--exclude 'backend/firmware_files/*.fw' \
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