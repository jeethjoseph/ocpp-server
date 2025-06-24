# OCPP Server Testing

This directory contains all tests for the OCPP server, organized by type and purpose.

## Test Structure

```
tests/
├── README.md                 # This file
├── conftest.py              # Shared test fixtures and configuration
├── test_infrastructure.py   # Redis, database connectivity tests
├── test_chargers.py         # Charger API unit tests
├── test_stations.py         # Station API unit tests
└── test_integration.py      # WebSocket integration tests
```

## Test Categories

### 1. Infrastructure Tests (`test_infrastructure.py`)
- Tests Redis connectivity and basic operations
- Tests database connectivity
- Tests Redis manager functionality
- **Requirements**: Redis and database must be available

### 2. Unit Tests (`test_chargers.py`, `test_stations.py`)
- Tests API endpoints with mocked dependencies
- Uses test database for data operations
- Mocks Redis for connection status
- **Requirements**: Test database only

### 3. Integration Tests (`test_integration.py`)
- Tests real OCPP WebSocket connections
- Tests end-to-end functionality
- **Requirements**: Server running at localhost:8000 + test data

## Quick Start

### Setup Test Environment
```bash
# Setup test environment (creates test data, checks infrastructure)
python scripts/setup_test_environment.py

# Run all tests
python scripts/run_tests.py --setup --all

# Run specific test categories
python scripts/run_tests.py --unit
python scripts/run_tests.py --infrastructure  
python scripts/run_tests.py --integration  # Requires running server
```

### Manual Testing
```bash
# Infrastructure tests (check Redis/DB)
pytest tests/test_infrastructure.py -v

# Unit tests (API testing with mocks)
pytest tests/test_chargers.py tests/test_stations.py -v

# Integration tests (requires server running)
fastapi dev main.py  # In another terminal
pytest tests/test_integration.py -v
```

## Prerequisites

### For All Tests
- Python environment with all dependencies installed
- Test database configured (see `conftest.py`)

### For Infrastructure Tests
- Redis server running locally (`redis-server`)
- Database accessible with credentials in `.env`

### For Integration Tests
- OCPP server running at `localhost:8000`
- Integration test chargers created (handled by setup script)

## Test Data

The setup script automatically creates test chargers with specific IDs that integration tests expect:
- `test-cp-2` - Used for basic connection tests
- `cp-1`, `cp-2`, `cp-3` - Used for multiple connection tests  
- `test-cp-boot` - Used for boot notification tests

## Troubleshooting

### Redis Not Available
```bash
# macOS
brew install redis
brew services start redis

# Ubuntu  
sudo apt-get install redis-server

# Docker
docker run -d -p 6379:6379 redis:alpine
```

### Database Connection Issues
- Check `.env` file for correct database credentials
- Ensure database exists and is accessible
- Run `python scripts/setup_test_environment.py` to verify

### Integration Test Failures
- Ensure server is running: `fastapi dev main.py`
- Verify test chargers exist: `python scripts/setup_test_environment.py`
- Check server logs for WebSocket connection errors