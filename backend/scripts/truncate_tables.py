#!/usr/bin/env python3
"""
Script to truncate all tables in the database.
Useful for cloud databases where you can't drop/recreate the database.
"""
import asyncio
from tortoise import Tortoise
import sys
import os

# Add the backend directory to Python path to import tortoise_config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise_config import TORTOISE_ORM

async def truncate_all():
    """Truncate all tables except aerich migration table"""
    try:
        await Tortoise.init(config=TORTOISE_ORM)
        conn = Tortoise.get_connection('default')
        
        print("🔍 Finding tables to truncate...")
        
        # Get all table names except aerich
        result = await conn.execute_query(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename != 'aerich';"
        )
        tables = [row[0] for row in result[1]]
        
        if not tables:
            print("ℹ️  No tables to truncate")
            return
        
        print(f"🗑️  Found {len(tables)} tables: {', '.join(tables)}")
        
        # Try to truncate with CASCADE (works on most managed databases)
        try:
            # Try truncating all tables at once with CASCADE
            table_list = ', '.join([f'"{table}"' for table in tables])
            print(f"🔄 Truncating all tables with CASCADE...")
            await conn.execute_query(f'TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE;')
            print(f"✅ Successfully truncated all tables")
        except Exception as e:
            print(f"⚠️  CASCADE truncate failed: {str(e)}")
            print("🔄 Trying individual table truncation...")
            
            # If CASCADE fails, try individual truncation (may have foreign key issues)
            success_count = 0
            for table in tables:
                try:
                    print(f"   Truncating {table}...")
                    await conn.execute_query(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE;')
                    success_count += 1
                except Exception as table_error:
                    print(f"   ❌ Failed to truncate {table}: {str(table_error)}")
            
            if success_count < len(tables):
                print(f"⚠️  Only {success_count}/{len(tables)} tables were truncated successfully")
            else:
                print(f"✅ All {success_count} tables truncated individually")
        
    except Exception as e:
        print(f"❌ Error truncating tables: {str(e)}")
        raise
    finally:
        await Tortoise.close_connections()

if __name__ == "__main__":
    asyncio.run(truncate_all())