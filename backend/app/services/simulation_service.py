"""
Simulation Engine Service for AeroPulse AI.
100% Software-Only Synthetic Air Quality Generator.
Strictly identifies all output as SIMULATED provenance.
"""

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.app.models.air_quality import AirQualityReading
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.schemas.air_quality import AirQualityReadingCreate
from backend.app.schemas.simulation import (
    SimulationRequest,
    SimulationResponse,
    SimulationRunMetadata,
    SimulationScenario,
)
from backend.app.services.data_validator import validate_reading_data
from backend.app.services.aqi_engine import calculate_aqi

# Maximum safety threshold for total records per simulation execution
MAX_RECORDS_PER_RUN = 1000

# In-memory record of the most recent simulation run
_latest_simulation_run: Optional[SimulationRunMetadata] = None


def get_latest_simulation_run() -> Optional[SimulationRunMetadata]:
    """Returns metadata of the most recent simulation execution."""
    return _latest_simulation_run


def _get_or_create_simulated_datasource(db: Session) -> DataSource:
    """Retrieves or registers the software simulation data source."""
    source = (
        db.query(DataSource)
        .filter(DataSource.source_type == SourceType.SIMULATED)
        .first()
    )
    if not source:
        source = DataSource(
            name="Software Simulation Engine",
            source_type=SourceType.SIMULATED,
            provider="AeroPulse Deterministic Simulator",
            description="Software-generated synthetic telemetry for testing and validation.",
            is_active=True,
        )
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


def _get_synthetic_baseline(location_id: int) -> Dict[str, float]:
    """
    Derives a synthetic mathematical baseline profile for a station ID.
    IMPORTANT: These profiles are SYNTHETIC CONFIGURATIONS ONLY and do NOT
    represent real or measured pollution levels of physical cities/stations.
    """
    # Deterministic baseline variation derived mathematically from location ID
    base_pm25 = 28.0 + (location_id * 19) % 65
    base_pm10 = base_pm25 * (1.45 + ((location_id * 7) % 5) * 0.08)
    base_no2 = 18.0 + (location_id * 13) % 45
    base_so2 = 7.0 + (location_id * 5) % 18
    base_co = 0.5 + ((location_id * 3) % 12) * 0.1
    base_o3 = 22.0 + (location_id * 11) % 35
    base_temp = 22.0 + (location_id % 9)
    base_humidity = 50.0 + (location_id % 25)

    return {
        "pm25": base_pm25,
        "pm10": base_pm10,
        "no2": base_no2,
        "so2": base_so2,
        "co": base_co,
        "o3": base_o3,
        "temperature": base_temp,
        "humidity": base_humidity,
    }


def _calculate_diurnal_factors(ts: datetime) -> Dict[str, float]:
    """
    Computes realistic time-of-day multipliers based on diurnal atmospheric physics:
    - Morning traffic peak (07:00 - 10:00)
    - Afternoon photochemical peak (12:00 - 16:00)
    - Evening traffic peak (17:30 - 20:30)
    - Nocturnal inversion accumulation (23:00 - 05:00)
    """
    hour_float = ts.hour + ts.minute / 60.0

    # Gaussian peak around morning rush hour (08:30, sigma=1.2)
    m_peak = math.exp(-((hour_float - 8.5) ** 2) / (2 * (1.2 ** 2)))

    # Gaussian peak around evening rush hour (19:00, sigma=1.4)
    e_peak = math.exp(-((hour_float - 19.0) ** 2) / (2 * (1.4 ** 2)))

    # Gaussian peak around solar noon / photochemical activity (14:00, sigma=1.8)
    solar_peak = math.exp(-((hour_float - 14.0) ** 2) / (2 * (1.8 ** 2)))

    # Nocturnal accumulation factor (highest at 03:00, lowest at 14:00)
    nocturnal = 0.5 * (1.0 + math.cos(math.radians((hour_float - 3.0) * 15.0)))

    # Pollutant diurnal modulation factors
    no2_factor = 1.0 + 0.45 * m_peak + 0.40 * e_peak - 0.15 * solar_peak
    co_factor = 1.0 + 0.35 * m_peak + 0.35 * e_peak - 0.10 * solar_peak
    o3_factor = 0.6 + 0.85 * solar_peak - 0.20 * nocturnal
    pm25_factor = 1.0 + 0.25 * m_peak + 0.30 * e_peak + 0.30 * nocturnal - 0.20 * solar_peak
    pm10_factor = 1.0 + 0.20 * m_peak + 0.25 * e_peak + 0.25 * nocturnal - 0.15 * solar_peak
    so2_factor = 1.0 + 0.20 * m_peak + 0.15 * e_peak

    # Meteorology diurnal shifts
    temp_shift = 6.0 * math.sin(math.radians((hour_float - 9.0) * 15.0))
    humidity_shift = -15.0 * math.sin(math.radians((hour_float - 9.0) * 15.0))

    return {
        "pm25": max(0.4, pm25_factor),
        "pm10": max(0.4, pm10_factor),
        "no2": max(0.3, no2_factor),
        "so2": max(0.4, so2_factor),
        "co": max(0.3, co_factor),
        "o3": max(0.2, o3_factor),
        "temp_shift": temp_shift,
        "humidity_shift": humidity_shift,
    }


def _calculate_scenario_multiplier(
    scenario: SimulationScenario,
    progress: float,
    rng: random.Random,
) -> float:
    """
    Calculates scenario progression multiplier across the normalized time window [0.0, 1.0].
    Clarification 2: PERSISTENT_ELEVATED generates sustained elevated concentrations,
    but does NOT force every pollutant into the Severe range; AQI engine independently evaluates category.
    """
    if scenario == SimulationScenario.NORMAL:
        return 1.0 + rng.uniform(-0.05, 0.05)

    elif scenario == SimulationScenario.RISING_POLLUTION:
        # Gradual buildup from baseline to 2.1x
        return 1.0 + 1.1 * progress + rng.uniform(-0.05, 0.05)

    elif scenario == SimulationScenario.POLLUTION_SPIKE:
        # Sharp surge centered at progress = 0.5 (sigma = 0.12)
        spike = math.exp(-((progress - 0.5) ** 2) / (2 * (0.12 ** 2)))
        return 1.0 + 1.8 * spike + rng.uniform(-0.06, 0.06)

    elif scenario == SimulationScenario.PERSISTENT_ELEVATED:
        # Sustained elevated concentrations without forcing artificial Severe bounds
        return 1.85 + rng.uniform(-0.10, 0.10)

    elif scenario == SimulationScenario.RECOVERY:
        # High initial levels gradually clearing towards baseline
        return 2.1 - 1.1 * progress + rng.uniform(-0.05, 0.05)

    return 1.0


def run_simulation(
    req: SimulationRequest,
    db: Session,
) -> SimulationResponse:
    """
    Executes end-to-end software simulation according to configured request.
    Strictly adheres to all safety rules, deterministic seeding, validation, and AQI pipeline.
    """
    started_at = datetime.now(timezone.utc)

    # 1. Backend safety limits check
    total_steps = (req.duration_hours * 60) // req.interval_minutes + 1
    total_potential_readings = total_steps * len(req.location_ids)

    if total_potential_readings > MAX_RECORDS_PER_RUN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Requested simulation would generate {total_potential_readings} readings, "
                f"exceeding the maximum safety limit of {MAX_RECORDS_PER_RUN} records per run. "
                "Please increase interval minutes or decrease duration/station count."
            ),
        )

    # 2. Verify all location IDs exist in database
    existing_locations = (
        db.query(Location)
        .filter(Location.id.in_(req.location_ids))
        .all()
    )
    existing_loc_ids = {loc.id for loc in existing_locations}
    missing_locs = [lid for lid in req.location_ids if lid not in existing_loc_ids]
    if missing_locs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location IDs {missing_locs} do not exist in the system",
        )

    # 3. Initialize Deterministic or Dynamic RNG
    # Clarification 3: ALL randomness used during simulation must strictly come from rng!
    rng = random.Random(req.seed) if req.seed is not None else random.Random()

    # 4. Ensure SIMULATED data source is available
    sim_source = _get_or_create_simulated_datasource(db)

    # 5. Determine temporal sequence
    # End time is aligned to current rounded 15-minute interval, going back duration_hours
    now_rounded = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now_rounded = now_rounded - timedelta(minutes=now_rounded.minute % 15)
    start_time = now_rounded - timedelta(hours=req.duration_hours)

    readings_generated = 0
    readings_inserted = 0
    readings_skipped = 0

    # 6. Generate synthetic observations per station
    for location in existing_locations:
        baseline = _get_synthetic_baseline(location.id)

        # Autoregressive state tracker to guarantee smooth transitions
        prev_pm25 = baseline["pm25"] * req.intensity
        prev_no2 = baseline["no2"] * req.intensity
        prev_co = baseline["co"] * req.intensity
        prev_so2 = baseline["so2"] * req.intensity
        prev_o3 = baseline["o3"] * req.intensity

        for step in range(total_steps):
            current_ts = start_time + timedelta(minutes=step * req.interval_minutes)
            progress = step / max(1, total_steps - 1)

            # Scenario multiplier + diurnal factors
            scenario_mult = _calculate_scenario_multiplier(req.scenario, progress, rng)
            diurnal = _calculate_diurnal_factors(current_ts)

            # Calculate target pollutant values
            target_pm25 = baseline["pm25"] * diurnal["pm25"] * scenario_mult * req.intensity
            target_no2 = baseline["no2"] * diurnal["no2"] * scenario_mult * req.intensity
            target_so2 = baseline["so2"] * diurnal["so2"] * scenario_mult * req.intensity
            target_co = baseline["co"] * diurnal["co"] * scenario_mult * req.intensity
            target_o3 = baseline["o3"] * diurnal["o3"] * scenario_mult * req.intensity

            # AR(1) recurrence for smooth physical transition + controlled Gaussian noise
            noise_pm25 = rng.gauss(0, max(1.0, target_pm25 * 0.04))
            noise_no2 = rng.gauss(0, max(0.5, target_no2 * 0.03))
            noise_so2 = rng.gauss(0, max(0.3, target_so2 * 0.03))
            noise_co = rng.gauss(0, max(0.05, target_co * 0.03))
            noise_o3 = rng.gauss(0, max(0.8, target_o3 * 0.04))

            cur_pm25 = round(max(1.0, 0.75 * prev_pm25 + 0.25 * target_pm25 + noise_pm25), 1)
            # PM10 is correlated with PM2.5 with natural variance
            cur_pm10 = round(max(cur_pm25 + 2.0, cur_pm25 * rng.uniform(1.45, 1.75)), 1)
            cur_no2 = round(max(1.0, 0.75 * prev_no2 + 0.25 * target_no2 + noise_no2), 1)
            cur_so2 = round(max(0.5, 0.75 * prev_so2 + 0.25 * target_so2 + noise_so2), 1)
            cur_co = round(max(0.1, 0.75 * prev_co + 0.25 * target_co + noise_co), 2)
            cur_o3 = round(max(1.0, 0.75 * prev_o3 + 0.25 * target_o3 + noise_o3), 1)

            # Meteorology
            cur_temp = round(baseline["temperature"] + diurnal["temp_shift"] + rng.uniform(-0.5, 0.5), 1)
            cur_humidity = round(min(100.0, max(10.0, baseline["humidity"] + diurnal["humidity_shift"] + rng.uniform(-1.0, 1.0))), 1)

            # Update state for next step
            prev_pm25 = cur_pm25
            prev_no2 = cur_no2
            prev_so2 = cur_so2
            prev_co = cur_co
            prev_o3 = cur_o3

            readings_generated += 1

            # 7. Check database for duplicate record
            duplicate = (
                db.query(AirQualityReading)
                .filter(
                    AirQualityReading.location_id == location.id,
                    AirQualityReading.timestamp == current_ts,
                    AirQualityReading.source_id == sim_source.id,
                )
                .first()
            )
            if duplicate:
                readings_skipped += 1
                continue

            # 8. Data Validation pass
            reading_schema = AirQualityReadingCreate(
                location_id=location.id,
                timestamp=current_ts,
                pm25=cur_pm25,
                pm10=cur_pm10,
                co=cur_co,
                no2=cur_no2,
                so2=cur_so2,
                o3=cur_o3,
                temperature=cur_temp,
                humidity=cur_humidity,
                source_id=sim_source.id,
                source_type=SourceType.SIMULATED,
            )
            quality_status, notes = validate_reading_data(reading_schema)

            # 9. Persist AirQualityReading
            reading = AirQualityReading(
                location_id=location.id,
                timestamp=current_ts,
                pm25=cur_pm25,
                pm10=cur_pm10,
                co=cur_co,
                no2=cur_no2,
                so2=cur_so2,
                o3=cur_o3,
                temperature=cur_temp,
                humidity=cur_humidity,
                source_id=sim_source.id,
                source_type=SourceType.SIMULATED,
                quality_status=quality_status,
                validation_notes=notes,
            )
            db.add(reading)
            db.flush()  # Flush to obtain reading.id for AQI caching

            # 10. Existing AQI Engine Integration (Pre-cache AQIRecord)
            calc = calculate_aqi(
                pm25=cur_pm25,
                pm10=cur_pm10,
                no2=cur_no2,
                so2=cur_so2,
                co=cur_co,
                o3=cur_o3,
                timestamp=current_ts,
            )
            aqi_rec = AQIRecord(
                location_id=location.id,
                reading_id=reading.id,
                timestamp=current_ts,
                aqi=calc.aqi,
                category=calc.category,
                dominant_pollutant=calc.dominant_pollutant,
                calculation_method=calc.calculation_method,
                status=calc.status.value,
                pollutant_subindices=calc.pollutant_subindices,
                warnings=calc.warnings,
                message=calc.message,
            )
            db.add(aqi_rec)
            readings_inserted += 1

    # Commit all inserted synthetic records and cached AQI entries
    db.commit()

    completed_at = datetime.now(timezone.utc)
    duration_sec = round((completed_at - started_at).total_seconds(), 3)

    # Store latest run metadata
    global _latest_simulation_run
    _latest_simulation_run = SimulationRunMetadata(
        scenario=req.scenario,
        location_count=len(req.location_ids),
        readings_generated=readings_generated,
        readings_inserted=readings_inserted,
        readings_skipped=readings_skipped,
        started_at=started_at,
        completed_at=completed_at,
        seed=req.seed,
    )

    return SimulationResponse(
        status="completed",
        source_type="SIMULATED",
        locations=len(req.location_ids),
        readings_generated=readings_generated,
        readings_inserted=readings_inserted,
        readings_skipped=readings_skipped,
        scenario=req.scenario,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration_sec,
        seed=req.seed,
    )
