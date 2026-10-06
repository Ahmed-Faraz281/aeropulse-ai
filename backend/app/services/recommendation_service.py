"""
Prevention & Explainable Recommendation Engine for AeroPulse AI.

Converts multi-source air quality telemetry, CPCB NAQI assessments, dominant pollutant
characteristics, temporal trends, ML forecasts, and active threshold alerts into practical,
deterministic, explainable preventive guidance.

Positioning: Software-only analytics based on available monitoring-station observations.
Not medical advice. Preserves data provenance throughout.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.models.prediction import PredictionRecord
from backend.app.models.alert import Alert, AlertStatus, AlertSeverity
from backend.app.services.analytics import compute_trend_direction, TrendDirection
from backend.app.schemas.recommendation import (
    RecommendationType,
    RecommendationPriority,
    RecommendationItem,
    ForecastContext,
    LocationRecommendationsResponse,
)

STANDARD_DISCLAIMER = (
    "Recommendations are informational and based on available air-quality data. "
    "They are not medical advice. Follow official public-health guidance for your situation."
)

PRIORITY_WEIGHTS = {
    RecommendationPriority.CRITICAL: 5,
    RecommendationPriority.HIGH: 4,
    RecommendationPriority.MEDIUM: 3,
    RecommendationPriority.LOW: 2,
    RecommendationPriority.INFO: 1,
}


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

def _get_pollutant(p_source: Any, key: str) -> Optional[float]:
    if p_source is None:
        return None
    if isinstance(p_source, dict):
        return p_source.get(key)
    return getattr(p_source, key, None)


def generate_recommendations_from_context(
    location_id: int,
    current_aqi: Optional[int],
    current_category: Optional[str],
    dominant_pollutant: Optional[str],
    pollutants: Optional[Any] = None,
    source_type_str: str = "API",
    trend_str: Optional[str] = None,
    latest_pred: Optional[PredictionRecord] = None,
    active_alerts: Optional[List[Alert]] = None,
    is_simulated_scenario: bool = False,
) -> List[RecommendationItem]:
    """
    Core deterministic rule matrix producing prioritized, explainable prevention
    recommendations for either a live observation or a hypothetical What-If scenario.
    """
    if is_simulated_scenario:
        source_type_str = "WHAT_IF / SIMULATED"
    active_alerts = active_alerts or []

    recs: List[RecommendationItem] = []

    if current_aqi is not None and current_category:
        cat_lower = current_category.lower()

        # A. CPCB Category Rules
        if cat_lower == "good" or current_aqi <= 50:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_good",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Outdoor Activities Suitable",
                    action="Outdoor activities are suitable; enjoy outdoor recreation and physical exercise freely.",
                    message="Air quality is in the Good range, presenting minimal risk.",
                    severity="INFO",
                    priority=RecommendationPriority.INFO,
                    reason=f"Current AQI is {current_aqi} ({current_category}), indicating clean ambient air.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_ventilation_good",
                    type=RecommendationType.VENTILATION,
                    title="Natural Ventilation Suitable",
                    action="Keep windows and vents open for natural indoor air exchange.",
                    message="Outdoor ambient air is fresh and ideal for flushing indoor stale air.",
                    severity="INFO",
                    priority=RecommendationPriority.INFO,
                    reason=f"Outdoor AQI is {current_aqi}, well within clean air thresholds.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        elif cat_lower == "satisfactory" or current_aqi <= 100:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_satisfactory",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Normal Outdoor Routine Suitable",
                    action="Continue normal outdoor activities as planned.",
                    message="Air quality is acceptable for the general population.",
                    severity="INFO",
                    priority=RecommendationPriority.INFO,
                    reason=f"Current AQI is {current_aqi} ({current_category}), indicating acceptable air quality.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_caution_satisfactory",
                    type=RecommendationType.HIGH_RISK_GROUP_CAUTION,
                    title="Sensitive Groups Caution",
                    action="People who are more sensitive to air pollution may wish to take additional precautions if experiencing mild discomfort.",
                    message="A small number of sensitive individuals may experience minor breathing irritation.",
                    severity="LOW",
                    priority=RecommendationPriority.LOW,
                    reason=f"AQI is {current_aqi} ({current_category}); individuals with respiratory sensitivity may notice mild effects.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        elif cat_lower == "moderate" or current_aqi <= 200:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_moderate",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Reduce Heavy Outdoor Exertion",
                    action="Reduce prolonged or heavy outdoor physical exertion; take frequent rest breaks.",
                    message="Breathing discomfort may be experienced by sensitive groups upon extended exertion.",
                    severity="WARNING",
                    priority=RecommendationPriority.LOW,
                    reason=f"Current AQI is {current_aqi} ({current_category}); prolonged outdoor exertion may cause breathing discomfort.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_caution_moderate",
                    type=RecommendationType.HIGH_RISK_GROUP_CAUTION,
                    title="Precautions for Sensitive Demographics",
                    action="People with existing respiratory conditions or cardiovascular sensitivity should limit prolonged outdoor exposure.",
                    message="Moderate air quality can trigger mild discomfort in susceptible individuals.",
                    severity="WARNING",
                    priority=RecommendationPriority.MEDIUM,
                    reason=f"Current AQI of {current_aqi} falls in the Moderate category.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_ventilation_moderate",
                    type=RecommendationType.VENTILATION,
                    title="Timed Indoor Ventilation",
                    action="Open windows selectively during low-traffic afternoon hours and keep closed during morning rush.",
                    message="Manage indoor airflow to minimize traffic-related particulate entry.",
                    severity="INFO",
                    priority=RecommendationPriority.LOW,
                    reason=f"AQI is {current_aqi} ({current_category}); ambient air contains moderate pollutant levels.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        elif cat_lower == "poor" or current_aqi <= 300:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_poor",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Postpone Strenuous Outdoor Exercise",
                    action="Postpone strenuous outdoor exercise or move physical activities indoors.",
                    message="Prolonged outdoor exposure can cause breathing discomfort to most people.",
                    severity="WARNING",
                    priority=RecommendationPriority.MEDIUM,
                    reason=f"Current AQI is {current_aqi} ({current_category}); breathing discomfort is likely upon prolonged exposure.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_mask_poor",
                    type=RecommendationType.MASK_GUIDANCE,
                    title="Wear N95/FFP2 Mask Outdoors",
                    action="Wear an N95 or equivalent particulate-filtering mask when prolonged outdoor transit cannot be avoided.",
                    message="Particulate concentrations are elevated in the Poor AQI range.",
                    severity="WARNING",
                    priority=RecommendationPriority.MEDIUM,
                    reason=f"Current AQI is {current_aqi} ({current_category}) with elevated particulate matter.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_exposure_poor",
                    type=RecommendationType.EXPOSURE_REDUCTION,
                    title="Reduce Outdoor Exposure Duration",
                    action="Minimize non-essential outdoor transit and prefer cleaner indoor environments.",
                    message="Limit time spent in traffic corridors or outdoor public spaces.",
                    severity="WARNING",
                    priority=RecommendationPriority.MEDIUM,
                    reason=f"AQI is {current_aqi} ({current_category}).",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        elif cat_lower == "very poor" or current_aqi <= 400:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_very_poor",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Avoid Strenuous Outdoor Physical Work",
                    action="Avoid strenuous outdoor physical activities, jogging, and intense outdoor sports.",
                    message="Very Poor air quality poses severe respiratory risks on prolonged exposure.",
                    severity="HIGH",
                    priority=RecommendationPriority.HIGH,
                    reason=f"Current AQI is {current_aqi} ({current_category}); respiratory illness on prolonged exposure is likely.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_exposure_very_poor",
                    type=RecommendationType.EXPOSURE_REDUCTION,
                    title="Minimize Outdoor Exposure",
                    action="Remain indoors in cleaner air environments whenever possible.",
                    message="Keep exposure to ambient air as brief as possible.",
                    severity="HIGH",
                    priority=RecommendationPriority.HIGH,
                    reason=f"AQI is {current_aqi} ({current_category}), representing hazardous exposure levels.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_indoor_very_poor",
                    type=RecommendationType.INDOOR_AIR,
                    title="Run Indoor Air Filtration",
                    action="Run indoor HEPA air purifiers and ensure windows and doors remain closed.",
                    message="Prevent infiltration of highly polluted ambient air into living and working spaces.",
                    severity="HIGH",
                    priority=RecommendationPriority.HIGH,
                    reason=f"Outdoor AQI of {current_aqi} poses significant particulate infiltration risks.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_mask_very_poor",
                    type=RecommendationType.MASK_GUIDANCE,
                    title="N95/FFP2 Mask Mandatory Outdoors",
                    action="Always wear a well-fitted N95, KN95, or FFP2 certified particulate respirator if stepping outside.",
                    message="Standard surgical and cloth masks offer negligible protection against high fine-particulate concentrations.",
                    severity="HIGH",
                    priority=RecommendationPriority.HIGH,
                    reason=f"Very Poor AQI ({current_aqi}) requires certified particulate filtration.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_caution_very_poor",
                    type=RecommendationType.HIGH_RISK_GROUP_CAUTION,
                    title="Strict Confinement for Vulnerable Groups",
                    action="Children, elderly individuals, and patients with asthma, COPD, or coronary artery disease should remain strictly indoors.",
                    message="Ambient air at this level triggers acute exacerbations of cardiopulmonary conditions.",
                    severity="CRITICAL",
                    priority=RecommendationPriority.HIGH,
                    reason=f"Current AQI is {current_aqi} ({current_category}); vulnerable individuals are at critical risk.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        elif cat_lower == "severe" or current_aqi > 400:
            recs.append(
                RecommendationItem(
                    id="rec_outdoor_severe",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Strictly Avoid All Outdoor Physical Activity",
                    action="Strictly avoid any outdoor physical activity, transit, or exertion. Severe pollution emergency protocol applies.",
                    message="Ambient air quality presents severe risks to the entire population.",
                    severity="CRITICAL",
                    priority=RecommendationPriority.CRITICAL,
                    reason=f"Current AQI is {current_aqi} (Severe emergency level).",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_exposure_severe",
                    type=RecommendationType.EXPOSURE_REDUCTION,
                    title="Remain in Filtered Indoor Spaces",
                    action="Seal windows and doors against ambient infiltration; follow official government air advisories.",
                    message="Create a clean-air sanctuary indoors with air cleaning equipment.",
                    severity="CRITICAL",
                    priority=RecommendationPriority.CRITICAL,
                    reason=f"AQI of {current_aqi} is in the Severe category.",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )
            recs.append(
                RecommendationItem(
                    id="rec_indoor_severe",
                    type=RecommendationType.INDOOR_AIR,
                    title="Continuous Indoor HEPA Filtration",
                    action="Run HEPA purifiers continuously and avoid indoor combustion activities (incense, frying, candles).",
                    message="Maintain maximum indoor particle clearance efficiency.",
                    severity="CRITICAL",
                    priority=RecommendationPriority.CRITICAL,
                    reason=f"Severe outdoor ambient AQI ({current_aqi}).",
                    triggered_by="AQI_CATEGORY",
                    supporting_data={"aqi": current_aqi, "category": current_category},
                    source_type=source_type_str,
                    location_id=location_id,
                    category=current_category,
                )
            )

        # B. Dominant Pollutant Targeted Rules
        if dominant_pollutant and pollutants is not None:
            dom = dominant_pollutant.lower()
            pm25_val = _get_pollutant(pollutants, "pm25")
            pm10_val = _get_pollutant(pollutants, "pm10")
            no2_val = _get_pollutant(pollutants, "no2")
            o3_val = _get_pollutant(pollutants, "o3")
            co_val = _get_pollutant(pollutants, "co")
            so2_val = _get_pollutant(pollutants, "so2")

            if dom == "pm25" and pm25_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_pm25",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="PM2.5 Particulate Filtration",
                        action="Prioritize high-efficiency particulate air filtration (HEPA) to capture respirable fine particles.",
                        message="Fine PM2.5 penetrates deeply into the lungs; particle-certified filtration is most effective.",
                        severity="HIGH" if current_aqi > 300 else "WARNING",
                        priority=RecommendationPriority.HIGH if current_aqi > 300 else RecommendationPriority.MEDIUM,
                        reason=f"PM2.5 is the dominant pollutant ({pm25_val:.1f} µg/m³), which penetrates deep into the respiratory tract.",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "PM2.5", "concentration": pm25_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="PM2.5",
                    )
                )
            elif dom == "pm10" and pm10_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_pm10",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="PM10 Coarse Dust Abatement",
                        action="Perform indoor dust suppression using damp mopping rather than dry sweeping; avoid unpaved or construction routes.",
                        message="Coarse dust easily resuspends; damp cleaning prevents indoor particle agitation.",
                        severity="HIGH" if current_aqi > 300 else "WARNING",
                        priority=RecommendationPriority.HIGH if current_aqi > 300 else RecommendationPriority.MEDIUM,
                        reason=f"PM10 is the dominant pollutant ({pm10_val:.1f} µg/m³), consisting predominantly of coarse dust and road debris.",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "PM10", "concentration": pm10_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="PM10",
                    )
                )
            elif dom == "no2" and no2_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_no2",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="NO2 Traffic Corridor Avoidance",
                        action="Avoid transit through congested traffic corridors and busy intersections during peak rush hours.",
                        message="Nitrogen Dioxide accumulates near heavy diesel and vehicle combustion zones.",
                        severity="WARNING",
                        priority=RecommendationPriority.MEDIUM,
                        reason=f"Nitrogen Dioxide (NO2) is the dominant pollutant ({no2_val:.1f} µg/m³), primarily produced by vehicle combustion.",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "NO2", "concentration": no2_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="NO2",
                    )
                )
            elif dom == "o3" and o3_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_o3",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="Ozone Photochemical Peak Timing",
                        action="Reschedule strenuous outdoor activities to morning or evening hours; avoid peak afternoon sun exposure.",
                        message="Ground-level ozone forms through photochemical reactions in intense sunlight (12:00-16:00).",
                        severity="WARNING",
                        priority=RecommendationPriority.MEDIUM,
                        reason=f"Ground-level Ozone (O3) is the dominant pollutant ({o3_val:.1f} µg/m³), peaking during afternoon photochemical hours.",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "O3", "concentration": o3_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="O3",
                    )
                )
            elif dom == "co" and co_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_co",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="CO Combustion Ventilation Safety",
                        action="Ensure thorough ventilation around all indoor combustion appliances; never operate engines in enclosed areas.",
                        message="Carbon monoxide interferes with oxygen delivery; maintain proper ventilation.",
                        severity="WARNING",
                        priority=RecommendationPriority.MEDIUM,
                        reason=f"Carbon Monoxide (CO) is the dominant pollutant ({co_val:.1f} mg/m³).",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "CO", "concentration": co_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="CO",
                    )
                )
            elif dom == "so2" and so2_val is not None:
                recs.append(
                    RecommendationItem(
                        id="rec_pollutant_so2",
                        type=RecommendationType.POLLUTANT_SPECIFIC,
                        title="SO2 Industrial Emission Precaution",
                        action="Minimize outdoor exposure downwind of industrial or combustion facilities; close windows.",
                        message="Sulfur dioxide is an irritating gas from fuel combustion and industrial processes.",
                        severity="WARNING",
                        priority=RecommendationPriority.MEDIUM,
                        reason=f"Sulfur Dioxide (SO2) is the dominant pollutant ({so2_val:.1f} µg/m³).",
                        triggered_by="DOMINANT_POLLUTANT",
                        supporting_data={"dominant_pollutant": "SO2", "concentration": so2_val},
                        source_type=source_type_str,
                        location_id=location_id,
                        dominant_pollutant="SO2",
                    )
                )

        # C. Trend-Aware Rules
        if trend_str == "INCREASING":
            recs.append(
                RecommendationItem(
                    id="rec_trend_increasing",
                    type=RecommendationType.TRAVEL_TIMING,
                    title="Deteriorating Pollution Trend Notice",
                    action="Complete outdoor errands promptly or postpone non-urgent tasks as air quality is worsening.",
                    message="Recent hours exhibit an increasing AQI trajectory; conditions may degrade further.",
                    severity="WARNING",
                    priority=RecommendationPriority.MEDIUM,
                    reason="AQI trend analysis indicates increasing pollutant concentration over the recent evaluation window.",
                    triggered_by="TREND",
                    supporting_data={"trend": "INCREASING", "current_aqi": current_aqi},
                    source_type=source_type_str,
                    location_id=location_id,
                )
            )
        elif trend_str == "DECREASING":
            recs.append(
                RecommendationItem(
                    id="rec_trend_decreasing",
                    type=RecommendationType.OUTDOOR_ACTIVITY,
                    title="Improving Air Quality Trend",
                    action="Atmospheric dispersal is underway; continue monitoring AQI before planning extended outdoor exercise.",
                    message="Pollutant concentrations are decreasing; maintain awareness until clean baseline stabilizes.",
                    severity="INFO",
                    priority=RecommendationPriority.LOW,
                    reason="AQI trend analysis indicates a decreasing trend over the recent evaluation window.",
                    triggered_by="TREND",
                    supporting_data={"trend": "DECREASING", "current_aqi": current_aqi},
                    source_type=source_type_str,
                    location_id=location_id,
                )
            )

    # D. Prediction-Aware Forecast Prevention (Phase 9)
    if latest_pred:
        pred_aqi = latest_pred.predicted_aqi
        pred_cat = latest_pred.predicted_category
        horizon = latest_pred.horizon_hours

        if current_aqi is not None and (pred_aqi > current_aqi or pred_cat in ["Poor", "Very Poor", "Severe"]):
            prio = RecommendationPriority.CRITICAL if pred_aqi >= 401 else (RecommendationPriority.HIGH if pred_aqi >= 301 else RecommendationPriority.MEDIUM)
            recs.append(
                RecommendationItem(
                    id="rec_forecast_worsening",
                    type=RecommendationType.FORECAST_PREVENTION,
                    title=f"Forecast Warning: Conditions Expected to Degrade ({horizon}h)",
                    action=f"Consider scheduling prolonged outdoor activities earlier. AQI is predicted to reach {pred_aqi:.0f} ({pred_cat}) in {horizon}h.",
                    message=f"Machine learning models project a shift toward {pred_cat} conditions within the {horizon}-hour window.",
                    severity="HIGH" if pred_aqi >= 301 else "WARNING",
                    priority=prio,
                    reason=f"Machine learning forecast predicts a transition from {current_category or 'Current'} (AQI {current_aqi}) to {pred_cat} (AQI {pred_aqi:.0f}) within {horizon} hours.",
                    triggered_by="FORECAST",
                    supporting_data={
                        "horizon_hours": horizon,
                        "predicted_aqi": pred_aqi,
                        "predicted_category": pred_cat,
                    },
                    source_type="PREDICTED",
                    location_id=location_id,
                    forecast_based=True,
                )
            )
        elif current_aqi is not None and pred_aqi < current_aqi and current_aqi > 200:
            recs.append(
                RecommendationItem(
                    id="rec_forecast_recovery",
                    type=RecommendationType.FORECAST_PREVENTION,
                    title=f"Forecast Notification: Atmospheric Clearing Expected ({horizon}h)",
                    action=f"Air quality is forecast to improve towards AQI {pred_aqi:.0f} ({pred_cat}) in {horizon}h. Maintain current indoor precautions until verified.",
                    message=f"Anticipated dispersion may reduce AQI to {pred_aqi:.0f} within {horizon} hours.",
                    severity="INFO",
                    priority=RecommendationPriority.LOW,
                    reason=f"Machine learning forecast predicts improvement to {pred_cat} (AQI {pred_aqi:.0f}) in {horizon} hours.",
                    triggered_by="FORECAST",
                    supporting_data={
                        "horizon_hours": horizon,
                        "predicted_aqi": pred_aqi,
                        "predicted_category": pred_cat,
                    },
                    source_type="PREDICTED",
                    location_id=location_id,
                    forecast_based=True,
                )
            )

    # E. Alert-Aware Rules (Phase 10)
    for alert in active_alerts:
        alert_prio = (
            RecommendationPriority.CRITICAL
            if alert.severity == AlertSeverity.CRITICAL
            else (RecommendationPriority.HIGH if alert.severity == AlertSeverity.HIGH else RecommendationPriority.MEDIUM)
        )
        recs.append(
            RecommendationItem(
                id=f"rec_alert_{alert.id}",
                type=RecommendationType.ALERT_RESPONSE,
                title=f"Active Alert Response: {alert.title}",
                action=f"Take immediate protective precautions: {alert.message}",
                message=f"System alert is actively triggered for {alert.alert_type.value}.",
                severity=alert.severity.value,
                priority=alert_prio,
                reason=f"Active {alert.alert_type.value} alert detected at {alert.detected_at.strftime('%H:%M UTC')} with observed value {alert.observed_value:.0f}.",
                triggered_by="ACTIVE_ALERT",
                supporting_data={
                    "alert_id": alert.id,
                    "alert_type": alert.alert_type.value,
                    "observed_value": alert.observed_value,
                    "threshold": alert.threshold_value,
                },
                source_type=alert.source_type or source_type_str,
                location_id=location_id,
            )
        )

    # 7. Deduplication: Consolidate items with identical actions or core intent
    deduped_recs: List[RecommendationItem] = []
    seen_actions = set()

    for item in recs:
        action_key = item.action.strip().lower()
        if action_key not in seen_actions:
            seen_actions.add(action_key)
            deduped_recs.append(item)
        else:
            # If seen, keep the one with higher priority
            existing_idx = next(i for i, r in enumerate(deduped_recs) if r.action.strip().lower() == action_key)
            if PRIORITY_WEIGHTS[item.priority] > PRIORITY_WEIGHTS[deduped_recs[existing_idx].priority]:
                deduped_recs[existing_idx] = item

    # 8. Deterministic Sorting: Priority descending, then ID ascending
    deduped_recs.sort(key=lambda r: (-PRIORITY_WEIGHTS[r.priority], r.id))

    return deduped_recs


def evaluate_location_recommendations(
    db: Session,
    location_id: int,
    include_forecast: bool = True,
    include_alerts: bool = True,
    horizon_hours: Optional[int] = None,
) -> LocationRecommendationsResponse:
    """
    Evaluates and generates deterministic, explainable prevention recommendations
    for a monitored station location.
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    location_name = location.name if location else f"Station #{location_id}"
    city_name = location.city if location else "Unknown"

    now = datetime.now(timezone.utc)

    # 1. Fetch latest reading and joined data source
    latest_reading = (
        db.query(AirQualityReading)
        .join(AirQualityReading.data_source)
        .filter(
            AirQualityReading.location_id == location_id,
            AirQualityReading.quality_status == QualityStatus.VALID,
        )
        .order_by(AirQualityReading.timestamp.desc())
        .first()
    )

    # 2. Fetch latest AQI record
    latest_aqi_rec = (
        db.query(AQIRecord)
        .filter(AQIRecord.location_id == location_id)
        .order_by(AQIRecord.timestamp.desc())
        .first()
    )

    source_type_str = "API"
    has_simulated = False
    if latest_reading and latest_reading.data_source:
        source_type_str = latest_reading.data_source.source_type.value
        has_simulated = latest_reading.data_source.source_type == SourceType.SIMULATED

    current_aqi = latest_aqi_rec.aqi if latest_aqi_rec else None
    current_category = latest_aqi_rec.category if latest_aqi_rec else None
    dominant_pollutant = latest_aqi_rec.dominant_pollutant if latest_aqi_rec else None

    # 3. Compute recent trend (past 24h vs previous 24h)
    trend_str = "STABLE"
    past_aqi_records = (
        db.query(AQIRecord)
        .filter(
            AQIRecord.location_id == location_id,
            AQIRecord.timestamp >= now - timedelta(hours=48),
        )
        .order_by(AQIRecord.timestamp.asc())
        .all()
    )

    if len(past_aqi_records) >= 3:
        valid_aqis = [r.aqi for r in past_aqi_records if r.aqi is not None]
        if len(valid_aqis) >= 2:
            half = len(valid_aqis) // 2
            baseline = valid_aqis[:half]
            recent = valid_aqis[half:]
            trend_dir = compute_trend_direction(recent, baseline)
            if trend_dir == TrendDirection.INCREASING:
                trend_str = "INCREASING"
            elif trend_dir == TrendDirection.DECREASING:
                trend_str = "DECREASING"
            elif trend_dir == TrendDirection.STABLE:
                trend_str = "STABLE"

    # 4. Fetch prediction context (Phase 9)
    forecast_ctx: Optional[ForecastContext] = None
    latest_pred: Optional[PredictionRecord] = None
    if include_forecast:
        pred_query = db.query(PredictionRecord).filter(
            PredictionRecord.location_id == location_id,
            PredictionRecord.target_timestamp >= now - timedelta(hours=1),
        )
        if horizon_hours is not None:
            pred_query = pred_query.filter(PredictionRecord.horizon_hours == horizon_hours)
        latest_pred = pred_query.order_by(PredictionRecord.created_at.desc()).first()

        if latest_pred:
            forecast_ctx = ForecastContext(
                horizon_hours=latest_pred.horizon_hours,
                predicted_aqi=latest_pred.predicted_aqi,
                predicted_category=latest_pred.predicted_category,
                target_timestamp=latest_pred.target_timestamp,
                model_name=latest_pred.model_name or "RandomForestRegressor",
            )

    # 5. Fetch active alerts (Phase 10)
    active_alerts: List[Alert] = []
    if include_alerts:
        active_alerts = (
            db.query(Alert)
            .filter(
                Alert.location_id == location_id,
                Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED]),
            )
            .order_by(Alert.detected_at.desc())
            .all()
        )

    deduped_recs = generate_recommendations_from_context(
        location_id=location_id,
        current_aqi=current_aqi,
        current_category=current_category,
        dominant_pollutant=dominant_pollutant,
        pollutants=latest_reading,
        source_type_str=source_type_str,
        trend_str=trend_str,
        latest_pred=latest_pred,
        active_alerts=active_alerts,
        is_simulated_scenario=False,
    )

    return LocationRecommendationsResponse(
        location_id=location_id,
        location_name=location_name,
        city=city_name,
        assessment_timestamp=now,
        current_aqi=current_aqi,
        current_category=current_category,
        dominant_pollutant=dominant_pollutant,
        trend=trend_str,
        source_type=source_type_str,
        has_simulated_data=has_simulated,
        disclaimer=STANDARD_DISCLAIMER,
        forecast_summary=forecast_ctx,
        active_alerts_count=len(active_alerts),
        recommendations=deduped_recs,
    )
