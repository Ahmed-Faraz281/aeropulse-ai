import re
from typing import Generator, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.app.core.config import settings


_DEFAULT_URL = object()


def normalize_database_url(url: Optional[str] = _DEFAULT_URL) -> str:
    """
    Normalizes PostgreSQL connection URLs to explicitly specify the psycopg (v3) driver
    if no driver dialect is specified, ensuring seamless compatibility with
    Supabase, Render, Heroku, and standard PostgreSQL connection strings.
    """
    if url is _DEFAULT_URL:
        target = settings.DATABASE_URL or ""
    elif url is None:
        return ""
    else:
        target = url

    if not target:
        return ""
    if target.startswith("postgres://"):
        return "postgresql+psycopg://" + target[len("postgres://"):]
    if target.startswith("postgresql://"):
        return "postgresql+psycopg://" + target[len("postgresql://"):]
    return target


def sanitize_database_url(url: Optional[str] = _DEFAULT_URL) -> str:
    """
    Returns a sanitized database connection string with password masked.
    Prevents credentials from ever being leaked in logs, health checks, or error messages.
    """
    if url is _DEFAULT_URL:
        target = settings.DATABASE_URL or ""
    elif url is None:
        return ""
    else:
        target = url

    if not target:
        return ""
    try:
        u = make_url(target)
        return u.render_as_string(hide_password=True)
    except Exception:
        # Fallback regex masking if URL parsing fails
        sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", target)
        return sanitized


def sanitize_error_message(error: str) -> str:
    """Removes sensitive credentials or connection passwords from error strings."""
    if not error:
        return ""
    sanitized = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", str(error))
    sanitized = re.sub(r"password=([^\s,;]+)", r"password=***", sanitized, flags=re.IGNORECASE)
    return sanitized


def get_database_dialect(url: Optional[str] = None) -> str:
    """Returns database dialect ('sqlite' or 'postgresql')."""
    target = url if url is not None else settings.DATABASE_URL
    if target.startswith("sqlite"):
        return "sqlite"
    return "postgresql"


def get_database_provider(url: Optional[str] = None) -> str:
    """Identifies the database provider ('sqlite', 'supabase', or 'postgresql')."""
    target = url if url is not None else settings.DATABASE_URL
    if target.startswith("sqlite"):
        return "sqlite"
    target_lower = target.lower()
    if "supabase.co" in target_lower or "pooler.supabase.com" in target_lower:
        return "supabase"
    return "postgresql"


# Configure connection pool kwargs safely per dialect
normalized_url = normalize_database_url(settings.DATABASE_URL)
engine_kwargs = {
    "pool_pre_ping": True,
}

if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Production PostgreSQL / Supabase pool configuration
    # pool_recycle=300 (5m) prevents dropped connections across Supabase/cloud poolers
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_recycle"] = 300

engine = create_engine(normalized_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> dict:
    """Executes a lightweight query to verify active database connectivity."""
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            row = result.fetchone()
            if row and row[0] == 1:
                db_dialect = get_database_dialect()
                db_provider = get_database_provider()
                return {
                    "status": "connected",
                    "database": db_dialect,
                    "provider": db_provider,
                    "ok": True,
                }
        return {"status": "error", "message": "Unexpected result", "ok": False}
    except Exception as exc:
        sanitized_err = sanitize_error_message(str(exc))
        return {"status": "disconnected", "error": sanitized_err, "ok": False}
