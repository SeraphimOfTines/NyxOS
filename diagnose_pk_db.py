import asyncio
import asyncpg
import config
import os

# Force load config values if not loaded
try:
    with open("config.txt", "r") as f:
        exec(f.read(), globals())
except: pass

DB_URI = getattr(config, "PLURALKIT_DB_URI", "postgresql://postgres:postgres@localhost:5432/postgres")

async def diagnose():
    print(f"Attempting to connect to: {DB_URI}")
    try:
        conn = await asyncpg.connect(DB_URI)
        print("✅ Connection Successful!")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return

    print("\n--- Tables ---")
    rows = await conn.fetch("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname != 'pg_catalog' AND schemaname != 'information_schema';")
    for r in rows:
        print(f"- {r['tablename']}")

    print("\n--- Columns in 'messages' ---")
    try:
        cols = await conn.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'messages';")
        for c in cols:
            print(f"  {c['column_name']} ({c['data_type']})")
    except Exception as e:
        print(f"Could not fetch columns: {e}")

    print("\n--- Recent Messages (Top 5) ---")
    try:
        # Try to fetch using 'mid' assuming it exists, otherwise we fail
        msgs = await conn.fetch("SELECT * FROM messages ORDER BY mid DESC LIMIT 5")
        for m in msgs:
            print(dict(m))
    except Exception as e:
        print(f"❌ Could not fetch messages: {e}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(diagnose())
