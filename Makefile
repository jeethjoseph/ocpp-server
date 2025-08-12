# OCPP Server Makefile for Database Management

# Database configuration
DB_HOST=localhost
DB_PORT=5432
DB_USER=ocpp_user
DB_PASSWORD=ocpp_password
DB_NAME=ocpp_db
PG_SUPERUSER=$(shell whoami)

# Directories
BACKEND_DIR=backend
SCRIPTS_DIR=$(BACKEND_DIR)/scripts

.PHONY: help db-reset db-drop-user db-create-user db-drop db-create migrate seed setup-dev

help:
	@echo "Available commands:"
	@echo "  help          - Show this help message"
	@echo "  db-reset      - Complete database reset (drop, recreate, init schema, seed)"
	@echo "  db-drop-user  - Drop database user"
	@echo "  db-create-user- Create database user"
	@echo "  db-drop       - Drop database"
	@echo "  db-create     - Create database"
	@echo "  init-fresh-db - Initialize fresh database with schema"
	@echo "  migrate       - Run database migrations (for existing DB)"
	@echo "  seed          - Run seed script"
	@echo "  setup-dev     - Initial development setup"

# Complete database reset
db-reset: db-drop db-drop-user db-create-user db-create init-fresh-db seed
	@echo "✅ Database reset complete!"

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