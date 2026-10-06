import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from backend.app.core.database import Base


class AlertSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class AlertType(str, enum.Enum):
    AQI_THRESHOLD = "AQI_THRESHOLD"
    SUSTAINED_HIGH_AQI = "SUSTAINED_HIGH_AQI"
    RAPID_INCREASE = "RAPID_INCREASE"
    PREDICTED_THRESHOLD = "PREDICTED_THRESHOLD"
    CATEGORY_CHANGE = "CATEGORY_CHANGE"


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    alert_type = Column(Enum(AlertType), nullable=False, index=True)
    threshold = Column(Float, nullable=False)
    duration_hours = Column(Float, nullable=True)  # Used for SUSTAINED_HIGH_AQI
    window_hours = Column(Float, nullable=True)    # Used for RAPID_INCREASE
    severity = Column(Enum(AlertSeverity), default=AlertSeverity.WARNING, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False, index=True)
    applies_to_prediction = Column(Boolean, default=False, nullable=False)
    prediction_horizon_hours = Column(Integer, nullable=True)

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

    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    location_id = Column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_id = Column(
        Integer,
        ForeignKey("alert_rules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    alert_type = Column(Enum(AlertType), nullable=False, index=True)
    severity = Column(Enum(AlertSeverity), nullable=False, index=True)
    status = Column(
        Enum(AlertStatus),
        default=AlertStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    observed_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=False)
    detected_at = Column(DateTime(timezone=True), nullable=False, index=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Data Provenance & Forecast Transparency
    source_type = Column(String(50), default="API", nullable=False, index=True)
    is_prediction = Column(Boolean, default=False, nullable=False)
    prediction_id = Column(
        Integer,
        ForeignKey("prediction_records.id", ondelete="SET NULL"),
        nullable=True,
    )
    metadata_json = Column(JSON, nullable=True)

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
    location = relationship("Location", backref="alerts")
    rule = relationship("AlertRule", back_populates="alerts")
    prediction = relationship("PredictionRecord", backref="alerts")
