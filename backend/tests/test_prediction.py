from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.core.database import Base, get_db
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord

# In-memory test SQLite DB
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

admin_token = ""
analyst_token = ""
viewer_token = ""
loc_sufficient_id = 0
loc_insufficient_id = 0
loc_simulated_id = 0


@pytest.fixture(autouse=True)
def setup_prediction_test_db():
    global admin_token, analyst_token, viewer_token
    global loc_sufficient_id, loc_insufficient_id, loc_simulated_id

    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    # Users
    admin = User(
        username="admin_pred",
        email="admin_pred@test.org",
        password_hash=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    analyst = User(
        username="analyst_pred",
        email="analyst_pred@test.org",
        password_hash=get_password_hash("AnalystPass123!"),
        role=UserRole.ANALYST,
        is_active=True,
    )
    viewer = User(
        username="viewer_pred",
        email="viewer_pred@test.org",
        password_hash=get_password_hash("ViewerPass123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    db.add_all([admin, analyst, viewer])
    db.commit()

    # Locations
    loc1 = Location(
        name="Station Central",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9716,
        longitude=77.5946,
        is_active=True,
    )
    loc2 = Location(
        name="Station Sparse",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        latitude=12.9352,
        longitude=77.6245,
        is_active=True,
    )
    loc3 = Location(
        name="Station Sim",
        city="Delhi",
        state="Delhi",
        country="India",
        latitude=28.6139,
        longitude=77.2090,
        is_active=True,
    )
    db.add_all([loc1, loc2, loc3])
    db.commit()
    db.refresh(loc1)
    db.refresh(loc2)
    db.refresh(loc3)

    loc_sufficient_id = loc1.id
    loc_insufficient_id = loc2.id
    loc_simulated_id = loc3.id

    # Data sources
    ds_real = DataSource(
        name="Real CPCB Station",
        source_type=SourceType.API,
        is_active=True,
    )
    ds_sim = DataSource(
        name="Simulation Generator",
        source_type=SourceType.SIMULATED,
        is_active=True,
    )
    db.add_all([ds_real, ds_sim])
    db.commit()
    db.refresh(ds_real)
    db.refresh(ds_sim)

    # Seed 48 hours of chronological data for loc1 (Sufficient)
    base_time = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    for i in range(48):
        ts = base_time + timedelta(hours=i)
        reading = AirQualityReading(
            location_id=loc1.id,
            source_id=ds_real.id,
            source_type=ds_real.source_type,
            timestamp=ts,
            pm25=40.0 + (i % 24) * 2.0,
            pm10=80.0 + (i % 24) * 3.0,
            no2=25.0 + (i % 12),
            so2=15.0,
            co=0.8,
            o3=None if (i % 5 == 0) else 35.0,  # Intentionally missing to test NULL preservation
            temperature=24.0 + (i % 12) * 0.5,
            humidity=55.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(reading)
        db.flush()

        aqi_val = int(80 + (i % 24) * 3)
        aqi_rec = AQIRecord(
            location_id=loc1.id,
            reading_id=reading.id,
            timestamp=ts,
            aqi=aqi_val,
            category="Satisfactory" if aqi_val <= 100 else "Moderate",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
        db.add(aqi_rec)

    # Seed only 5 hours of data for loc2 (Insufficient data)
    for i in range(5):
        ts = base_time + timedelta(hours=i)
        reading = AirQualityReading(
            location_id=loc2.id,
            source_id=ds_real.id,
            source_type=ds_real.source_type,
            timestamp=ts,
            pm25=30.0,
            pm10=60.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(reading)
        db.flush()
        aqi_rec = AQIRecord(
            location_id=loc2.id,
            reading_id=reading.id,
            timestamp=ts,
            aqi=60,
            category="Satisfactory",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
        db.add(aqi_rec)

    # Seed 36 hours of simulated data for loc3 (Provenance check)
    for i in range(36):
        ts = base_time + timedelta(hours=i)
        reading = AirQualityReading(
            location_id=loc3.id,
            source_id=ds_sim.id,
            source_type=ds_sim.source_type,
            timestamp=ts,
            pm25=120.0 + (i % 12) * 5.0,
            pm10=220.0 + (i % 12) * 8.0,
            temperature=20.0,
            humidity=40.0,
            quality_status=QualityStatus.VALID,
        )
        db.add(reading)
        db.flush()
        aqi_val = int(220 + (i % 12) * 8)
        aqi_rec = AQIRecord(
            location_id=loc3.id,
            reading_id=reading.id,
            timestamp=ts,
            aqi=aqi_val,
            category="Poor",
            dominant_pollutant="pm25",
            status="CALCULATED",
        )
        db.add(aqi_rec)

    db.commit()
    db.close()

    # Login tokens
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "admin_pred", "password": "AdminPass123!"},
    )
    admin_token = r.json()["access_token"]

    r = client.post(
        "/api/v1/auth/login",
        data={"username": "analyst_pred", "password": "AnalystPass123!"},
    )
    analyst_token = r.json()["access_token"]

    r = client.post(
        "/api/v1/auth/login",
        data={"username": "viewer_pred", "password": "ViewerPass123!"},
    )
    viewer_token = r.json()["access_token"]

    yield

    Base.metadata.drop_all(bind=test_engine)
    app.dependency_overrides.clear()


# ==============================================================================
# Unit & Service Tests
# ==============================================================================

def test_feature_engineering_and_null_preservation():
    """Verify feature extractor builds diurnal cyclics and preserves NaNs (no 0.0 conversion)."""
    from backend.app.services.prediction_service import extract_features_and_targets

    db = TestingSessionLocal()
    try:
        X, y, timestamps, sources = extract_features_and_targets(db, loc_sufficient_id, horizon_hours=1)
        assert len(X) > 0
        assert len(X) == len(y)
        # Check diurnal cyclics exist in feature dict
        sample = X[0]
        assert "hour_sin" in sample
        assert "hour_cos" in sample
        assert "dow_sin" in sample
        assert "dow_cos" in sample
        # Check that missing pollutant (o3 in sample 0) was NOT silently zeroed out
        assert sample["o3"] is None or (sample["o3"] != sample["o3"])
        # Check sources tracking
        assert "API" in sources
    finally:
        db.close()



def test_insufficient_data_handling():
    """Verify system safely returns INSUFFICIENT_DATA when observation count is below threshold."""
    from backend.app.services.prediction_service import train_and_evaluate_model

    db = TestingSessionLocal()
    try:
        result = train_and_evaluate_model(db, loc_insufficient_id, horizon_hours=1, min_observations=20)
        assert result["status"] == "INSUFFICIENT_DATA"
        assert "Insufficient" in result["message"]
        assert result["metrics"] is None
    finally:
        db.close()


def test_chronological_train_validation_split():
    """Verify chronological split has no temporal leakage (train timestamps < val timestamps)."""
    from backend.app.services.prediction_service import split_chronologically

    base_time = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    timestamps = [base_time + timedelta(hours=i) for i in range(40)]
    X = [{"val": i} for i in range(40)]
    y = [float(i * 2) for i in range(40)]

    X_train, X_val, y_train, y_val, t_train, t_val = split_chronologically(X, y, timestamps, split_ratio=0.8)

    assert len(X_train) == 32
    assert len(X_val) == 8
    # Latest training timestamp must be strictly before earliest validation timestamp
    assert max(t_train) < min(t_val)


def test_model_training_and_evaluation_metrics():
    """Verify model training produces valid MAE, RMSE, and R² metrics."""
    from backend.app.services.prediction_service import train_and_evaluate_model

    db = TestingSessionLocal()
    try:
        result = train_and_evaluate_model(db, loc_sufficient_id, horizon_hours=1, min_observations=20)
        assert result["status"] == "SUCCESS"
        metrics = result["metrics"]
        assert "mae" in metrics and metrics["mae"] >= 0.0
        assert "rmse" in metrics and metrics["rmse"] >= 0.0
        assert "r2" in metrics and metrics["r2"] <= 1.0
        assert result["training_observations"] >= 20
        assert "API" in result["data_sources"]
        assert result["has_simulated_data"] is False
    finally:
        db.close()


def test_prediction_horizon_generation():
    """Verify predictions can be generated for 1h, 3h, 6h, 12h, 24h horizons."""
    from backend.app.services.prediction_service import generate_predictions

    db = TestingSessionLocal()
    try:
        for horizon in [1, 3, 6, 12, 24]:
            pred = generate_predictions(db, loc_sufficient_id, horizon_hours=horizon)
            assert pred is not None
            assert pred["horizon_hours"] == horizon
            assert 0 <= pred["predicted_aqi"] <= 500
            assert pred["predicted_category"] in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
            # Target timestamp must be exactly horizon_hours after base
            delta = pred["target_timestamp"] - pred["base_timestamp"]
            assert delta == timedelta(hours=horizon)
    finally:
        db.close()


def test_provenance_tracking_with_simulated_data():
    """Verify provenance explicitly flags SIMULATED observations when present."""
    from backend.app.services.prediction_service import train_and_evaluate_model

    db = TestingSessionLocal()
    try:
        result = train_and_evaluate_model(db, loc_simulated_id, horizon_hours=1, min_observations=20)
        assert result["status"] == "SUCCESS"
        assert result["has_simulated_data"] is True
        assert "SIMULATED" in result["data_sources"]
        assert "SIMULATED" in result["provenance_notice"]
    finally:
        db.close()


# ==============================================================================
# REST API & RBAC Tests
# ==============================================================================

def test_api_train_admin_success():
    """Admin can trigger model training via POST /api/v1/prediction/train."""
    response = client.post(
        "/api/v1/prediction/train",
        json={"location_id": loc_sufficient_id, "horizon_hours": 3},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert data["metrics"]["mae"] >= 0.0


def test_api_train_analyst_success():
    """Analyst can trigger model training via POST /api/v1/prediction/train."""
    response = client.post(
        "/api/v1/prediction/train",
        json={"location_id": loc_sufficient_id, "horizon_hours": 1},
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"


def test_api_train_viewer_forbidden():
    """Viewer is forbidden from training models (HTTP 403)."""
    response = client.post(
        "/api/v1/prediction/train",
        json={"location_id": loc_sufficient_id, "horizon_hours": 1},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_api_predict_admin_success():
    """Admin can generate future prediction via POST /api/v1/prediction/predict."""
    response = client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_sufficient_id, "horizon_hours": 6},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location_id"] == loc_sufficient_id
    assert data["horizon_hours"] == 6
    assert data["predicted_aqi"] >= 0
    assert data["predicted_category"] in ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]


def test_api_predict_viewer_forbidden():
    """Viewer is forbidden from initiating on-demand predictions (HTTP 403)."""
    response = client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_sufficient_id, "horizon_hours": 6},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 403


def test_api_get_latest_predictions_viewer_allowed():
    """Viewer can read latest predictions via GET /api/v1/prediction/{location_id}/latest."""
    # First generate a prediction with admin
    client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_sufficient_id, "horizon_hours": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Viewer reads
    response = client.get(
        f"/api/v1/prediction/{loc_sufficient_id}/latest",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_api_get_history_viewer_allowed():
    """Viewer can read historical predictions via GET /api/v1/prediction/{location_id}/history."""
    response = client.get(
        f"/api/v1/prediction/{loc_sufficient_id}/history",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_api_insufficient_data_response():
    """Predict API safely reports INSUFFICIENT_DATA for station with few observations."""
    response = client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_insufficient_id, "horizon_hours": 1},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "Insufficient" in data["detail"] or "INSUFFICIENT_DATA" in data["detail"]


def test_api_invalid_horizon_rejected():
    """Predict API rejects invalid forecast horizons with HTTP 422 or 400."""
    response = client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_sufficient_id, "horizon_hours": 999},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code in [400, 422]


def test_api_unauthenticated_rejected():
    """Unauthenticated requests are rejected with HTTP 401."""
    response = client.post(
        "/api/v1/prediction/predict",
        json={"location_id": loc_sufficient_id, "horizon_hours": 1},
    )
    assert response.status_code == 401
