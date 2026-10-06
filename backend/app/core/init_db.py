import os
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from backend.app.core.config import settings
from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole
from backend.app.models.location import Location
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.system_setting import SystemSetting, SettingCategory

logger = logging.getLogger(__name__)


def init_db(db: Session) -> None:
    """
    Initializes database schema seed data:
    1. Independent column migration for existing SQLite databases (Phase 17 Step 2).
    2. Initial Admin and Development Demo User Accounts.
    3. Default Data Sources (DEMO, SIMULATED, API, OpenAQ).
    4. Multi-City Monitoring Locations (Bengaluru, Delhi, Mumbai, Hyderabad).
    5. Multi-day Historical Demo Readings with strict NULL preservation.
    """
    # 0. Independent column migration for existing databases (Phase 17 Steps 2 & 3)
    try:
        from sqlalchemy import inspect, text
        from backend.app.core.database import Base
        Base.metadata.create_all(bind=db.bind)

        inspector = inspect(db.bind)
        table_names = inspector.get_table_names()
        if "locations" in table_names:
            columns = [c["name"] for c in inspector.get_columns("locations")]
            if "external_provider" not in columns:
                db.execute(text("ALTER TABLE locations ADD COLUMN external_provider VARCHAR(32);"))
                logger.info("Added column external_provider to locations table")
            if "external_id" not in columns:
                db.execute(text("ALTER TABLE locations ADD COLUMN external_id VARCHAR(64);"))
                logger.info("Added column external_id to locations table")

            indexes = [idx["name"] for idx in inspector.get_indexes("locations")]
            if "ix_locations_external_ref" not in indexes:
                try:
                    db.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_locations_external_ref "
                        "ON locations (external_provider, external_id) "
                        "WHERE external_provider IS NOT NULL AND external_id IS NOT NULL;"
                    ))
                except Exception as idx_err:
                    logger.debug(f"Index creation note: {idx_err}")

        if "prediction_records" in table_names:
            pred_cols = [c["name"] for c in inspector.get_columns("prediction_records")]
            if "is_prediction" not in pred_cols:
                db.execute(text("ALTER TABLE prediction_records ADD COLUMN is_prediction BOOLEAN DEFAULT 1;"))
                logger.info("Added column is_prediction to prediction_records table")

        db.commit()

        # Ensure ML model storage directory exists
        os.makedirs(settings.MODEL_DIR, exist_ok=True)
    except Exception as mig_err:
        logger.warning(f"Database schema check encountered non-fatal note: {mig_err}")
        db.rollback()

    # 1. User accounts seeding
    admin = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
    if not admin:
        if settings.ENVIRONMENT == "production" and settings.ADMIN_PASSWORD == "Admin@12345":
            logger.warning(
                "CRITICAL SECURITY NOTICE: Running in production with default ADMIN_PASSWORD! "
                "Change ADMIN_PASSWORD in your environment immediately."
            )

        admin_user = User(
            username=settings.ADMIN_USERNAME,
            email=settings.ADMIN_EMAIL,
            password_hash=get_password_hash(settings.ADMIN_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin_user)
        logger.info(f"Initialized administrative account: {settings.ADMIN_USERNAME}")

    if settings.ENVIRONMENT != "production":
        analyst = db.query(User).filter(User.username == settings.ANALYST_USERNAME).first()
        if not analyst:
            analyst_user = User(
                username=settings.ANALYST_USERNAME,
                email=settings.ANALYST_EMAIL,
                password_hash=get_password_hash(settings.ANALYST_PASSWORD),
                role=UserRole.ANALYST,
                is_active=True,
            )
            db.add(analyst_user)

        viewer = db.query(User).filter(User.username == settings.VIEWER_USERNAME).first()
        if not viewer:
            viewer_user = User(
                username=settings.VIEWER_USERNAME,
                email=settings.VIEWER_EMAIL,
                password_hash=get_password_hash(settings.VIEWER_PASSWORD),
                role=UserRole.VIEWER,
                is_active=True,
            )
            db.add(viewer_user)

    db.commit()

    # 2. Data Sources seeding
    demo_source = db.query(DataSource).filter(DataSource.name == "Demo Historical Benchmark").first()
    if not demo_source:
        demo_source = DataSource(
            name="Demo Historical Benchmark",
            source_type=SourceType.DEMO,
            provider="AeroPulse Synthetic Lab",
            description="Synthetic historical telemetry for multi-city application testing.",
            is_active=True,
        )
        db.add(demo_source)

    sim_source = db.query(DataSource).filter(DataSource.name == "Software Simulation Engine").first()
    if not sim_source:
        sim_source = DataSource(
            name="Software Simulation Engine",
            source_type=SourceType.SIMULATED,
            provider="Internal Python Diurnal Simulator",
            description="Software-generated real-time stochastic air quality generator.",
            is_active=True,
        )
        db.add(sim_source)

    api_source = db.query(DataSource).filter(DataSource.name == "Open-Meteo Air Quality API").first()
    if not api_source:
        api_source = DataSource(
            name="Open-Meteo Air Quality API",
            source_type=SourceType.API,
            provider="Open-Meteo Public API",
            description="External public air quality observations where available.",
            is_active=True,
        )
        db.add(api_source)

    openaq_source = db.query(DataSource).filter(
        DataSource.name == "OpenAQ",
        DataSource.source_type == SourceType.API
    ).first()
    if not openaq_source:
        openaq_source = DataSource(
            name="OpenAQ",
            source_type=SourceType.API,
            provider="OpenAQ API v3",
            description="Official OpenAQ API v3 global air quality monitoring network.",
            is_active=True,
        )
        db.add(openaq_source)

    db.commit()
    db.refresh(demo_source)

    # 3. Locations seeding (Bengaluru, Delhi, Mumbai, Hyderabad)
    locations_data = [
        {
            "name": "Bengaluru Central (BTM Layout)",
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "latitude": 12.9165,
            "longitude": 77.6101,
            "description": "Urban mixed residential and commercial junction in South Bengaluru.",
        },
        {
            "name": "Delhi IGI Airport (Terminal 3)",
            "city": "Delhi",
            "state": "Delhi",
            "country": "India",
            "latitude": 28.5562,
            "longitude": 77.1000,
            "description": "Aviation and highway corridor station with high transit volume.",
        },
        {
            "name": "Mumbai Coastal (Bandra Kurla)",
            "city": "Mumbai",
            "state": "Maharashtra",
            "country": "India",
            "latitude": 19.0607,
            "longitude": 72.8688,
            "description": "Commercial business district with coastal marine breeze influences.",
        },
        {
            "name": "Hyderabad Tech Corridor (Hitec City)",
            "city": "Hyderabad",
            "state": "Telangana",
            "country": "India",
            "latitude": 17.4474,
            "longitude": 78.3762,
            "description": "Information technology hub with heavy commuter traffic patterns.",
        },
    ]

    location_entities = {}
    for loc in locations_data:
        existing = db.query(Location).filter(Location.name == loc["name"]).first()
        if not existing:
            existing = Location(**loc, is_active=True)
            db.add(existing)
            db.commit()
            db.refresh(existing)
        location_entities[loc["city"]] = existing

    # 4. Multi-Day Historical Demo Readings Seeding
    # Check if readings already seeded
    readings_count = db.query(AirQualityReading).count()
    if readings_count < 20:
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # Seed 48 hours of hourly historical readings across all 4 stations
        readings_to_add = []

        city_profiles = {
            "Delhi": {"pm25": 142.0, "pm10": 235.0, "no2": 62.0, "so2": 18.0, "co": 2.4, "o3": 44.0, "temp": 24.0, "hum": 48.0},
            "Bengaluru": {"pm25": 48.0, "pm10": 78.0, "no2": 26.0, "so2": 9.0, "co": 0.8, "o3": 32.0, "temp": 26.5, "hum": 62.0},
            "Mumbai": {"pm25": 68.0, "pm10": 112.0, "no2": 42.0, "so2": 14.0, "co": 1.4, "o3": 38.0, "temp": 29.0, "hum": 76.0},
            "Hyderabad": {"pm25": 74.0, "pm10": 128.0, "no2": 38.0, "so2": None, "co": 1.1, "o3": 36.0, "temp": 28.0, "hum": 55.0}, # Note intentional NULL so2!
        }

        for hours_ago in range(48, -1, -1):
            ts = base_time - timedelta(hours=hours_ago)
            # Add diurnal wave
            hour = ts.hour
            diurnal_factor = 1.0 + 0.25 * ((hour in [8, 9, 10, 19, 20, 21]) - (hour in [2, 3, 4, 13, 14]))

            for city, loc_obj in location_entities.items():
                prof = city_profiles[city]
                # Variation
                reading = AirQualityReading(
                    location_id=loc_obj.id,
                    timestamp=ts,
                    pm25=round(prof["pm25"] * diurnal_factor, 1),
                    pm10=round(prof["pm10"] * diurnal_factor, 1),
                    co=round(prof["co"] * (0.9 + 0.2 * (hour % 3 == 0)), 2),
                    no2=round(prof["no2"] * diurnal_factor, 1),
                    so2=round(prof["so2"] * 1.05, 1) if prof["so2"] is not None else None, # STRICT NULL PRESERVED!
                    o3=round(prof["o3"] * (1.3 if 12 <= hour <= 16 else 0.8), 1),
                    temperature=round(prof["temp"] + 3.0 * (12 <= hour <= 16) - 2.0 * (hour <= 6), 1),
                    humidity=round(prof["hum"] - 10.0 * (12 <= hour <= 16) + 5.0 * (hour <= 6), 1),
                    source_id=demo_source.id,
                    source_type=SourceType.DEMO,
                    quality_status=QualityStatus.VALID,
                    validation_notes=None,
                )
                readings_to_add.append(reading)

        db.add_all(readings_to_add)
        db.commit()
        logger.info(f"Seeded {len(readings_to_add)} historical demo readings across 4 monitoring locations.")

    # 4. System Settings seeding
    init_system_settings(db)


def init_system_settings(db: Session) -> None:
    """Seeds default non-secret operational parameters if not already populated."""
    defaults = [
        ("app_name", "AeroPulse AI", "string", SettingCategory.GENERAL, "Application Display Name"),
        ("timezone", "Asia/Kolkata", "string", SettingCategory.GENERAL, "Default Operational Timezone"),
        ("default_dashboard_window", "24h", "string", SettingCategory.UI, "Default Dashboard Temporal Range"),
        ("ui_refresh_interval_seconds", "30", "int", SettingCategory.UI, "Real-time Telemetry Polling Rate (seconds)"),
        ("min_aqi_data_sufficiency_subindices", "3", "int", SettingCategory.DATA_QUALITY, "Minimum required sub-indices for CPCB NAQI calculation"),
        ("prediction_forecast_horizons_hours", "[1, 3, 6, 12, 24]", "json", SettingCategory.PREDICTION, "Supported ML Prediction Horizons"),
        ("default_reporting_period", "24h", "string", SettingCategory.REPORTING, "Default Generated Report Window"),
    ]
    for key, val, vtype, cat, desc in defaults:
        existing = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not existing:
            db.add(
                SystemSetting(
                    key=key,
                    value=val,
                    value_type=vtype,
                    category=cat,
                    description=desc,
                    is_sensitive=False,
                )
            )
    db.commit()
    logger.info("Seeded default operational system settings.")
