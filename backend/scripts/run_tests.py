#!/usr/bin/env python3
"""
Unified test runner script
"""

import subprocess
import sys
import argparse
from pathlib import Path

def run_command(cmd, description):
    """Run a command and return success status"""
    print(f"\n🔄 {description}")
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Success")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed with exit code {e.returncode}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Run OCPP server tests")
    parser.add_argument("--setup", action="store_true", help="Setup test environment first")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only") 
    parser.add_argument("--infrastructure", action="store_true", help="Run infrastructure tests only")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    # Change to backend directory
    backend_dir = Path(__file__).parent.parent
    print(f"Working directory: {backend_dir}")
    
    # Setup environment if requested
    if args.setup:
        setup_cmd = [sys.executable, "scripts/setup_test_environment.py"]
        run_command(setup_cmd, "Setting up test environment")
    
    # Build pytest command
    pytest_args = ["python", "-m", "pytest"]
    if args.verbose:
        pytest_args.append("-v")
    
    success = True
    
    # Run specific test categories
    if args.infrastructure or args.all:
        cmd = pytest_args + ["tests/test_infrastructure.py"]
        success &= run_command(cmd, "Running infrastructure tests")
    
    if args.unit or args.all:
        cmd = pytest_args + ["tests/test_chargers.py", "tests/test_stations.py"]
        success &= run_command(cmd, "Running unit tests")
    
    if args.integration or args.all:
        print("\n⚠️  Integration tests require the server to be running at localhost:8000")
        print("   Start server with: fastapi dev main.py")
        cmd = pytest_args + ["tests/test_integration.py"]
        success &= run_command(cmd, "Running integration tests")
    
    # If no specific category chosen, show help
    if not any([args.unit, args.integration, args.infrastructure, args.all]):
        print("\n📋 Available test categories:")
        print("   --infrastructure : Test Redis and database connectivity")
        print("   --unit          : Test API endpoints with mocked dependencies")
        print("   --integration   : Test real WebSocket connections (requires running server)")
        print("   --all           : Run all test categories")
        print("   --setup         : Setup test environment first")
        print("\nExample usage:")
        print("   python scripts/run_tests.py --setup --all")
        print("   python scripts/run_tests.py --unit --verbose")
        return
    
    if success:
        print("\n🎉 All tests completed successfully!")
    else:
        print("\n❌ Some tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()