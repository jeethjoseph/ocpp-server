# test_connection.py
import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def test_connection():
    try:
        # Test connection with SSL
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT", 5432)),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            ssl="require"
        )
        
        # Test query
        result = await conn.fetchval("SELECT version()")
        print(f"✅ Connection successful!")
        print(f"PostgreSQL version: {result}")
        
        # Check if tables exist
        tables = await conn.fetch("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """)
        print(f"📋 Tables in database: {[t['table_name'] for t in tables]}")
        
        await conn.close()
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())