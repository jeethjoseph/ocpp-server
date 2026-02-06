#!/bin/bash
# Wrapper script to conditionally start OCPP server with or without New Relic monitoring
# This script is called by the systemd service

set -e

# Load environment variables from .env file if it exists
if [ -f /root/ocpp_server/.env ]; then
    set -a  # automatically export all variables
    source /root/ocpp_server/.env
    set +a
fi

# Get configuration from environment variables with defaults
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
WORKERS="${WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"
UVICORN_PATH="/root/ocpp_server/.venv/bin/uvicorn"

# Check if New Relic monitoring is enabled
if [ "$NEW_RELIC_MONITOR_MODE" = "true" ]; then
    echo "🚀 Starting OCPP Server with New Relic APM instrumentation..."
    echo "   App Name: ${NEW_RELIC_APP_NAME:-OCPP-Server}"
    echo "   Environment: ${ENVIRONMENT:-production}"
    echo "   Distributed Tracing: ${NEW_RELIC_DISTRIBUTED_TRACING_ENABLED:-true}"

    # Start with newrelic-admin wrapper for automatic instrumentation
    /root/ocpp_server/.venv/bin/newrelic-admin run-program \
        $UVICORN_PATH main:app \
        --host $HOST \
        --port $PORT \
        --workers $WORKERS \
        --log-level $LOG_LEVEL
else
    echo "🚀 Starting OCPP Server (New Relic monitoring disabled)..."
    echo "   To enable monitoring: Set NEW_RELIC_MONITOR_MODE=true in .env"

    # Start without New Relic
    $UVICORN_PATH main:app \
        --host $HOST \
        --port $PORT \
        --workers $WORKERS \
        --log-level $LOG_LEVEL
fi
