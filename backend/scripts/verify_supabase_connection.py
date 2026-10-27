"""
Supabase PostgreSQL & Database Connection Probe for AeroPulse AI
Phase 17 Step 2 Verification Script

Safely tests database connectivity, inspects table existence, and validates
Supabase configuration without logging or leaking credentials.
"""

import sys
import os
import argparse
from sqlalchemy import create_engine, inspect, text

# Add backend root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.app.core.config import settings
from backend.app.core.database import (
    normalize_database_url,
    sanitize_database_url,
    get_database_dialect,
    get_database_provider,
)


def verify_connection(custom_url: str = None) -> int:
    target_raw_url = custom_url or os.getenv("DATABASE_URL") or settings.DATABASE_URL
    sanitized_url = sanitize_database_url(target_raw_url)
    dialect = get_database_dialect(target_raw_url)
    provider = get_database_provider(target_raw_url)

    print("=" * 70)
    print("AEROPULSE AI — DATABASE & SUPABASE CONNECTION VERIFICATION")
    print("=" * 70)
    print(f"Target URL: {sanitized_url}")
    print(f"Dialect:    {dialect.upper()}")
    print(f"Provider:   {provider.upper()}")
    print("-" * 70)

    if provider == "sqlite":
        print("[INFO] Running in local SQLite development mode.")
        print("[INFO] To connect to Supabase PostgreSQL, set the DATABASE_URL in .env:")
        print("       DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres")
        print("       or via Supabase Connection Pooler (Session Mode):")
        print("       DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres")
        print("-" * 70)

    normalized_url = normalize_database_url(target_raw_url)

    engine_kwargs = {"pool_pre_ping": True}
    if dialect == "sqlite":
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10
        engine_kwargs["pool_recycle"] = 300

    try:
        engine = create_engine(normalized_url, **engine_kwargs)
        with engine.connect() as conn:
            print("[1/3] Testing basic connectivity (SELECT 1)...")
            res = conn.execute(text("SELECT 1")).scalar()
            if res != 1:
                print("  [FAIL] Unexpected query result from SELECT 1")
                return 1
            print("  [PASS] Connection established successfully.")

            print("[2/3] Querying database version...")
            if dialect == "postgresql":
                version_str = conn.execute(text("SELECT version();")).scalar()
                print(f"  [PASS] Database Version: {version_str[:60]}...")
                if "supabase" in sanitized_url.lower() or "pooler" in sanitized_url.lower():
                    print("  [PASS] Confirmed Supabase PostgreSQL instance.")
            else:
                version_str = conn.execute(text("SELECT sqlite_version();")).scalar()
                print(f"  [PASS] SQLite Version: {version_str}")

            print("[3/3] Inspecting schema tables...")
            inspector = inspect(conn)
            tables = sorted(inspector.get_table_names())
            print(f"  Found {len(tables)} tables: {', '.join(tables)}")

            required_core_tables = [
                "users",
                "locations",
                "data_sources",
                "air_quality_readings",
                "aqi_records",
            ]
            missing = [t for t in required_core_tables if t not in tables]
            if missing:
                print(f"  [WARN] Missing core tables: {missing}")
                print("         Run backend startup or init_db to seed schema tables.")
            else:
                print("  [PASS] All core application tables are present and verified.")

        print("-" * 70)
        print("[SUCCESS] Database connection check completed cleanly.")
        return 0

    except Exception as exc:
        print("-" * 70)
        from backend.app.core.database import sanitize_error_message
        clean_err = sanitize_error_message(str(exc))
        print(f"[ERROR] Database connection failed: {clean_err}")
        print("-" * 70)
        print("Troubleshooting Supabase Connection:")
        print("1. Verify your network allows outbound traffic on port 5432 or 6543.")
        print("2. For Supabase IPv4 compatibility, use the Supabase Connection Pooler URI")
        print("   (Session mode on port 5432 or Transaction mode on port 6543).")
        print("3. Ensure special characters in your password are properly percent-encoded if needed.")
        print("4. Check that psycopg[binary] is installed in your python environment.")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify AeroPulse Database / Supabase Connection")
    parser.add_argument("--url", help="Optional DATABASE_URL override to test", default=None)
    args = parser.parse_args()
    sys.exit(verify_connection(args.url))
