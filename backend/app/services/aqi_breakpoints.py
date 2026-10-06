"""
CPCB (Central Pollution Control Board) National Air Quality Index (NAQI) Breakpoints
and Category Definitions.

Standard Methodology: CPCB_INDIA_V1
"""

import math
from enum import Enum
from typing import Dict, List, Optional, Tuple


class AQICategory(str, Enum):
    GOOD = "Good"
    SATISFACTORY = "Satisfactory"
    MODERATE = "Moderate"
    POOR = "Poor"
    VERY_POOR = "Very Poor"
    SEVERE = "Severe"


# Category Breakpoints: (aqi_lo, aqi_hi, category_name, color_hex, health_implication)
AQI_CATEGORY_BANDS = [
    (0, 50, AQICategory.GOOD, "#00b050", "Minimal health impact"),
    (51, 100, AQICategory.SATISFACTORY, "#92d050", "Minor breathing discomfort to sensitive people"),
    (101, 200, AQICategory.MODERATE, "#ffff00", "Breathing discomfort to people with lungs, asthma and heart diseases"),
    (201, 300, AQICategory.POOR, "#ff9900", "Breathing discomfort to most people on prolonged exposure"),
    (301, 400, AQICategory.VERY_POOR, "#ff0000", "Respiratory illness on prolonged exposure"),
    (401, 500, AQICategory.SEVERE, "#7030a0", "Affects healthy people and seriously impacts those with existing diseases"),
]

# Official CPCB Breakpoint Tables
# Format: (concentration_lo, concentration_hi, aqi_lo, aqi_hi)
CPCB_BREAKPOINTS: Dict[str, List[Tuple[float, float, int, int]]] = {
    "pm25": [
        (0.0, 30.0, 0, 50),
        (31.0, 60.0, 51, 100),
        (61.0, 90.0, 101, 200),
        (91.0, 120.0, 201, 300),
        (121.0, 250.0, 301, 400),
        (251.0, 380.0, 401, 500),
    ],
    "pm10": [
        (0.0, 50.0, 0, 50),
        (51.0, 100.0, 51, 100),
        (101.0, 250.0, 101, 200),
        (251.0, 350.0, 201, 300),
        (351.0, 430.0, 301, 400),
        (431.0, 510.0, 401, 500),
    ],
    "no2": [
        (0.0, 40.0, 0, 50),
        (41.0, 80.0, 51, 100),
        (81.0, 180.0, 101, 200),
        (181.0, 280.0, 201, 300),
        (281.0, 400.0, 301, 400),
        (401.0, 500.0, 401, 500),
    ],
    "so2": [
        (0.0, 40.0, 0, 50),
        (41.0, 80.0, 51, 100),
        (81.0, 380.0, 101, 200),
        (381.0, 800.0, 201, 300),
        (801.0, 1600.0, 301, 400),
        (1601.0, 2100.0, 401, 500),
    ],
    "co": [
        (0.0, 1.0, 0, 50),
        (1.1, 2.0, 51, 100),
        (2.1, 10.0, 101, 200),
        (10.1, 17.0, 201, 300),
        (17.1, 34.0, 301, 400),
        (34.1, 40.0, 401, 500),
    ],
    "o3": [
        (0.0, 50.0, 0, 50),
        (51.0, 100.0, 51, 100),
        (101.0, 168.0, 101, 200),
        (169.0, 208.0, 201, 300),
        (209.0, 748.0, 301, 400),
        (749.0, 1000.0, 401, 500),
    ],
    "nh3": [
        (0.0, 200.0, 0, 50),
        (201.0, 400.0, 51, 100),
        (401.0, 800.0, 101, 200),
        (801.0, 1200.0, 201, 300),
        (1201.0, 1800.0, 301, 400),
        (1801.0, 2400.0, 401, 500),
    ],
    "pb": [
        (0.0, 0.5, 0, 50),
        (0.6, 1.0, 51, 100),
        (1.1, 2.0, 101, 200),
        (2.1, 3.0, 201, 300),
        (3.1, 3.5, 301, 400),
        (3.6, 5.0, 401, 500),
    ],
}


def get_aqi_category(aqi_value: Optional[int]) -> Optional[str]:
    """
    Returns the official CPCB NAQI category for a given AQI integer.
    """
    if aqi_value is None:
        return None
    if aqi_value <= 50:
        return AQICategory.GOOD.value
    elif aqi_value <= 100:
        return AQICategory.SATISFACTORY.value
    elif aqi_value <= 200:
        return AQICategory.MODERATE.value
    elif aqi_value <= 300:
        return AQICategory.POOR.value
    elif aqi_value <= 400:
        return AQICategory.VERY_POOR.value
    else:
        return AQICategory.SEVERE.value


def calculate_sub_index(pollutant: str, concentration: Optional[float]) -> Tuple[Optional[int], Optional[str]]:
    """
    Calculates the CPCB sub-index for a specific pollutant using linear interpolation:
    Ip = ((Ihi - Ilo) / (BPhi - BPlo)) * (Cp - BPlo) + Ilo

    Returns:
        (sub_index: Optional[int], warning: Optional[str])
    """
    if concentration is None:
        return None, None

    if not isinstance(concentration, (int, float)) or math.isnan(concentration) or math.isinf(concentration):
        return None, f"Non-finite concentration ({concentration}) for {pollutant.upper()} is physically invalid."

    if concentration < 0:
        return None, f"Negative concentration ({concentration}) for {pollutant.upper()} is physically invalid."

    key = pollutant.lower().replace(".", "")
    if key not in CPCB_BREAKPOINTS:
        return None, f"Unsupported pollutant: {pollutant}"

    brackets = CPCB_BREAKPOINTS[key]

    # Check if below lowest breakpoint
    if concentration < brackets[0][0]:
        return 0, None

    # Check if exceeds maximum breakpoint
    max_bp_hi = brackets[-1][1]
    if concentration > max_bp_hi:
        warning = f"{pollutant.upper()} concentration {concentration} exceeds maximum CPCB breakpoint {max_bp_hi}; sub-index capped at 500."
        return 500, warning

    # Find the appropriate breakpoint bracket
    for i, (bp_lo, bp_hi, i_lo, i_hi) in enumerate(brackets):
        # Allow exact inclusion and bridge tiny gaps between discrete CPCB thresholds
        # e.g., if concentration is between bracket[i-1].hi and bracket[i].lo
        in_range = False
        if i == 0:
            in_range = bp_lo <= concentration <= bp_hi
        else:
            prev_bp_hi = brackets[i - 1][1]
            in_range = prev_bp_hi < concentration <= bp_hi

        if in_range:
            # Linear interpolation formula
            bp_range = bp_hi - bp_lo
            i_range = i_hi - i_lo
            sub_index = ((i_range / bp_range) * (concentration - bp_lo)) + i_lo
            return round(sub_index), None

    # Fallback to capping at 500 if edge case
    return 500, f"{pollutant.upper()} concentration {concentration} fell outside standard brackets; capped at 500."
