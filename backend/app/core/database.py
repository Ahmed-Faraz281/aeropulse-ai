from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.app.core.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

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
                db_type = "sqlite" if settings.DATABASE_URL.startswith("sqlite") else "postgresql"
                return {"status": "connected", "database": db_type, "ok": True}
        return {"status": "error", "message": "Unexpected result", "ok": False}
    except Exception as exc:
        return {"status": "disconnected", "error": str(exc), "ok": False}
