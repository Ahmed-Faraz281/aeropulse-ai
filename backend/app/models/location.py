from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import relationship, validates
from backend.app.core.database import Base


def normalize_external_id(value: Any) -> Optional[str]:
    """
    Normalizes provider-specific external IDs to the string representation
    expected by the database `locations.external_id` VARCHAR column.
    Handles numeric IDs (e.g. OpenAQ integer IDs), string IDs, or None.
    """
    if value is None:
        return None
    val_str = str(value).strip()
    return val_str if val_str else None


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(128), index=True, nullable=False)
    city = Column(String(64), index=True, nullable=False)
    state = Column(String(64), nullable=False)
    country = Column(String(64), default="India", nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # External Provider Mapping (Phase 17 Step 2)
    external_provider = Column(String(32), nullable=True, index=True)
    external_id = Column(String(64), nullable=True, index=True)

    @validates("external_id")
    def validate_external_id(self, key: str, value: Any) -> Optional[str]:
        return normalize_external_id(value)

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

    __table_args__ = (
        Index(
            "ix_locations_external_ref",
            "external_provider",
            "external_id",
            unique=True,
            sqlite_where=text("external_provider IS NOT NULL AND external_id IS NOT NULL"),
            postgresql_where=text("external_provider IS NOT NULL AND external_id IS NOT NULL"),
        ),
    )

    # Relationships
    readings = relationship(
        "AirQualityReading",
        back_populates="location",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self):
        return f"<Location {self.name} ({self.city}, {self.state})>"
