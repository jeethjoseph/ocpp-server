import time
import subprocess
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

def on_change(event):
    print(f"Change detected: {event.src_path}. Running tests...")
    subprocess.run(["pytest"])

if __name__ == "__main__":
    patterns = ["*.py"]
    event_handler = PatternMatchingEventHandler(patterns=patterns, ignore_directories=True)
    event_handler.on_modified = on_change
    event_handler.on_created = on_change

    observer = Observer()
    observer.schedule(event_handler, ".", recursive=True)
    observer.start()
    print("Watching for file changes. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()