import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.data_source import SourceType


class QualityStatus(str, enum.Enum):
    VALID = "VALID"
    WARNING = "WARNING"
    INVALID = "INVALID"


class AirQualityReading(Base):
    __tablename__ = "air_quality_readings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # Pollutant concentrations (Strictly NULL if missing, NEVER default to 0.0)
    pm25 = Column(Float, nullable=True)  # µg/m³
    pm10 = Column(Float, nullable=True)  # µg/m³
    co = Column(Float, nullable=True)    # mg/m³
    no2 = Column(Float, nullable=True)   # µg/m³
    so2 = Column(Float, nullable=True)   # µg/m³
    o3 = Column(Float, nullable=True)    # µg/m³

    # Environmental weather parameters
    temperature = Column(Float, nullable=True)  # °C
    humidity = Column(Float, nullable=True)     # %

    # Provenance & Data Quality
    source_id = Column(
        Integer,
        ForeignKey("data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type = Column(Enum(SourceType), nullable=False, index=True)
    quality_status = Column(
        Enum(QualityStatus),
        default=QualityStatus.VALID,
        nullable=False,
        index=True,
    )
    validation_notes = Column(Text, nullable=True)

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
    location = relationship("Location", back_populates="readings")
    data_source = relationship("DataSource", back_populates="readings")

    # Table Constraints & Composite Indexes
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "timestamp",
            "source_id",
            name="uq_location_time_source",
        ),
        Index("ix_readings_location_time", "location_id", "timestamp"),
        Index("ix_readings_source_time", "source_id", "timestamp"),
    )

    def __repr__(self):
        return (
            f"<AirQualityReading loc={self.location_id} time={self.timestamp} "
            f"pm25={self.pm25} quality={self.quality_status.value}>"
        )
