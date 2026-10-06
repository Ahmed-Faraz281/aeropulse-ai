"""
What-If Pollution Simulation & Impact Analysis Engine for AeroPulse AI.

Provides interactive, deterministic, explainable, and non-destructive hypothetical
air-quality scenario simulation strictly utilizing the authoritative Phase 4 CPCB NAQI
calculation engine and Phase 11 explainable recommendation rules.
"""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.alert import AlertRule, AlertSeverity, AlertType
from backend.app.models.location import Location
from backend.app.services.aqi_engine import (
    POLLUTANT_LABELS,
    AQIStatus,
    calculate_aqi,
)
from backend.app.services.recommendation_service import generate_recommendations_from_context
from backend.app.schemas.what_if import (
    BaselineState,
    ImpactAnalysis,
    ScenarioState,
    ThresholdImpact,
    WhatIfSimulationRequest,
    WhatIfSimulationResponse,
)

STANDARD_WHAT_IF_DISCLAIMER = (
    "This scenario is a software-simulated hypothetical calculation based on user-adjusted "
    "pollutant parameters and the official CPCB NAQI formula. It does not represent actual "
    "measured observations and does not constitute medical advice."
)


def run_what_if_simulation(
    db: Session,
    request: WhatIfSimulationRequest,
) -> WhatIfSimulationResponse:
    """
    Executes a stateless hypothetical pollutant scenario on the selected monitoring station.
    Strictly non-destructive: zero database modifications performed.
    """
    now = datetime.now(timezone.utc)

    # 1. Fetch Location
    location = db.query(Location).filter(Location.id == request.location_id).first()
    if not location:
        raise HTTPException(
            status_code=404,
            detail=f"Location #{request.location_id} not found.",
        )

    # 2. Fetch baseline reading
    if request.reading_id is not None:
        reading = (
            db.query(AirQualityReading)
            .filter(
                AirQualityReading.id == request.reading_id,
                AirQualityReading.location_id == request.location_id,
            )
            .first()
        )
    else:
        reading = (
            db.query(AirQualityReading)
            .join(AirQualityReading.data_source)
            .filter(
                AirQualityReading.location_id == request.location_id,
                AirQualityReading.quality_status == QualityStatus.VALID,
            )
            .order_by(AirQualityReading.timestamp.desc())
            .first()
        )

    if not reading:
        raise HTTPException(
            status_code=404,
            detail=f"No valid air quality observations available for Location #{request.location_id}.",
        )

    baseline_source_str = (
        reading.data_source.source_type.value
        if reading.data_source and reading.data_source.source_type
        else "API"
    )

    # 3. Extract baseline pollutant concentrations (strict NULL preservation)
    base_pollutants: Dict[str, Optional[float]] = {
        "pm25": reading.pm25,
        "pm10": reading.pm10,
        "no2": reading.no2,
        "so2": reading.so2,
        "co": reading.co,
        "o3": reading.o3,
        "nh3": getattr(reading, "nh3", None),
        "pb": getattr(reading, "pb", None),
    }

    # 4. Validate pollutant change parameters
    pollutant_changes_normalized: Dict[str, float] = {}
    for k, pct in request.pollutant_changes.items():
        k_norm = k.strip().lower()
        if k_norm not in POLLUTANT_LABELS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid pollutant '{k}'. Supported pollutants: {', '.join(POLLUTANT_LABELS.values())}",
            )
        if pct is None or math.isnan(pct) or math.isinf(pct):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid percentage change for {POLLUTANT_LABELS[k_norm]}: value cannot be NaN or infinite.",
            )
        if pct < -100.0 or pct > 500.0:
            raise HTTPException(
                status_code=400,
                detail=f"Percentage change for {POLLUTANT_LABELS[k_norm]} ({pct}%) must be between -100% and +500%.",
            )
        pollutant_changes_normalized[k_norm] = float(pct)

    # 5. NULL Safety Check (Requirement 9):
    # If the required pollutant is NULL in baseline: reject modification with explicit message.
    for k_norm, pct in pollutant_changes_normalized.items():
        label = POLLUTANT_LABELS[k_norm]
        if base_pollutants.get(k_norm) is None:
            raise HTTPException(
                status_code=400,
                detail=f"{label} is unavailable for the selected observation, so this scenario cannot be calculated.",
            )

    # 6. Compute baseline AQI via authoritative Phase 4 CPCB engine
    base_calc = calculate_aqi(
        pm25=base_pollutants["pm25"],
        pm10=base_pollutants["pm10"],
        no2=base_pollutants["no2"],
        so2=base_pollutants["so2"],
        co=base_pollutants["co"],
        o3=base_pollutants["o3"],
        nh3=base_pollutants["nh3"],
        pb=base_pollutants["pb"],
        timestamp=reading.timestamp,
    )

    if base_calc.status == AQIStatus.INSUFFICIENT_DATA:
        raise HTTPException(
            status_code=400,
            detail=f"Baseline observation has insufficient data for CPCB NAQI calculation: {base_calc.message}",
        )
    if base_calc.status == AQIStatus.INVALID_DATA:
        raise HTTPException(
            status_code=400,
            detail=f"Baseline observation has invalid data: {base_calc.message}",
        )

    # 7. Apply percentage changes to produce simulated pollutant state
    modified_pollutants: Dict[str, Optional[float]] = dict(base_pollutants)
    for k_norm, pct in pollutant_changes_normalized.items():
        base_val = base_pollutants[k_norm]
        if base_val is not None:
            new_val = max(0.0, base_val * (1.0 + pct / 100.0))
            modified_pollutants[k_norm] = round(new_val, 3)

    # 8. Compute simulated AQI strictly via authoritative Phase 4 CPCB engine
    sim_calc = calculate_aqi(
        pm25=modified_pollutants["pm25"],
        pm10=modified_pollutants["pm10"],
        no2=modified_pollutants["no2"],
        so2=modified_pollutants["so2"],
        co=modified_pollutants["co"],
        o3=modified_pollutants["o3"],
        nh3=modified_pollutants["nh3"],
        pb=modified_pollutants["pb"],
        timestamp=reading.timestamp,
    )

    if sim_calc.status != AQIStatus.CALCULATED:
        raise HTTPException(
            status_code=400,
            detail=f"Simulated scenario could not be calculated: {sim_calc.message}",
        )

    # 9. Calculate Impact Analysis
    aqi_delta = (sim_calc.aqi - base_calc.aqi) if (sim_calc.aqi is not None and base_calc.aqi is not None) else None
    aqi_percent_delta = None
    if aqi_delta is not None:
        if base_calc.aqi and base_calc.aqi > 0:
            aqi_percent_delta = round((aqi_delta / base_calc.aqi) * 100.0, 2)
        elif aqi_delta == 0:
            aqi_percent_delta = 0.0

    cat_before = base_calc.category
    cat_after = sim_calc.category
    cat_transition = (
        f"{cat_before} → {cat_after}"
        if cat_before != cat_after
        else f"Unchanged ({cat_before})"
    )

    dom_before = base_calc.dominant_pollutant
    dom_after = sim_calc.dominant_pollutant
    dom_transition = (
        f"Changed from {dom_before} to {dom_after}"
        if dom_before != dom_after
        else f"Dominant pollutant remains {dom_before}."
    )

    if aqi_delta is not None:
        if aqi_delta < 0:
            direction = "IMPROVED"
        elif aqi_delta > 0:
            direction = "WORSENED"
        else:
            direction = "UNCHANGED"
    else:
        direction = "UNCHANGED"

    # 10. Stateless Threshold Impact against active Alert Rules (read-only in-memory check)
    threshold_impact: Optional[ThresholdImpact] = None
    enabled_rules = (
        db.query(AlertRule)
        .filter(
            AlertRule.enabled == True,
            AlertRule.alert_type == AlertType.AQI_THRESHOLD,
        )
        .all()
    )

    crossed_rules = []
    if sim_calc.aqi is not None and base_calc.aqi is not None:
        for r in enabled_rules:
            if base_calc.aqi < r.threshold <= sim_calc.aqi:
                crossed_rules.append(r)

    if crossed_rules:
        # Prioritize highest threshold crossed
        crossed_rules.sort(key=lambda r: r.threshold, reverse=True)
        top_rule = crossed_rules[0]
        threshold_impact = ThresholdImpact(
            crosses_threshold=True,
            rule_name=top_rule.name,
            threshold_value=top_rule.threshold,
            severity=top_rule.severity.value,
            message=f"Scenario crosses the {top_rule.name} threshold (Simulated AQI {sim_calc.aqi} >= {top_rule.threshold:.0f}).",
        )
    else:
        # Check standard CPCB boundaries if no custom rule matched
        if base_calc.aqi is not None and sim_calc.aqi is not None:
            if base_calc.aqi < 201 <= sim_calc.aqi:
                threshold_impact = ThresholdImpact(
                    crosses_threshold=True,
                    rule_name="Poor AQI Threshold",
                    threshold_value=201.0,
                    severity="HIGH",
                    message=f"Scenario crosses the Poor AQI threshold (Simulated AQI {sim_calc.aqi} >= 201).",
                )
            elif base_calc.aqi < 401 <= sim_calc.aqi:
                threshold_impact = ThresholdImpact(
                    crosses_threshold=True,
                    rule_name="Severe AQI Threshold",
                    threshold_value=401.0,
                    severity="CRITICAL",
                    message=f"Scenario crosses the Severe AQI emergency threshold (Simulated AQI {sim_calc.aqi} >= 401).",
                )
            else:
                threshold_impact = ThresholdImpact(
                    crosses_threshold=False,
                    message="Simulated AQI does not cross any active alert threshold.",
                )

    # 11. Recalculate Preventive Recommendations via Phase 11 Engine
    scenario_recommendations = generate_recommendations_from_context(
        location_id=request.location_id,
        current_aqi=sim_calc.aqi,
        current_category=sim_calc.category,
        dominant_pollutant=sim_calc.dominant_pollutant,
        pollutants=modified_pollutants,
        source_type_str="WHAT_IF / SIMULATED",
        trend_str=None,
        latest_pred=None,
        active_alerts=[],
        is_simulated_scenario=True,
    )

    # 12. Build response components
    baseline_state = BaselineState(
        location_id=location.id,
        location_name=location.name,
        city=location.city,
        timestamp=reading.timestamp,
        source_type=baseline_source_str,
        pollutant_values=base_pollutants,
        pollutant_subindices=base_calc.pollutant_subindices,
        aqi=base_calc.aqi,
        category=base_calc.category,
        dominant_pollutant=base_calc.dominant_pollutant,
    )

    scenario_state = ScenarioState(
        modified_pollutant_values=modified_pollutants,
        pollutant_changes_percent=pollutant_changes_normalized,
        pollutant_subindices=sim_calc.pollutant_subindices,
        simulated_aqi=sim_calc.aqi,
        category=sim_calc.category,
        dominant_pollutant=sim_calc.dominant_pollutant,
        provenance="WHAT_IF / SIMULATED",
        is_valid=True,
        warnings=sim_calc.warnings,
        message=sim_calc.message,
    )

    impact_state = ImpactAnalysis(
        aqi_delta=aqi_delta,
        aqi_percent_delta=aqi_percent_delta,
        category_before=cat_before,
        category_after=cat_after,
        category_transition=cat_transition,
        dominant_pollutant_before=dom_before,
        dominant_pollutant_after=dom_after,
        dominant_pollutant_transition=dom_transition,
        direction=direction,
        threshold_impact=threshold_impact,
    )

    return WhatIfSimulationResponse(
        baseline=baseline_state,
        scenario=scenario_state,
        impact=impact_state,
        recommendations=scenario_recommendations,
        calculation_method="CPCB_INDIA_V1",
        generated_at=now,
        baseline_provenance=baseline_source_str,
        scenario_provenance="WHAT_IF / SIMULATED",
        disclaimer=STANDARD_WHAT_IF_DISCLAIMER,
    )
