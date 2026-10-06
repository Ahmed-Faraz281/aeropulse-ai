from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.app.core.database import Base


class AQIRecord(Base):
    __tablename__ = "aqi_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reading_id = Column(
        Integer,
        ForeignKey("air_quality_readings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # AQI Metrics (nullable if INSUFFICIENT_DATA or INVALID_DATA)
    aqi = Column(Integer, nullable=True)
    category = Column(String(50), nullable=True)
    dominant_pollutant = Column(String(20), nullable=True)
    calculation_method = Column(String(50), default="CPCB_INDIA_V1", nullable=False)
    status = Column(String(50), default="CALCULATED", nullable=False, index=True)

    # Sub-indices and diagnostic metadata stored as structured JSON
    pollutant_subindices = Column(JSON, nullable=True)
    warnings = Column(JSON, nullable=True)
    message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    location = relationship("Location", backref="aqi_records")
    reading = relationship("AirQualityReading", backref="aqi_record")

    __table_args__ = (
        UniqueConstraint("reading_id", "calculation_method", name="uq_reading_calculation_method"),
    )
