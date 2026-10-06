from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class PredictionRecord(Base):
    __tablename__ = "prediction_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    target_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    horizon_hours = Column(Integer, nullable=False)
    predicted_aqi = Column(Float, nullable=False)
    predicted_category = Column(String(50), nullable=False)
    model_name = Column(String(100), default="RandomForestRegressor", nullable=False)
    training_observations = Column(Integer, nullable=False)
    mae = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    r2 = Column(Float, nullable=True)
    data_sources = Column(JSON, nullable=True)
    has_simulated_data = Column(Boolean, default=False, nullable=False)
    provenance_notice = Column(Text, nullable=True)
    is_prediction = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    location = relationship("Location", backref="prediction_records")


class ModelRegistryRecord(Base):
    __tablename__ = "model_registry_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    model_id = Column(String(100), unique=True, index=True, nullable=False)
    model_name = Column(String(100), default="RandomForestRegressor", nullable=False)
    horizon_hours = Column(Integer, nullable=False, index=True)
    version = Column(String(20), default="1.0.0", nullable=False)
    artifact_path = Column(String(255), nullable=False)
    training_observations = Column(Integer, nullable=False)
    training_locations_count = Column(Integer, nullable=False)
    training_start = Column(DateTime(timezone=True), nullable=True)
    training_end = Column(DateTime(timezone=True), nullable=True)
    mae = Column(Float, nullable=True)
    rmse = Column(Float, nullable=True)
    r2 = Column(Float, nullable=True)
    features = Column(JSON, nullable=False)
    data_sources = Column(JSON, nullable=False)
    has_simulated_data = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, index=True, nullable=False)
    checksum = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

