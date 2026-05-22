#!/bin/bash
# Docker entrypoint script for OCPP Backend
# Runs database migrations before starting the application

set -e

# ---------------------------------------------------------------------------
# Privilege drop: if we start as root (production image has no USER
# directive), fix ownership on the firmware volume and re-exec as the app
# user via gosu. Named volumes mounted at /app/firmware_files may have been
# seeded with root ownership from an older image, which would otherwise
# block firmware uploads with EACCES.
#
# DO NOT add logic above this block without thinking about the security
# implication — anything here runs as root.
# ---------------------------------------------------------------------------
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/firmware_files
    chown -R app:app /app/firmware_files
    exec gosu app "$0" "$@"
fi

echo "=========================================="
echo "OCPP Backend - Docker Entrypoint"
echo "=========================================="
echo "Environment: ${ENVIRONMENT:-development}"
echo "Database: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
echo ""

# Wait for database to be ready
echo "Waiting for database..."
MAX_RETRIES=30
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if python3 -c "
import asyncio
import asyncpg
import os

async def check_db():
    try:
        conn = await asyncpg.connect(
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', 5432)),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            ssl='disable'
        )
        await conn.close()
        return True
    except Exception as e:
        return False

exit(0 if asyncio.run(check_db()) else 1)
" 2>/dev/null; then
        echo "Database is ready!"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Waiting for database... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "ERROR: Could not connect to database after $MAX_RETRIES attempts"
    exit 1
fi

# Run Aerich migrations
echo ""
echo "Running database migrations..."
echo "------------------------------------------"

# Try aerich upgrade — it handles both fresh and existing databases
aerich upgrade
echo "Migrations completed successfully."

echo "------------------------------------------"
echo ""

# Start the application
echo "Starting OCPP Backend..."
echo ""

# Workers default to 1 because in-memory OCPP connection state (WebSocket
# sessions, pending call maps) is not shared across uvicorn workers.
# Check if New Relic is enabled
if [ "$NEW_RELIC_MONITOR_MODE" = "true" ]; then
    echo "Starting with New Relic APM..."
    exec newrelic-admin run-program uvicorn main:app \
        --host 0.0.0.0 \
        --port ${PORT:-8000} \
        --workers ${WORKERS:-1} \
        --ws-ping-interval 20 \
        --ws-ping-timeout 20 \
        --log-level ${LOG_LEVEL:-info}
else
    echo "Starting without New Relic..."
    exec uvicorn main:app \
        --host 0.0.0.0 \
        --port ${PORT:-8000} \
        --workers ${WORKERS:-1} \
        --ws-ping-interval 20 \
        --ws-ping-timeout 20 \
        --log-level ${LOG_LEVEL:-info}
fi
