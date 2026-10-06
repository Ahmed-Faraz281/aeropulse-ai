import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class SourceType(str, enum.Enum):
    API = "API"
    UPLOADED = "UPLOADED"
    SIMULATED = "SIMULATED"
    DEMO = "DEMO"


class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(128), index=True, nullable=False)
    source_type = Column(Enum(SourceType), nullable=False, index=True)
    provider = Column(String(128), nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
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
    readings = relationship(
        "AirQualityReading",
        back_populates="data_source",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<DataSource {self.name} ({self.source_type.value})>"
