# utils.py
"""
Utility functions for OCPP server.
Add logging, ID generation, and other helpers here.
"""
import datetime
import uuid

def get_utc_now():
    """Return current UTC time with timezone info."""
    return datetime.datetime.now(datetime.timezone.utc)

def generate_uuid():
    """Generate a new UUID4 as string."""
    return str(uuid.uuid4())

# Example: You can add more helpers as needed
