"""
Unit tests for database URL normalization, credential sanitization,
and connection checking (Phase 17 Step 2).
"""

from unittest.mock import patch, MagicMock
from backend.app.core.database import (
    normalize_database_url,
    sanitize_database_url,
    sanitize_error_message,
    get_database_dialect,
    get_database_provider,
    check_db_connection,
)


def test_normalize_database_url_postgresql_schemes():
    """Validates that postgres:// and postgresql:// are normalized to psycopg v3 dialect."""
    raw_supabase_direct = "postgresql://postgres:mysecretpass@db.xyz.supabase.co:5432/postgres"
    expected_direct = "postgresql+psycopg://postgres:mysecretpass@db.xyz.supabase.co:5432/postgres"
    assert normalize_database_url(raw_supabase_direct) == expected_direct

    raw_supabase_pooler = "postgres://postgres.xyz:mysecretpass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    expected_pooler = "postgresql+psycopg://postgres.xyz:mysecretpass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    assert normalize_database_url(raw_supabase_pooler) == expected_pooler


def test_normalize_database_url_preserved_schemes():
    """Validates that already qualified drivers and sqlite are left untouched."""
    already_psycopg = "postgresql+psycopg://postgres:mysecretpass@db.xyz.supabase.co:5432/postgres"
    assert normalize_database_url(already_psycopg) == already_psycopg

    sqlite_url = "sqlite:///./air_quality.db"
    assert normalize_database_url(sqlite_url) == sqlite_url

    assert normalize_database_url("") == ""
    assert normalize_database_url(None) == ""


def test_sanitize_database_url_masks_password():
    """Validates that passwords in connection strings are strictly hidden."""
    raw_url = "postgresql://postgres:super_secret_pass_12345@db.xyz.supabase.co:5432/postgres"
    sanitized = sanitize_database_url(raw_url)
    assert "super_secret_pass_12345" not in sanitized
    assert "***" in sanitized
    assert "db.xyz.supabase.co" in sanitized


def test_sanitize_error_message_masks_credentials():
    """Validates that error messages containing passwords or URIs are sanitized."""
    error_with_uri = (
        "connection to server at db.xyz.supabase.co failed: "
        "postgresql://postgres:topsecretpassword@db.xyz.supabase.co:5432/postgres"
    )
    clean = sanitize_error_message(error_with_uri)
    assert "topsecretpassword" not in clean
    assert "***" in clean

    error_with_kw = "psycopg.OperationalError: password=topsecretpassword authentication failed"
    clean_kw = sanitize_error_message(error_with_kw)
    assert "topsecretpassword" not in clean_kw
    assert "password=***" in clean_kw


def test_get_database_dialect():
    """Validates dialect identification."""
    assert get_database_dialect("sqlite:///./test.db") == "sqlite"
    assert get_database_dialect("postgresql://user:pass@host/db") == "postgresql"
    assert get_database_dialect("postgresql+psycopg://user:pass@host/db") == "postgresql"


def test_get_database_provider():
    """Validates database provider identification for SQLite, Supabase, and PostgreSQL."""
    assert get_database_provider("sqlite:///./test.db") == "sqlite"
    assert get_database_provider("postgresql://user:pass@db.abc.supabase.co:5432/postgres") == "supabase"
    assert get_database_provider("postgresql://user:pass@aws-0-ap-south-1.pooler.supabase.com:6543/postgres") == "supabase"
    assert get_database_provider("postgresql://user:pass@localhost:5432/test") == "postgresql"


def test_check_db_connection_success():
    """Validates check_db_connection() returns expected dict on active engine."""
    result = check_db_connection()
    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["database"] in ("sqlite", "postgresql")
    assert result["provider"] in ("sqlite", "supabase", "postgresql")


def test_check_db_connection_handles_failure():
    """Validates check_db_connection() handles exceptions gracefully without leaking secrets."""
    with patch("backend.app.core.database.engine.connect") as mock_conn:
        mock_conn.side_effect = Exception("failed to connect with password=supersecretpass")
        result = check_db_connection()
        assert result["ok"] is False
        assert result["status"] == "disconnected"
        assert "supersecretpass" not in result["error"]
        assert "password=***" in result["error"]
