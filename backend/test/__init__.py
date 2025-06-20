# tests/__init__.py
"""
Integration tests for OCPP Central System API

Test Structure:
- test_stations.py: Station management endpoint tests
- test_chargers.py: Charger management endpoint tests
- conftest.py: Shared fixtures and configuration

Run all tests: pytest tests/ -v
Run specific test file: pytest tests/test_stations.py -v
Run with coverage: pytest tests/ --cov=routers --cov-report=html
"""