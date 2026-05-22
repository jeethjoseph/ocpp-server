#!/usr/bin/env python3
"""
Orchestrator that runs every dev seeder in order against a single shared
Tortoise connection.

Run inside the backend container:
    docker exec ocpp-backend python scripts/seed_all.py

The individual seeders (seed_docker.py, seed_franchisees.py) detect an
already-open connection via Tortoise._inited and skip their own init/close.
Add new seeders to SEEDERS below as they're written.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise

from scripts._db import build_tortoise_config
from scripts.seed_docker import DockerSeeder
from scripts.seed_franchisees import FranchiseeSeeder


SEEDERS = [DockerSeeder, FranchiseeSeeder]


async def main():
    await Tortoise.init(config=build_tortoise_config())
    print("✅ Shared DB connection opened")
    try:
        for seeder_cls in SEEDERS:
            print()
            await seeder_cls().seed_all()
    finally:
        await Tortoise.close_connections()
        print()
        print("✅ Shared DB connection closed")


if __name__ == "__main__":
    asyncio.run(main())
