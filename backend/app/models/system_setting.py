import enum
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Enum, Integer, String, Text

from backend.app.core.database import Base


class SettingCategory(str, enum.Enum):
    GENERAL = "GENERAL"
    DATA_QUALITY = "DATA_QUALITY"
    PREDICTION = "PREDICTION"
    REPORTING = "REPORTING"
    UI = "UI"


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(64), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    value_type = Column(String(32), default="string", nullable=False)  # "string", "int", "float", "bool", "json"
    description = Column(Text, nullable=True)
    category = Column(Enum(SettingCategory), default=SettingCategory.GENERAL, nullable=False, index=True)
    is_sensitive = Column(Boolean, default=False, nullable=False)
    updated_by = Column(String(64), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<SystemSetting key={self.key} category={self.category.value}>"
