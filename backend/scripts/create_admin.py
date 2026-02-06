#!/usr/bin/env python3
"""
Create an admin user for FastAdmin panel.

Usage:
    python scripts/create_admin.py [username] [password] [email]

Defaults:
    username: admin
    password: admin123
    email: admin@example.com
"""

import asyncio
import sys
import os
import bcrypt

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise


async def create_admin_user(username: str = "admin", password: str = "admin123", email: str = "admin@example.com"):
    """Create an admin user for FastAdmin"""

    # Build database URL from environment
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_user = os.getenv("DB_USER", "ocpp")
    db_password = os.getenv("DB_PASSWORD", "ocpp_password")
    db_name = os.getenv("DB_NAME", "ocpp_db")

    db_url = f"postgres://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    print(f"Connecting to database at {db_host}:{db_port}/{db_name}...")

    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["admin"]}
    )
    await Tortoise.generate_schemas()

    from admin import Admin

    # Check if user already exists
    existing = await Admin.filter(username=username).first()
    if existing:
        print(f"Admin user '{username}' already exists (id={existing.id})")
        print("To reset password, delete the user first or update directly in database.")
        await Tortoise.close_connections()
        return

    # Hash the password
    hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    # Create admin user
    admin = await Admin.create(
        username=username,
        hash_password=hashed_password,
        email=email,
        is_superuser=True,
        is_active=True
    )

    print(f"Successfully created admin user!")
    print(f"  Username: {username}")
    print(f"  Password: {password}")
    print(f"  Email: {email}")
    print(f"  ID: {admin.id}")
    print(f"\nYou can now login at /admin")

    await Tortoise.close_connections()


if __name__ == "__main__":
    # Parse command line arguments
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    email = sys.argv[3] if len(sys.argv) > 3 else "admin@example.com"

    asyncio.run(create_admin_user(username, password, email))
