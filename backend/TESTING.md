# Testing Guide

This project uses **pytest natively** for all testing. No custom scripts required!

## Quick Start

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_integration.py

# Run specific test
pytest tests/test_integration.py::TestOCPPSuccessCycle::test_ocpp_core_functionality
```

## Test Categories

Tests are organized with **pytest markers** for easy filtering:

### 🚀 Unit Tests (Fast)
```bash
# API unit tests with mocked dependencies
pytest -m unit
```
- **Duration**: ~1 second
- **Dependencies**: None (mocked)
- **Coverage**: API endpoints, business logic

### 🔗 Integration Tests (Requires Server)
```bash
# OCPP WebSocket integration tests  
pytest -m integration
```
- **Duration**: ~45 seconds
- **Dependencies**: Server running at localhost:8000
- **Coverage**: Complete OCPP 1.6 functionality

### 🏗️ Infrastructure Tests (Requires Services)
```bash
# Redis and database connectivity tests
pytest -m infrastructure  
```
- **Duration**: ~5 seconds
- **Dependencies**: Redis + PostgreSQL
- **Coverage**: Database, Redis, connections

### 🐌 Slow Tests
```bash
# Tests that take >30 seconds
pytest -m slow
```

## Advanced Usage

### Exclude Categories
```bash
# Run everything except slow tests
pytest -m "not slow"

# Run unit tests only (fastest)
pytest -m "unit"

# Run everything except infrastructure
pytest -m "not infrastructure"
```

### Parallel Execution
```bash
# Install pytest-xdist for parallel testing
pip install pytest-xdist

# Run tests in parallel
pytest -n auto
```

### Coverage Reports
```bash
# Generate coverage report
pytest --cov=. --cov-report=html

# View coverage
open htmlcov/index.html
```

### Output Control
```bash
# Short output format
pytest --tb=short

# Hide warnings
pytest --disable-warnings

# Show all output (including print statements)
pytest -s

# Stop on first failure
pytest -x
```

## Real-World OCPP Testing

For **complete OCPP simulation** with real timing and remote commands:

```bash
# Start the OCPP simulator
python ocpp_simulator.py --charger-id f87a48bc-532e-4aed-862c-c6846dd278f9

# Features:
# ✅ Real 45-second heartbeat intervals
# ✅ Waits for remote start/stop commands
# ✅ 30-second meter value intervals  
# ✅ Complete status cycle simulation
# ✅ Database integration
```

## Pre-Test Setup

### 1. Start Server (for integration tests)
```bash
python main.py
# or
fastapi dev main.py
```

### 2. Setup Test Database
```bash
# Ensure test database exists
createdb test_ocpp_db

# Run migrations
aerich upgrade
```

### 3. Setup Redis (for infrastructure tests)
```bash
# Start Redis server
redis-server

# Or with Docker
docker run -d --name redis -p 6379:6379 redis:alpine
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── test_stations.py         # @pytest.mark.unit - Station API tests
├── test_chargers.py         # @pytest.mark.unit - Charger API tests  
├── test_infrastructure.py   # @pytest.mark.infrastructure - Redis/DB tests
└── test_integration.py      # @pytest.mark.integration - OCPP WebSocket tests
```

## Example Test Commands

```bash
# Quick unit test run (1 second)
pytest -m unit --tb=short

# Full integration test suite (requires server)
pytest -m integration -v

# Test specific OCPP functionality  
pytest tests/test_integration.py::TestOCPPSuccessCycle::test_ocpp_core_functionality -s

# Run all tests except slow ones
pytest -m "not slow" --tb=short

# Generate coverage report for unit tests only
pytest -m unit --cov=. --cov-report=term-missing
```

## Helpful Scripts

### Environment Setup
```bash
# Setup test environment (creates test chargers, checks Redis/DB)
python scripts/setup_test_environment.py
```

### Watch and Test
```bash
# Watch files and run tests automatically
python watch_and_test.py --type unit
python watch_and_test.py --type integration
python watch_and_test.py --type all
```

## Continuous Integration

For CI/CD pipelines:

```bash
# Fast feedback (unit tests only)
pytest -m unit --tb=short --disable-warnings

# Full test suite (requires services)
pytest --tb=short --disable-warnings
```

## Troubleshooting

### Import Errors
- **Solution**: Run pytest from the `backend/` directory
- **Root cause**: Module imports expect to be run from project root

### Server Connection Errors
- **Issue**: Integration tests fail with connection errors
- **Solution**: Start the server with `python main.py` before running integration tests

### Database Errors
- **Issue**: Tests fail with database connection errors
- **Solution**: Ensure test database exists and is accessible

### Redis Errors
- **Issue**: Infrastructure tests fail
- **Solution**: Start Redis server before running infrastructure tests

---

**✨ Native pytest is much better than custom test scripts!** 🚀