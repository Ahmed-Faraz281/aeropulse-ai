import math
from typing import Optional, Tuple
from backend.app.models.air_quality import QualityStatus
from backend.app.schemas.air_quality import AirQualityReadingCreate


def validate_reading_data(
    data: AirQualityReadingCreate,
) -> Tuple[QualityStatus, Optional[str]]:
    """
    Evaluates physical plausibility and integrity of an air quality reading.
    Returns (QualityStatus, reason_notes).
    Does NOT discard records; classifies them transparently.
    """
    reasons = []
    is_invalid = False
    is_warning = False

    # 1. Negative pollutant values check (Strictly INVALID)
    pollutant_checks = {
        "PM2.5": data.pm25,
        "PM10": data.pm10,
        "CO": data.co,
        "NO2": data.no2,
        "SO2": data.so2,
        "O3": data.o3,
    }

    for name, val in pollutant_checks.items():
        if val is not None:
            if not isinstance(val, (int, float)) or math.isnan(val) or math.isinf(val):
                is_invalid = True
                reasons.append(f"Non-finite {name} value ({val})")
            elif val < 0:
                is_invalid = True
                reasons.append(f"Negative {name} value ({val})")
            elif name == "PM2.5" and val > 1000:
                is_warning = True
                reasons.append(f"Unusually high PM2.5 concentration ({val} µg/m³)")
            elif name == "PM10" and val > 2000:
                is_warning = True
                reasons.append(f"Unusually high PM10 concentration ({val} µg/m³)")
            elif name == "CO" and val > 150:
                is_warning = True
                reasons.append(f"Unusually high CO concentration ({val} mg/m³)")

    # 2. Humidity bounds check
    if data.humidity is not None:
        if not isinstance(data.humidity, (int, float)) or math.isnan(data.humidity) or math.isinf(data.humidity):
            is_invalid = True
            reasons.append(f"Non-finite humidity value ({data.humidity})")
        elif data.humidity < 0 or data.humidity > 100:
            is_invalid = True
            reasons.append(f"Humidity ({data.humidity}%) outside valid range (0-100%)")

    # 3. Temperature plausibility check
    if data.temperature is not None:
        if not isinstance(data.temperature, (int, float)) or math.isnan(data.temperature) or math.isinf(data.temperature):
            is_invalid = True
            reasons.append(f"Non-finite temperature value ({data.temperature})")
        elif data.temperature < -60 or data.temperature > 65:
            is_warning = True
            reasons.append(f"Extreme environmental temperature ({data.temperature} °C)")

    # 4. Check that at least one measurement is present
    all_measurements = [
        data.pm25,
        data.pm10,
        data.co,
        data.no2,
        data.so2,
        data.o3,
        data.temperature,
        data.humidity,
    ]
    if all(m is None for m in all_measurements):
        is_invalid = True
        reasons.append("Empty reading: all pollutant and environmental fields are null")

    if is_invalid:
        return QualityStatus.INVALID, "; ".join(reasons)
    elif is_warning:
        return QualityStatus.WARNING, "; ".join(reasons)
    return QualityStatus.VALID, None
