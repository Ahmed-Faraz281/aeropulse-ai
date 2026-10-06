"""
AQI Calculation Engine implementing the CPCB (Central Pollution Control Board)
National Air Quality Index (NAQI) Standard (CPCB_INDIA_V1).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from backend.app.services.aqi_breakpoints import (
    calculate_sub_index,
    get_aqi_category,
)


class AQIStatus(str, Enum):
    CALCULATED = "CALCULATED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_DATA = "INVALID_DATA"
    UNSUPPORTED = "UNSUPPORTED"


# Deterministic priority ordering for dominant pollutant tie-breaking
POLLUTANT_PRIORITY = ["pm25", "pm10", "no2", "so2", "co", "o3", "nh3", "pb"]
POLLUTANT_LABELS = {
    "pm25": "PM2.5",
    "pm10": "PM10",
    "no2": "NO2",
    "so2": "SO2",
    "co": "CO",
    "o3": "O3",
    "nh3": "NH3",
    "pb": "Pb",
}


@dataclass
class AQICalculationResult:
    status: AQIStatus
    aqi: Optional[int] = None
    category: Optional[str] = None
    dominant_pollutant: Optional[str] = None
    pollutant_subindices: Dict[str, Optional[int]] = field(default_factory=dict)
    pollutants_used: List[str] = field(default_factory=list)
    pollutants_unavailable: List[str] = field(default_factory=list)
    calculation_method: str = "CPCB_INDIA_V1"
    warnings: List[str] = field(default_factory=list)
    message: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def calculate_aqi(
    pm25: Optional[float] = None,
    pm10: Optional[float] = None,
    no2: Optional[float] = None,
    so2: Optional[float] = None,
    co: Optional[float] = None,
    o3: Optional[float] = None,
    nh3: Optional[float] = None,
    pb: Optional[float] = None,
    timestamp: Optional[datetime] = None,
) -> AQICalculationResult:
    """
    Computes the overall AQI, dominant pollutant, and individual sub-indices
    strictly conforming to the Indian CPCB NAQI methodology.

    CPCB Sufficiency Rules:
    1. Overall AQI requires at least 3 valid pollutant sub-indices.
    2. At least one of the available pollutants MUST be a particulate matter (PM2.5 or PM10).
    3. Missing pollutants remain NULL (never replaced with 0).
    4. Non-physical negative concentrations trigger INVALID_DATA status.
    5. Capping applies above max breakpoints with explicit warning.
    """
    now = timestamp or datetime.now(timezone.utc)
    raw_inputs = {
        "pm25": pm25,
        "pm10": pm10,
        "no2": no2,
        "so2": so2,
        "co": co,
        "o3": o3,
        "nh3": nh3,
        "pb": pb,
    }

    # 1. Check for invalid negative or non-finite values
    invalid_negatives = [k for k, v in raw_inputs.items() if v is not None and isinstance(v, (int, float)) and v < 0]
    if invalid_negatives:
        labels = [POLLUTANT_LABELS.get(k, k) for k in invalid_negatives]
        return AQICalculationResult(
            status=AQIStatus.INVALID_DATA,
            message=f"Negative concentration detected for {', '.join(labels)}. Non-physical measurement cannot be evaluated.",
            timestamp=now,
        )

    invalid_non_finites = [
        k for k, v in raw_inputs.items()
        if v is not None and (not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v))
    ]
    if invalid_non_finites:
        labels = [POLLUTANT_LABELS.get(k, k) for k in invalid_non_finites]
        return AQICalculationResult(
            status=AQIStatus.INVALID_DATA,
            message=f"Non-finite concentration detected for {', '.join(labels)}. Non-physical measurement cannot be evaluated.",
            timestamp=now,
        )

    # 2. Compute individual sub-indices
    subindices: Dict[str, Optional[int]] = {}
    pollutants_used: List[str] = []
    pollutants_unavailable: List[str] = []
    warnings: List[str] = []

    for key in POLLUTANT_PRIORITY:
        val = raw_inputs.get(key)
        if val is None:
            pollutants_unavailable.append(key)
        else:
            sub_idx, warn = calculate_sub_index(key, val)
            if sub_idx is not None:
                subindices[key] = sub_idx
                pollutants_used.append(key)
                if warn:
                    warnings.append(warn)
            else:
                pollutants_unavailable.append(key)

    # 3. Verify CPCB minimum sufficiency conditions
    # Condition A: Minimum 3 pollutants
    if len(pollutants_used) < 3:
        return AQICalculationResult(
            status=AQIStatus.INSUFFICIENT_DATA,
            pollutant_subindices=subindices,
            pollutants_used=pollutants_used,
            pollutants_unavailable=pollutants_unavailable,
            warnings=warnings,
            message=f"At least 3 pollutants are required by CPCB NAQI methodology to compute an overall AQI (found {len(pollutants_used)}: {', '.join(pollutants_used) if pollutants_used else 'none'}).",
            timestamp=now,
        )

    # Condition B: At least one particulate pollutant (PM2.5 or PM10)
    has_particulate = ("pm25" in pollutants_used) or ("pm10" in pollutants_used)
    if not has_particulate:
        return AQICalculationResult(
            status=AQIStatus.INSUFFICIENT_DATA,
            pollutant_subindices=subindices,
            pollutants_used=pollutants_used,
            pollutants_unavailable=pollutants_unavailable,
            warnings=warnings,
            message="At least one particulate pollutant (PM2.5 or PM10) must be monitored to compute an overall AQI.",
            timestamp=now,
        )

    # 4. Overall AQI is the maximum sub-index
    max_subindex = -1
    dominant_key = None

    # Determine dominant pollutant using deterministic tie-breaking
    for key in POLLUTANT_PRIORITY:
        if key in subindices and subindices[key] is not None:
            val = subindices[key]
            if val > max_subindex:
                max_subindex = val
                dominant_key = key

    overall_aqi = max_subindex
    dominant_label = POLLUTANT_LABELS.get(dominant_key, dominant_key.upper()) if dominant_key else None
    category = get_aqi_category(overall_aqi)

    return AQICalculationResult(
        status=AQIStatus.CALCULATED,
        aqi=overall_aqi,
        category=category,
        dominant_pollutant=dominant_label,
        pollutant_subindices=subindices,
        pollutants_used=pollutants_used,
        pollutants_unavailable=pollutants_unavailable,
        calculation_method="CPCB_INDIA_V1",
        warnings=warnings,
        timestamp=now,
    )
