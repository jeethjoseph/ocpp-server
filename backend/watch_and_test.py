#!/usr/bin/env python3
"""
Watch for file changes and run tests automatically
Updated to work with new streamlined test structure
"""

import time
import subprocess
import sys
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

class TestRunner:
    def __init__(self, test_type="unit"):
        self.test_type = test_type
        self.last_run = 0
        self.debounce_seconds = 2  # Avoid running tests too frequently

    def run_tests(self, event_path=None):
        """Run tests based on configuration"""
        current_time = time.time()
        if current_time - self.last_run < self.debounce_seconds:
            return
        
        self.last_run = current_time
        
        if event_path:
            print(f"📁 Change detected: {event_path}")
        
        # Choose test command based on what changed and test type (using native pytest)
        if self.test_type == "unit":
            cmd = ["pytest", "-m", "unit", "--tb=short", "-q"]
            print("🧪 Running unit tests...")
        elif self.test_type == "all":
            cmd = ["pytest", "--tb=short", "-q"]
            print("🔄 Running all tests...")
        elif self.test_type == "infrastructure":
            cmd = ["pytest", "-m", "infrastructure", "--tb=short", "-q"]
            print("🏗️  Running infrastructure tests...")
        elif self.test_type == "integration":
            cmd = ["pytest", "-m", "integration", "--tb=short", "-q"]
            print("🔗 Running integration tests...")
        else:
            # Default to unit tests (fastest)
            cmd = ["pytest", "-m", "unit", "--tb=short", "-q"]
            print("🧪 Running unit tests...")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print("✅ Tests passed!")
            else:
                print("❌ Tests failed!")
                if result.stdout:
                    print("STDOUT:", result.stdout[-500:])  # Last 500 chars
                if result.stderr:
                    print("STDERR:", result.stderr[-500:])
        except subprocess.TimeoutExpired:
            print("⏰ Tests timed out after 2 minutes")
        except Exception as e:
            print(f"❌ Error running tests: {e}")

def on_change(event, test_runner):
    """Handle file change events"""
    # Skip if it's a directory change
    if event.is_directory:
        return
    
    # Get relative path for cleaner output
    try:
        rel_path = Path(event.src_path).relative_to(Path.cwd())
    except ValueError:
        rel_path = event.src_path
    
    test_runner.run_tests(str(rel_path))

def main():
    """Main function with argument parsing"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Watch files and run tests automatically")
    parser.add_argument("--type", choices=["unit", "all", "infrastructure", "integration"], 
                       default="unit", help="Type of tests to run on changes")
    parser.add_argument("--include", nargs="+", default=["*.py"], 
                       help="File patterns to watch")
    parser.add_argument("--exclude", nargs="+", 
                       default=["*/.venv/*", "*/__pycache__/*", "*/.pytest_cache/*", "*/.mypy_cache/*", "*/migrations/*"],
                       help="Patterns to ignore")
    
    args = parser.parse_args()
    
    test_runner = TestRunner(test_type=args.type)
    
    # Create event handler
    event_handler = PatternMatchingEventHandler(
        patterns=args.include,
        ignore_patterns=args.exclude, 
        ignore_directories=True
    )
    
    # Bind the test runner to the event handler
    event_handler.on_modified = lambda event: on_change(event, test_runner)
    event_handler.on_created = lambda event: on_change(event, test_runner)
    
    # Set up file watcher
    observer = Observer()
    observer.schedule(event_handler, ".", recursive=True)
    observer.start()
    
    print(f"👀 Watching for {args.include} changes (ignoring {args.exclude})")
    print(f"🧪 Will run: {args.type} tests using native pytest")
    print("💡 Available test types:")
    print("   unit         - Fast API tests (~1s)")
    print("   infrastructure - Redis/DB tests (~5s)")
    print("   integration  - OCPP WebSocket tests (~45s, requires server)")
    print("   all          - Complete test suite")
    print("Press Ctrl+C to stop.")
    
    # Run tests once at startup
    print("\n🚀 Running initial tests...")
    test_runner.run_tests()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Stopping file watcher...")
        observer.stop()
    
    observer.join()

if __name__ == "__main__":
    main()