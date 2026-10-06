from datetime import datetime, timedelta, timezone
import logging
import math
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.schemas.air_quality import AirQualityReadingCreate
from backend.app.schemas.openaq import (
    OpenAQIngestRequest,
    OpenAQIngestResponse,
    OpenAQLocationNormalized,
    OpenAQSensorNormalized,
    OpenAQStationIngestSummary,
)
from backend.app.services.aqi_engine import calculate_aqi
from backend.app.services.data_validator import validate_reading_data
from backend.app.services.openaq_service import (
    OpenAQRatelimitError,
    OpenAQService,
    get_openaq_service,
)

logger = logging.getLogger(__name__)

# Canonical supported pollutants in AeroPulse
SUPPORTED_POLLUTANTS = {"pm25", "pm10", "no2", "so2", "co", "o3"}
SUPPORTED_ENVIRONMENTAL = {"temperature", "relativehumidity"}


# ==============================================================================
# Haversine Distance Helper
# ==============================================================================

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates great-circle distance between two points on the Earth in kilometers."""
    r = 6371.0  # Mean radius of Earth in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# ==============================================================================
# Scientific Unit Normalization
# ==============================================================================

def normalize_pollutant_value(
    param: str,
    value: Optional[float],
    source_unit: str,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Normalizes raw OpenAQ sensor measurements into AeroPulse canonical units:
    - PM2.5, PM10, NO2, SO2, O3: µg/m³
    - CO: mg/m³ (CPCB 8-hr standard)
    - Temperature: °C
    - Relative Humidity: %

    Strict Scientific Reference:
    - 25°C, 1 atm, molar volume V_m = 24.45 L/mol.
    - NO2: MW = 46.0055 g/mol -> ppb * 1.8816 µg/m³
    - SO2: MW = 64.066 g/mol -> ppb * 2.6203 µg/m³
    - O3: MW = 47.998 g/mol -> ppb * 1.9631 µg/m³
    - CO: MW = 28.010 g/mol -> ppm * 1.1456 mg/m³
    - CO in ppb: STRICTLY REJECTED per User Mandate (set to None + audit note).
    """
    if value is None:
        return None, None

    if math.isnan(value) or math.isinf(value):
        return None, f"Non-finite value ({value}) rejected for {param}"

    clean_unit = (source_unit or "").strip().lower()

    if param in ("pm25", "pm10"):
        if clean_unit in ("µg/m³", "ug/m3", "µg/m3", "ug/m³"):
            return float(value), None
        return None, f"Unsupported unit '{source_unit}' for {param}"

    elif param == "no2":
        if clean_unit in ("µg/m³", "ug/m3", "µg/m3", "ug/m³"):
            return float(value), None
        elif clean_unit == "ppb":
            return float(value) * 1.8816, None
        elif clean_unit == "ppm":
            return float(value) * 1881.6, None
        return None, f"Unsupported unit '{source_unit}' for NO2"

    elif param == "so2":
        if clean_unit in ("µg/m³", "ug/m3", "µg/m3", "ug/m³"):
            return float(value), None
        elif clean_unit == "ppb":
            return float(value) * 2.6203, None
        elif clean_unit == "ppm":
            return float(value) * 2620.3, None
        return None, f"Unsupported unit '{source_unit}' for SO2"

    elif param == "o3":
        if clean_unit in ("µg/m³", "ug/m3", "µg/m3", "ug/m³"):
            return float(value), None
        elif clean_unit == "ppb":
            return float(value) * 1.9631, None
        elif clean_unit == "ppm":
            return float(value) * 1963.1, None
        return None, f"Unsupported unit '{source_unit}' for O3"

    elif param == "co":
        if clean_unit in ("mg/m³", "mg/m3"):
            return float(value), None
        elif clean_unit == "ppm":
            return float(value) * 1.1456, None
        elif clean_unit == "ppb":
            # STRICT CONSERVATIVE RULE: Do not guess or reinterpret
            return None, "CO source unit is ppb and no approved conversion rule is currently configured."
        return None, f"Unsupported unit '{source_unit}' for CO"

    elif param == "temperature":
        if clean_unit in ("c", "°c", "celsius"):
            return float(value), None
        elif clean_unit in ("f", "fahrenheit"):
            return (float(value) - 32.0) * 5.0 / 9.0, None
        return None, f"Unsupported unit '{source_unit}' for temperature"

    elif param == "relativehumidity":
        if clean_unit in ("%", "percent"):
            return float(value), None
        return None, f"Unsupported unit '{source_unit}' for relative humidity"

    return None, f"Unrecognized parameter '{param}'"


# ==============================================================================
# OpenAQ Ingestion Service
# ==============================================================================

class OpenAQIngestionService:
    """
    Orchestrates dynamic discovery, ranking, parameter-specific sensor selection,
    scientific unit normalization, temporal alignment, and database persistence
    for real OpenAQ monitoring observations.
    """

    def __init__(self, db: Session, openaq_service: Optional[OpenAQService] = None):
        self.db = db
        self.openaq = openaq_service or get_openaq_service()

    # ==========================================================================
    # Public Entry Point
    # ==========================================================================

    def ingest(self, request: OpenAQIngestRequest) -> OpenAQIngestResponse:
        """
        Executes bounded multi-station discovery and ingestion.
        Guaranteed safety limits: max 5 stations per request, max 14 days history.
        """
        start_time = time.time()
        errors: List[str] = []
        station_summaries: List[OpenAQStationIngestSummary] = []

        total_obs_fetched = 0
        total_obs_inserted = 0
        total_duplicates_skipped = 0
        total_obs_rejected = 0
        total_warnings = 0
        all_pollutants_mapped: Set[str] = set()

        earliest_overall_obs: Optional[datetime] = None
        latest_overall_obs: Optional[datetime] = None

        # 1. Ensure OpenAQ DataSource Singleton exists
        openaq_source = self._get_or_create_datasource()

        # 2. Discover and rank candidate stations
        try:
            candidate_locations = self._discover_and_rank_stations(request)
        except OpenAQRatelimitError as rate_err:
            errors.append(f"Rate limit exceeded during station discovery: {rate_err}")
            return self._build_empty_response(start_time, errors, status="rate_limited")
        except Exception as exc:
            errors.append(f"Failed to discover OpenAQ stations: {exc}")
            return self._build_empty_response(start_time, errors, status="error")

        if not candidate_locations:
            return OpenAQIngestResponse(
                status="no_data",
                locations_discovered=0,
                locations_processed=0,
                sensors_discovered=0,
                sensors_selected=0,
                observations_fetched=0,
                observations_inserted=0,
                duplicates_skipped=0,
                observations_rejected=0,
                validation_warnings=0,
                pollutants_mapped=[],
                earliest_observation=None,
                latest_observation=None,
                stations=[],
                duration_seconds=round(time.time() - start_time, 2),
                errors=["No suitable OpenAQ stations found within the specified search criteria"],
            )

        locations_discovered_count = len(candidate_locations)
        # Bounded processing: strictly capped at max_locations (1 to 5)
        selected_locations = candidate_locations[: request.max_locations]
        total_sensors_discovered = 0
        total_sensors_selected = 0

        # 3. Process each station independently with transaction boundary isolation
        for openaq_loc in selected_locations:
            try:
                # Map or resolve AeroPulse Location entity
                aeropulse_loc = self._get_or_create_location(openaq_loc)

                # Discover and deterministically select best sensors
                loc_sensors = self.openaq.get_location_sensors(openaq_loc.id)
                total_sensors_discovered += len(loc_sensors)

                selected_sensors = self._select_sensors(loc_sensors)
                total_sensors_selected += len(selected_sensors)

                if not selected_sensors:
                    station_summaries.append(
                        OpenAQStationIngestSummary(
                            location_id=aeropulse_loc.id,
                            location_name=aeropulse_loc.name,
                            external_id=str(openaq_loc.id),
                            sensors_selected=0,
                            observations_fetched=0,
                            observations_inserted=0,
                            duplicates_skipped=0,
                            warnings=1,
                            pollutants=[],
                        )
                    )
                    continue

                # Determine incremental or historical time window
                dt_from, dt_to, is_skipped = self._determine_time_window(
                    aeropulse_loc.id, openaq_source.id, request.history_days
                )
                if is_skipped:
                    station_summaries.append(
                        OpenAQStationIngestSummary(
                            location_id=aeropulse_loc.id,
                            location_name=aeropulse_loc.name,
                            external_id=str(openaq_loc.id),
                            sensors_selected=len(selected_sensors),
                            observations_fetched=0,
                            observations_inserted=0,
                            duplicates_skipped=0,
                            warnings=0,
                            pollutants=[p.upper() for p in selected_sensors.keys() if p in SUPPORTED_POLLUTANTS],
                        )
                    )
                    continue

                # Fetch and assemble hourly observations
                assembled_readings, fetched_count, warn_count, mapped_params = (
                    self._fetch_and_assemble_station_readings(
                        aeropulse_loc.id, openaq_source.id, selected_sensors, dt_from, dt_to
                    )
                )
                total_obs_fetched += fetched_count
                total_warnings += warn_count
                all_pollutants_mapped.update(mapped_params)

                # Deduplicate and persist readings
                inserted, skipped_dup, rejected = self._persist_readings(
                    aeropulse_loc.id, openaq_source.id, assembled_readings
                )
                total_obs_inserted += inserted
                total_duplicates_skipped += skipped_dup
                total_obs_rejected += rejected

                # Track temporal boundaries
                for r in assembled_readings:
                    if earliest_overall_obs is None or r.timestamp < earliest_overall_obs:
                        earliest_overall_obs = r.timestamp
                    if latest_overall_obs is None or r.timestamp > latest_overall_obs:
                        latest_overall_obs = r.timestamp

                station_summaries.append(
                    OpenAQStationIngestSummary(
                        location_id=aeropulse_loc.id,
                        location_name=aeropulse_loc.name,
                        external_id=str(openaq_loc.id),
                        sensors_selected=len(selected_sensors),
                        observations_fetched=fetched_count,
                        observations_inserted=inserted,
                        duplicates_skipped=skipped_dup,
                        warnings=warn_count,
                        pollutants=[p.upper() for p in mapped_params if p in SUPPORTED_POLLUTANTS],
                    )
                )

                # Commit transaction per station
                self.db.commit()

            except OpenAQRatelimitError as rate_err:
                self.db.rollback()
                errors.append(f"Rate limit hit while ingesting station {openaq_loc.name}: {rate_err}")
                break  # Stop processing further stations immediately
            except Exception as station_err:
                self.db.rollback()
                logger.warning("Error ingesting OpenAQ station %s: %s", openaq_loc.id, station_err, exc_info=True)
                errors.append(f"Station {openaq_loc.name} ({openaq_loc.id}): {station_err}")

        # 4. Post-Ingestion ML Retraining & Automatic Multi-Horizon Predictions
        total_predictions_generated = 0
        retrained_flag = False

        if total_obs_inserted > 0:
            # Step A: Check and trigger automatic retraining if threshold met or models missing
            try:
                from backend.app.services.prediction_service import check_and_trigger_automatic_retraining
                train_res = check_and_trigger_automatic_retraining(self.db)
                if train_res:
                    retrained_flag = True
            except Exception as train_exc:
                logger.warning("Automatic model retraining check error: %s", train_exc, exc_info=True)

            # Step B: Auto-generate predictions across all 5 horizons for stations with sufficient history
            try:
                from backend.app.services.prediction_service import predict_with_general_model
                horizons = [1, 3, 6, 12, 24]
                for summary in station_summaries:
                    loc_id = summary.location_id
                    for h in horizons:
                        try:
                            pred_res = predict_with_general_model(self.db, location_id=loc_id, horizon_hours=h)
                            if pred_res and pred_res.predicted_aqi is not None:
                                total_predictions_generated += 1
                        except Exception as pred_exc:
                            logger.debug("Automatic prediction skipped for loc %s h %s: %s", loc_id, h, pred_exc)
            except Exception as ml_exc:
                logger.warning("Post-ingestion ML prediction pipeline error: %s", ml_exc, exc_info=True)

            # Step C: Downstream Alert and Recommendation Evaluation
            try:
                from backend.app.services.alert_service import evaluate_location_alerts
                from backend.app.services.recommendation_service import evaluate_location_recommendations
                for summary in station_summaries:
                    loc_id = summary.location_id
                    try:
                        evaluate_location_alerts(self.db, location_id=loc_id)
                        evaluate_location_recommendations(self.db, location_id=loc_id)
                    except Exception as down_exc:
                        logger.warning("Downstream evaluation error for loc %s: %s", loc_id, down_exc, exc_info=True)
            except Exception as down_pipeline_exc:
                logger.warning("Downstream pipeline evaluation error: %s", down_pipeline_exc, exc_info=True)

        duration = round(time.time() - start_time, 2)
        overall_status = "success"
        if errors and total_obs_inserted > 0:
            overall_status = "partial_success"
        elif errors and total_obs_inserted == 0:
            overall_status = "error"

        return OpenAQIngestResponse(
            status=overall_status,
            locations_discovered=locations_discovered_count,
            locations_processed=len(station_summaries),
            sensors_discovered=total_sensors_discovered,
            sensors_selected=total_sensors_selected,
            observations_fetched=total_obs_fetched,
            observations_inserted=total_obs_inserted,
            duplicates_skipped=total_duplicates_skipped,
            observations_rejected=total_obs_rejected,
            validation_warnings=total_warnings,
            pollutants_mapped=sorted(list(all_pollutants_mapped)),
            earliest_observation=earliest_overall_obs,
            latest_observation=latest_overall_obs,
            stations=station_summaries,
            predictions_generated=total_predictions_generated,
            models_retrained=retrained_flag,
            duration_seconds=duration,
            errors=errors,
        )

    # ==========================================================================
    # Station Discovery & Deterministic Ranking
    # ==========================================================================

    def _discover_and_rank_stations(
        self, request: OpenAQIngestRequest
    ) -> List[OpenAQLocationNormalized]:
        """
        Discovers candidate OpenAQ stations and ranks them deterministically:
        1. Haversine distance ascending
        2. Supported pollutant count descending
        3. Recency of datetime_last descending
        4. Active monitor status descending
        5. Lowest OpenAQ ID tie-breaker
        """
        candidates: List[OpenAQLocationNormalized] = []

        if request.location_ids:
            for loc_id in request.location_ids[:5]:
                try:
                    candidates.append(self.openaq.get_location(loc_id))
                except Exception as e:
                    logger.warning("Could not fetch explicit location %s: %s", loc_id, e)
            return candidates

        # Dynamic discovery by arbitrary coordinates and radius
        coord_str = f"{request.latitude},{request.longitude}"
        candidates = self.openaq.search_locations(
            coordinates=coord_str,
            radius=request.radius,
            limit=20,
        )

        def station_rank_key(loc: OpenAQLocationNormalized):
            # 1. Distance
            dist = (
                haversine_distance_km(request.latitude, request.longitude, loc.latitude, loc.longitude)
                if loc.latitude is not None and loc.longitude is not None
                else 999999.0
            )
            # 2. Supported pollutant count
            supported_count = sum(
                1 for s in loc.sensors if s.parameter_name.lower() in SUPPORTED_POLLUTANTS
            )
            # 3. Recency
            recency_sec = loc.datetime_last.timestamp() if loc.datetime_last else 0.0
            # 4. Monitor flag
            is_mon = 1 if loc.is_monitor else 0

            # Rank tuple: (distance asc, supported_count desc, recency desc, is_mon desc, id asc)
            return (dist, -supported_count, -recency_sec, -is_mon, loc.id)

        candidates.sort(key=station_rank_key)
        return candidates

    # ==========================================================================
    # Sensor Selection Algorithm (7-Tier Score)
    # ==========================================================================

    def _select_sensors(
        self, sensors: List[OpenAQSensorNormalized]
    ) -> Dict[str, OpenAQSensorNormalized]:
        """
        Selects at most one sensor per required parameter using strict (parameter + unit)
        validation and a deterministic 7-tier score hierarchy.
        """
        grouped: Dict[str, List[OpenAQSensorNormalized]] = {}
        for s in sensors:
            param = s.parameter_name.lower().strip()
            if param not in SUPPORTED_POLLUTANTS and param not in SUPPORTED_ENVIRONMENTAL:
                continue

            unit = (s.units or "").lower().strip()
            # Parameter-specific unit eligibility check
            if param in ("pm25", "pm10") and unit not in ("µg/m³", "ug/m3", "µg/m3", "ug/m³"):
                continue
            if param in ("no2", "so2", "o3") and unit not in ("µg/m³", "ug/m3", "µg/m3", "ug/m³", "ppb", "ppm"):
                continue
            if param == "co" and unit not in ("mg/m³", "mg/m3", "ppm", "ppb"):
                continue
            if param == "temperature" and unit not in ("c", "°c", "celsius", "f", "fahrenheit"):
                continue
            if param == "relativehumidity" and unit not in ("%", "percent"):
                continue

            grouped.setdefault(param, []).append(s)

        selected: Dict[str, OpenAQSensorNormalized] = {}
        now_ts = datetime.now(timezone.utc).timestamp()

        for param, candidates in grouped.items():
            def sensor_score_key(sensor: OpenAQSensorNormalized):
                # 1. Recency of datetime_last (closer to now ranks higher)
                dt_ts = sensor.datetime_last.timestamp() if sensor.datetime_last else 0.0
                # 2. is_active flag
                is_act = 1 if sensor.is_active is True else 0
                # 3. Percent coverage
                cov_pct = 0.0
                obs_cnt = 0
                if sensor.coverage:
                    cov_pct = sensor.coverage.percent_coverage or sensor.coverage.percent_complete or 0.0
                    obs_cnt = sensor.coverage.observed_count or 0
                # 4. Tie-breaker: highest sensor ID
                return (-dt_ts, -is_act, -cov_pct, -obs_cnt, -sensor.id)

            candidates.sort(key=sensor_score_key)
            selected[param] = candidates[0]

        return selected

    # ==========================================================================
    # Location Entity Resolution & Metadata Safety
    # ==========================================================================

    def _get_or_create_location(self, openaq_loc: OpenAQLocationNormalized) -> Location:
        """
        Maps an OpenAQ station to an AeroPulse Location with external_provider and external_id.
        Applies strict metadata safety: never sets state = country_name.
        """
        ext_id = str(openaq_loc.id)
        existing = (
            self.db.query(Location)
            .filter(
                Location.external_provider == "OPENAQ",
                Location.external_id == ext_id,
            )
            .first()
        )
        if existing:
            # Sync coordinates if updated
            if openaq_loc.latitude is not None and openaq_loc.longitude is not None:
                existing.latitude = openaq_loc.latitude
                existing.longitude = openaq_loc.longitude
            return existing

        # Metadata safety: derive clean locality and fallback
        city = openaq_loc.locality or "Unknown"
        state = "Unknown"  # NEVER set state = country_name!
        country = openaq_loc.country_name or "India"

        new_loc = Location(
            name=openaq_loc.name[:128],
            city=city[:64],
            state=state[:64],
            country=country[:64],
            latitude=openaq_loc.latitude if openaq_loc.latitude is not None else 0.0,
            longitude=openaq_loc.longitude if openaq_loc.longitude is not None else 0.0,
            description=f"OpenAQ CAAQMS Station (ID: {openaq_loc.id}, Provider: {openaq_loc.provider_name or 'OpenAQ'})",
            external_provider="OPENAQ",
            external_id=ext_id,
            is_active=True,
        )
        self.db.add(new_loc)
        self.db.flush()
        return new_loc

    # ==========================================================================
    # Time Window & Incremental Sync
    # ==========================================================================

    def _determine_time_window(
        self, location_id: int, source_id: int, history_days: int
    ) -> Tuple[datetime, datetime, bool]:
        """
        Determines the fetch window:
        - If existing data exists: [latest_stored - 1h, now]. Skip if synced within 30 min.
        - If initial ingestion: [now - history_days, now].
        Returns (dt_from, dt_to, is_skipped).
        """
        now_utc = datetime.now(timezone.utc)
        latest_ts = (
            self.db.query(func.max(AirQualityReading.timestamp))
            .filter(
                AirQualityReading.location_id == location_id,
                AirQualityReading.source_id == source_id,
            )
            .scalar()
        )

        if latest_ts:
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)

            # Skip if synced within the last 30 minutes
            if (now_utc - latest_ts) < timedelta(minutes=30):
                return latest_ts, now_utc, True

            dt_from = latest_ts - timedelta(hours=1)
            return dt_from, now_utc, False

        # Initial ingestion bounded by history_days (max 14)
        safe_days = min(max(history_days, 1), 14)
        dt_from = now_utc - timedelta(days=safe_days)
        return dt_from, now_utc, False

    # ==========================================================================
    # Fetch, Normalize & Assemble Hourly Readings
    # ==========================================================================

    def _fetch_and_assemble_station_readings(
        self,
        location_id: int,
        source_id: int,
        selected_sensors: Dict[str, OpenAQSensorNormalized],
        dt_from: datetime,
        dt_to: datetime,
    ) -> Tuple[List[AirQualityReadingCreate], int, int, Set[str]]:
        """
        Fetches hourly observations for selected sensors, normalizes units,
        aligns timestamps to truncated UTC hours, and builds composite reading objects.
        """
        # Bucket: hour_utc -> {param: [normalized_values]}
        hourly_buckets: Dict[datetime, Dict[str, List[float]]] = {}
        hourly_notes: Dict[datetime, List[str]] = {}
        total_fetched = 0
        total_warnings = 0
        mapped_parameters: Set[str] = set()

        for param, sensor in selected_sensors.items():
            try:
                hours_resp = self.openaq.get_sensor_hours(
                    sensor_id=sensor.id,
                    limit=100,
                    datetime_from=dt_from,
                    datetime_to=dt_to,
                )
            except Exception as sensor_err:
                logger.warning("Failed to fetch hours for sensor %s: %s", sensor.id, sensor_err)
                continue

            total_fetched += hours_resp.total_records
            for m in hours_resp.measurements:
                hour_utc = m.datetime_from_utc.astimezone(timezone.utc).replace(
                    minute=0, second=0, microsecond=0
                )
                norm_val, note = normalize_pollutant_value(param, m.value, sensor.units)

                if note:
                    total_warnings += 1
                    hourly_notes.setdefault(hour_utc, []).append(note)

                if norm_val is not None:
                    hourly_buckets.setdefault(hour_utc, {}).setdefault(param, []).append(norm_val)
                    mapped_parameters.add(param.upper())

        # Construct AirQualityReadingCreate objects
        assembled: List[AirQualityReadingCreate] = []
        for hour_utc, param_dict in sorted(hourly_buckets.items()):
            # Arithmetic mean for any multiple measurements within the hour
            co_val = param_dict.get("co")
            pm25_val = param_dict.get("pm25")
            pm10_val = param_dict.get("pm10")
            no2_val = param_dict.get("no2")
            so2_val = param_dict.get("so2")
            o3_val = param_dict.get("o3")
            temp_val = param_dict.get("temperature")
            rh_val = param_dict.get("relativehumidity")

            reading = AirQualityReadingCreate(
                location_id=location_id,
                timestamp=hour_utc,
                source_id=source_id,
                source_type=SourceType.API,
                pm25=float(sum(pm25_val) / len(pm25_val)) if pm25_val else None,
                pm10=float(sum(pm10_val) / len(pm10_val)) if pm10_val else None,
                co=float(sum(co_val) / len(co_val)) if co_val else None,
                no2=float(sum(no2_val) / len(no2_val)) if no2_val else None,
                so2=float(sum(so2_val) / len(so2_val)) if so2_val else None,
                o3=float(sum(o3_val) / len(o3_val)) if o3_val else None,
                temperature=float(sum(temp_val) / len(temp_val)) if temp_val else None,
                humidity=float(sum(rh_val) / len(rh_val)) if rh_val else None,
            )
            assembled.append(reading)

        return assembled, total_fetched, total_warnings, mapped_parameters

    # ==========================================================================
    # Persistence & Deduplication
    # ==========================================================================

    def _persist_readings(
        self,
        location_id: int,
        source_id: int,
        readings: List[AirQualityReadingCreate],
    ) -> Tuple[int, int, int]:
        """
        Deduplicates candidate readings against existing database records and persists new ones.
        Returns (inserted_count, skipped_duplicates_count, rejected_count).
        """
        if not readings:
            return 0, 0, 0

        def _norm_dt(dt: datetime) -> datetime:
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt

        min_ts = min(r.timestamp for r in readings)
        max_ts = max(r.timestamp for r in readings)

        # Batch query existing timestamps to avoid duplicate queries
        existing_ts = set(
            _norm_dt(r[0])
            for r in self.db.query(AirQualityReading.timestamp)
            .filter(
                AirQualityReading.location_id == location_id,
                AirQualityReading.source_id == source_id,
                AirQualityReading.timestamp >= min_ts,
                AirQualityReading.timestamp <= max_ts,
            )
            .all()
            if r[0] is not None
        )

        inserted = 0
        skipped_dup = 0
        rejected = 0

        for r in readings:
            if _norm_dt(r.timestamp) in existing_ts:
                skipped_dup += 1
                continue

            # Validate against physical plausibility
            q_status, v_notes = validate_reading_data(r)
            if q_status == QualityStatus.INVALID:
                rejected += 1
                continue

            db_reading = AirQualityReading(
                location_id=r.location_id,
                timestamp=r.timestamp,
                source_id=r.source_id,
                source_type=SourceType.API,
                pm25=r.pm25,
                pm10=r.pm10,
                co=r.co,
                no2=r.no2,
                so2=r.so2,
                o3=r.o3,
                temperature=r.temperature,
                humidity=r.humidity,
                quality_status=q_status,
                validation_notes=v_notes,
            )
            self.db.add(db_reading)
            self.db.flush()

            # Compute and persist AQIRecord conforming strictly to CPCB NAQI standard
            calc = calculate_aqi(
                pm25=db_reading.pm25,
                pm10=db_reading.pm10,
                no2=db_reading.no2,
                so2=db_reading.so2,
                co=db_reading.co,
                o3=db_reading.o3,
                timestamp=db_reading.timestamp,
            )
            aqi_rec = AQIRecord(
                location_id=db_reading.location_id,
                reading_id=db_reading.id,
                timestamp=db_reading.timestamp,
                aqi=calc.aqi,
                category=calc.category,
                dominant_pollutant=calc.dominant_pollutant,
                calculation_method=calc.calculation_method,
                status=calc.status.value,
                pollutant_subindices=calc.pollutant_subindices,
                warnings=calc.warnings,
                message=calc.message,
            )
            self.db.add(aqi_rec)

            existing_ts.add(_norm_dt(r.timestamp))
            inserted += 1

        self.db.flush()
        return inserted, skipped_dup, rejected

    # ==========================================================================
    # Helper Utilities
    # ==========================================================================

    def _get_or_create_datasource(self) -> DataSource:
        """Retrieves or initializes the authoritative OpenAQ DataSource singleton."""
        source = (
            self.db.query(DataSource)
            .filter(
                DataSource.name == "OpenAQ",
                DataSource.source_type == SourceType.API,
            )
            .first()
        )
        if not source:
            source = DataSource(
                name="OpenAQ",
                source_type=SourceType.API,
                provider="OpenAQ API v3",
                description="Official OpenAQ API v3 global air quality monitoring network.",
                is_active=True,
            )
            self.db.add(source)
            self.db.flush()
        return source

    def _build_empty_response(
        self, start_time: float, errors: List[str], status: str = "error"
    ) -> OpenAQIngestResponse:
        return OpenAQIngestResponse(
            status=status,
            locations_discovered=0,
            locations_processed=0,
            sensors_discovered=0,
            sensors_selected=0,
            observations_fetched=0,
            observations_inserted=0,
            duplicates_skipped=0,
            observations_rejected=0,
            validation_warnings=0,
            pollutants_mapped=[],
            earliest_observation=None,
            latest_observation=None,
            stations=[],
            duration_seconds=round(time.time() - start_time, 2),
            errors=errors,
        )


def get_openaq_ingestion_service(db: Session) -> OpenAQIngestionService:
    return OpenAQIngestionService(db=db)
