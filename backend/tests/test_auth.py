from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import pytest

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
)
from backend.app.models.user import User, UserRole

# In-memory SQLite database isolated for auth test suite
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create fresh schema before each test and tear down after."""
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    # Ensure baseline accounts exist
    admin = User(
        username="admin_test",
        email="admin@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_test",
        email="analyst@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_test",
        email="viewer@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    inactive_user = User(
        username="inactive_test",
        email="inactive@test.org",
        password_hash=get_password_hash("InactivePass123!"),
        role=UserRole.VIEWER,
        is_active=False,
    )
    db.add_all([admin, analyst, viewer, inactive_user])
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.pop(get_db, None)


# TEST 1: Create a user
def test_create_user():
    db = TestingSessionLocal()
    new_user = User(
        username="newuser",
        email="newuser@example.com",
        password_hash=get_password_hash("NewPassword123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    fetched = db.query(User).filter(User.username == "newuser").first()
    assert fetched is not None
    assert fetched.email == "newuser@example.com"
    assert fetched.role == UserRole.VIEWER
    assert fetched.is_active is True
    db.close()


# TEST 2: Password is hashed and not stored as plaintext
def test_password_hashing_security():
    raw_pw = "SuperSecurePassword123!"
    hashed = get_password_hash(raw_pw)

    assert hashed != raw_pw
    assert not hashed.startswith(raw_pw)
    assert verify_password(raw_pw, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


# TEST 3: Successful login with valid credentials
def test_successful_login():
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_test", "password": "AdminPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["username"] == "admin_test"
    assert data["user"]["role"] == "admin"
    # Verify password or hash is never returned
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


# TEST 4: Incorrect password rejected
def test_incorrect_password_rejected():
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_test", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert "detail" in data
    assert "Incorrect username or password" in data["detail"]


# TEST 5: Inactive user rejected
def test_inactive_user_rejected():
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "inactive_test", "password": "InactivePass123!"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "Inactive user account" in data["detail"]


# TEST 6: /auth/me works with valid authentication
def test_get_current_user_profile():
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst_test", "password": "AnalystPass123!"},
    )
    token = login_res.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["username"] == "analyst_test"
    assert user_data["email"] == "analyst@test.org"
    assert user_data["role"] == "analyst"
    assert "password" not in user_data
    assert "password_hash" not in user_data


# TEST 7: /auth/me rejects missing/invalid/expired authentication
def test_get_current_user_unauthorized():
    # Missing token
    res1 = client.get("/api/v1/auth/me")
    assert res1.status_code == 401

    # Invalid token
    res2 = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid_garbage_token"},
    )
    assert res2.status_code == 401

    # Expired token
    expired_token = create_access_token(
        subject="admin_test",
        expires_delta=timedelta(seconds=-10),
    )
    res3 = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res3.status_code == 401


# TEST 8: Role authorization works
def test_role_authorization():
    # 1. Admin logs in -> can access admin-only
    admin_token = client.post(
        "/api/v1/auth/login",
        json={"username": "admin_test", "password": "AdminPass123!"},
    ).json()["access_token"]

    admin_res = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_res.status_code == 200

    # 2. Viewer logs in -> forbidden from admin-only
    viewer_token = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer_test", "password": "ViewerPass123!"},
    ).json()["access_token"]

    viewer_res = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_res.status_code == 403
    assert "Operation not permitted" in viewer_res.json()["detail"]

    # 3. Analyst logs in -> can access analyst-or-admin, but forbidden from admin-only
    analyst_token = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst_test", "password": "AnalystPass123!"},
    ).json()["access_token"]

    analyst_res1 = client.get(
        "/api/v1/auth/analyst-or-admin",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert analyst_res1.status_code == 200

    analyst_res2 = client.get(
        "/api/v1/auth/admin-only",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert analyst_res2.status_code == 403


# TEST 9: Logout endpoint
def test_logout_endpoint():
    token = client.post(
        "/api/v1/auth/login",
        json={"username": "viewer_test", "password": "ViewerPass123!"},
    ).json()["access_token"]

    response = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "Successfully logged out" in response.json()["message"]


# TEST 10: OpenAPI Documentation includes Authentication Schemas
def test_openapi_schema_contains_auth():
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/auth/me" in schema["paths"]
    assert "OAuth2PasswordBearer" in schema["components"]["securitySchemes"]
