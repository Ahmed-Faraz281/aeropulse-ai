from datetime import datetime, timedelta, timezone
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.data_source import DataSource, SourceType
from backend.app.models.location import Location
from backend.app.schemas.alert import AlertResponse
from backend.app.schemas.aqi import AQIResponse
from backend.app.schemas.location_workflow import (
    DistantStationInfo,
    LocationWorkflowRequest,
    LocationWorkflowResponse,
    PredictionSummaryItem,
    ResolvedStationInfo,
    UserLocationEcho,
    WorkflowExecutionMetadata,
)
from backend.app.schemas.openaq import (
    OpenAQIngestRequest,
    OpenAQLocationNormalized,
)
from backend.app.schemas.recommendation import RecommendationItem
from backend.app.services.alert_service import evaluate_location_alerts, get_active_alerts
from backend.app.services.openaq_ingestion_service import (
    OpenAQIngestionService,
    SUPPORTED_POLLUTANTS,
    haversine_distance_km,
)
from backend.app.services.openaq_service import (
    OpenAQRatelimitError,
    OpenAQService,
    OpenAQUpstreamError,
    get_openaq_service,
)
from backend.app.services.prediction_service import (
    DEFAULT_HORIZONS,
    predict_with_general_model,
)
from backend.app.services.recommendation_service import (
    evaluate_location_recommendations,
)

logger = logging.getLogger(__name__)

# Short-lived in-memory spatial resolution cache
# Key: f"{round(lat, 2)}:{round(lon, 2)}:{radius_meters}" -> (timestamp, LocationWorkflowResponse)
# Enforces a 15-minute TTL (900 seconds) purely for quota protection and request deduplication.
# Precise user coordinates are NEVER persisted to the database or persistent logs.
_LOCATION_RESOLUTION_CACHE: Dict[str, Tuple[float, LocationWorkflowResponse]] = {}
CACHE_TTL_SECONDS = 900.0  # 15 minutes


class LocationWorkflowService:
    """
    Lightweight orchestration service connecting user geolocation to:
    1. Deterministic OpenAQ station discovery & ranking (reusing Step 2 ranking)
    2. Observation ingestion & CPCB AQI calculation (reusing Step 2 & 4 engines)
    3. Multi-horizon AQI prediction (reusing Step 3 General Multi-Station Model Suite)
    4. Active alerts & prevention recommendations (reusing Phase 10 & 11 engines)
    """

    def __init__(self, db: Session, openaq: Optional[OpenAQService] = None):
        self.db = db
        self.openaq = openaq or get_openaq_service()
        self.ingest_service = OpenAQIngestionService(db=self.db, openaq_service=self.openaq)

    def resolve_location(self, request: LocationWorkflowRequest) -> LocationWorkflowResponse:
        start_time = time.time()
        warnings: List[str] = []
        new_station_discovered = False
        observations_ingested = 0

        # Coarse grid logging for privacy compliance (never log raw full-precision coordinates)
        coarse_lat = round(request.latitude, 1)
        coarse_lon = round(request.longitude, 1)
        logger.info(
            "Resolving location workflow for coarse grid [%.1f, %.1f], radius=%dm",
            coarse_lat,
            coarse_lon,
            request.radius_meters,
        )

        # 1. Check in-memory spatial cache (rounded to 2 decimal places ~1.1 km)
        cache_key = f"{round(request.latitude, 2)}:{round(request.longitude, 2)}:{request.radius_meters}"
        if not request.force_refresh and cache_key in _LOCATION_RESOLUTION_CACHE:
            cached_time, cached_response = _LOCATION_RESOLUTION_CACHE[cache_key]
            if time.time() - cached_time < CACHE_TTL_SECONDS:
                logger.info("Spatial cache hit for grid %s", cache_key)
                # Clone cached response and echo exact user coordinates
                resp_dict = cached_response.model_dump()
                resp_dict["user_location"] = {
                    "latitude": request.latitude,
                    "longitude": request.longitude,
                }
                resp_dict["metadata"]["cache_hit"] = True
                resp_dict["metadata"]["duration_seconds"] = round(time.time() - start_time, 3)
                return LocationWorkflowResponse(**resp_dict)

        # 2. Discover and rank candidate stations using existing Step 2 authoritative ranking
        candidates: List[OpenAQLocationNormalized] = []
        search_failed = False

        try:
            coord_str = f"{request.latitude},{request.longitude}"
            candidates = self.openaq.search_locations(
                coordinates=coord_str,
                radius=request.radius_meters,
                limit=20,
            )
        except OpenAQRatelimitError as rate_err:
            search_failed = True
            warnings.append(f"OpenAQ Rate limit hit during station discovery: {rate_err}")
            logger.warning("OpenAQ rate limit hit for grid [%.1f, %.1f]: %s", coarse_lat, coarse_lon, rate_err)
        except OpenAQUpstreamError as up_err:
            search_failed = True
            warnings.append(f"OpenAQ Upstream error during station discovery: {up_err}")
            logger.warning("OpenAQ upstream error for grid [%.1f, %.1f]: %s", coarse_lat, coarse_lon, up_err)
        except Exception as exc:
            search_failed = True
            warnings.append(f"Station discovery error: {exc}")
            logger.warning("Unexpected error during station discovery: %s", exc)

        # Fallback to local database stations if upstream search failed
        if search_failed:
            candidates = self._get_local_db_candidates(request.latitude, request.longitude)
            if candidates:
                warnings.append("Using locally registered stations due to upstream OpenAQ unavailability.")

        # 3. Apply authoritative Step 2 deterministic ranking
        def station_rank_key(loc: OpenAQLocationNormalized):
            dist = (
                haversine_distance_km(request.latitude, request.longitude, loc.latitude, loc.longitude)
                if loc.latitude is not None and loc.longitude is not None
                else 999999.0
            )
            supported_count = sum(
                1 for s in loc.sensors if s.parameter_name.lower() in SUPPORTED_POLLUTANTS
            )
            recency_sec = loc.datetime_last.timestamp() if loc.datetime_last else 0.0
            is_mon = 1 if loc.is_monitor else 0
            return (dist, -supported_count, -recency_sec, -is_mon, loc.id)

        candidates.sort(key=station_rank_key)

        # 4. Strict Radius Boundary Check (distance <= radius_meters)
        max_dist_km = request.radius_meters / 1000.0
        inside_radius: List[Tuple[OpenAQLocationNormalized, float]] = []
        outside_radius: List[Tuple[OpenAQLocationNormalized, float]] = []

        for cand in candidates:
            if cand.latitude is not None and cand.longitude is not None:
                d_km = haversine_distance_km(request.latitude, request.longitude, cand.latitude, cand.longitude)
                if d_km <= max_dist_km:
                    inside_radius.append((cand, d_km))
                else:
                    outside_radius.append((cand, d_km))

        # Handle NO_STATIONS_FOUND
        if not inside_radius:
            nearest_distant: Optional[DistantStationInfo] = None
            if outside_radius:
                # Closest station outside radius
                closest_outside, dist_out = min(outside_radius, key=lambda x: x[1])
                nearest_distant = DistantStationInfo(
                    external_id=closest_outside.id,
                    name=closest_outside.name,
                    city=closest_outside.locality or closest_outside.country_name or "Unknown",
                    latitude=closest_outside.latitude,
                    longitude=closest_outside.longitude,
                    distance_km=round(dist_out, 2),
                    notice=(
                        f"Nearest available station ({closest_outside.name}) is {round(dist_out, 1)} km away, "
                        f"located outside the configured {int(max_dist_km)} km radius. "
                        "It does not represent your immediate local air quality."
                    ),
                )

            empty_resp = LocationWorkflowResponse(
                status="NO_STATIONS_FOUND",
                message=f"No official monitoring station was found within {int(max_dist_km)} km of your location.",
                user_location=UserLocationEcho(
                    latitude=request.latitude,
                    longitude=request.longitude,
                ),
                resolved_station=None,
                nearest_distant_station=nearest_distant,
                current_aqi=None,
                predictions=[],
                active_alerts=[],
                recommendations=[],
                alternative_stations=[],
                metadata=WorkflowExecutionMetadata(
                    duration_seconds=round(time.time() - start_time, 3),
                    cache_hit=False,
                    new_station_discovered=False,
                    observations_ingested=0,
                    predictions_generated=0,
                    warnings=warnings,
                ),
            )
            # Cache negative result for 5 minutes
            _LOCATION_RESOLUTION_CACHE[cache_key] = (time.time() - (CACHE_TTL_SECONDS - 300), empty_resp)
            return empty_resp

        # 5. Primary Station Selection
        primary_cand, primary_dist_km = inside_radius[0]

        # Check if station already exists in database
        existing_loc = (
            self.db.query(Location)
            .filter(
                Location.external_provider == "OPENAQ",
                Location.external_id == str(primary_cand.id),
            )
            .first()
        )
        if not existing_loc:
            new_station_discovered = True

        loc = self.ingest_service._get_or_create_location(primary_cand)
        self.db.commit()
        self.db.refresh(loc)
        if new_station_discovered:
            logger.info("Registered new OpenAQ station %s (ID: %s)", loc.name, loc.id)

        # 6. Data Ingestion & Refresh Check
        # Check if station needs fresh observations (if no reading or older than 60m)
        latest_reading = (
            self.db.query(AirQualityReading)
            .filter(AirQualityReading.location_id == loc.id)
            .order_by(AirQualityReading.timestamp.desc())
            .first()
        )

        needs_ingest = False
        if not latest_reading:
            needs_ingest = True
        else:
            now_utc = datetime.now(timezone.utc)
            reading_ts = latest_reading.timestamp
            if reading_ts.tzinfo is None:
                reading_ts = reading_ts.replace(tzinfo=timezone.utc)
            if (now_utc - reading_ts).total_seconds() > 3600:
                needs_ingest = True

        if needs_ingest:
            try:
                ingest_req = OpenAQIngestRequest(
                    location_ids=[primary_cand.id],
                    days_history=2,  # 48-hour window for responsive interactive resolution
                )
                ingest_res = self.ingest_service.ingest(ingest_req)
                observations_ingested = ingest_res.observations_inserted
                if ingest_res.errors:
                    warnings.extend(ingest_res.errors)
            except Exception as ing_exc:
                warnings.append(f"Observation ingestion error: {ing_exc}")
                logger.warning("Ingestion error for station %s: %s", loc.id, ing_exc)

        # 7. Current AQI Retrieval
        current_aqi_resp: Optional[AQIResponse] = None
        latest_aqi_rec = (
            self.db.query(AQIRecord)
            .filter(AQIRecord.location_id == loc.id)
            .order_by(AQIRecord.timestamp.desc())
            .first()
        )
        if latest_aqi_rec:
            current_aqi_resp = AQIResponse.model_validate(latest_aqi_rec)

        # 8. Data Freshness Classification
        freshness_status, last_obs_time = self._determine_data_freshness(loc.id)

        # 9. Actual ML Readiness & Automatic General Model Prediction
        predictions: List[PredictionSummaryItem] = []
        try:
            predictions = self._generate_predictions_for_station(loc.id)
        except Exception as ml_exc:
            warnings.append(f"Prediction pipeline error: {ml_exc}")
            logger.warning("ML prediction error for station %s: %s", loc.id, ml_exc)

        # 10. Alert Evaluation & Real-Data Notification Flow
        active_alerts: List[AlertResponse] = []
        try:
            active_alerts = self._evaluate_and_get_alerts(loc.id)
        except Exception as alert_exc:
            warnings.append(f"Alert evaluation error: {alert_exc}")
            logger.warning("Alert evaluation error for station %s: %s", loc.id, alert_exc)

        # 11. Prevention Recommendation Generation Flow
        recommendations: List[RecommendationItem] = []
        try:
            recommendations = self._evaluate_and_get_recommendations(loc.id)
        except Exception as rec_exc:
            warnings.append(f"Recommendation generation error: {rec_exc}")
            logger.warning("Recommendation generation error for station %s: %s", loc.id, rec_exc)

        # 12. Alternative Stations (top 2-4 remaining candidates inside radius)
        alternative_stations: List[ResolvedStationInfo] = []
        for alt_cand, alt_dist in inside_radius[1:4]:
            alt_freshness = "FRESH" if alt_cand.datetime_last and (datetime.now(timezone.utc) - alt_cand.datetime_last).total_seconds() < 10800 else "STALE"
            alt_pollutants = [s.parameter_name.upper() for s in alt_cand.sensors if s.parameter_name.lower() in SUPPORTED_POLLUTANTS]
            # Try to get existing DB location id if registered
            alt_loc = self.db.query(Location).filter(Location.external_provider == "OPENAQ", Location.external_id == alt_cand.id).first()
            alternative_stations.append(
                ResolvedStationInfo(
                    location_id=alt_loc.id if alt_loc else 0,
                    external_id=alt_cand.id,
                    external_provider="OPENAQ",
                    name=alt_cand.name,
                    city=alt_cand.locality or alt_cand.country_name or "Unknown",
                    latitude=alt_cand.latitude,
                    longitude=alt_cand.longitude,
                    distance_km=round(alt_dist, 2),
                    is_monitor=alt_cand.is_monitor,
                    data_freshness=alt_freshness,
                    last_observation_time=alt_cand.datetime_last,
                    pollutants_monitored=alt_pollutants,
                )
            )

        # Monitored pollutants for primary station
        primary_pollutants = [
            s.parameter_name.upper()
            for s in primary_cand.sensors
            if s.parameter_name.lower() in SUPPORTED_POLLUTANTS
        ]

        resolved_station = ResolvedStationInfo(
            location_id=loc.id,
            external_id=primary_cand.id,
            external_provider="OPENAQ",
            name=loc.name,
            city=loc.city,
            latitude=loc.latitude,
            longitude=loc.longitude,
            distance_km=round(primary_dist_km, 2),
            is_monitor=primary_cand.is_monitor,
            data_freshness=freshness_status,
            last_observation_time=last_obs_time,
            pollutants_monitored=primary_pollutants,
        )

        overall_status = "SUCCESS" if not warnings else "PARTIAL_SUCCESS"
        preds_count = sum(1 for p in predictions if p.status == "PREDICTED")

        response = LocationWorkflowResponse(
            status=overall_status,
            message=f"Resolved nearest official monitoring station: {loc.name} ({round(primary_dist_km, 1)} km away).",
            user_location=UserLocationEcho(
                latitude=request.latitude,
                longitude=request.longitude,
            ),
            resolved_station=resolved_station,
            nearest_distant_station=None,
            current_aqi=current_aqi_resp,
            predictions=predictions,
            active_alerts=active_alerts,
            recommendations=recommendations,
            alternative_stations=alternative_stations,
            metadata=WorkflowExecutionMetadata(
                duration_seconds=round(time.time() - start_time, 3),
                cache_hit=False,
                new_station_discovered=new_station_discovered,
                observations_ingested=observations_ingested,
                predictions_generated=preds_count,
                warnings=warnings,
            ),
        )

        # Store in spatial resolution cache
        _LOCATION_RESOLUTION_CACHE[cache_key] = (time.time(), response)
        return response

    # ==========================================================================
    # Internal Helpers
    # ==========================================================================

    def _determine_data_freshness(self, location_id: int) -> Tuple[str, Optional[datetime]]:
        """
        Calculates observation age and maps to FRESH (< 3h), STALE (3-24h), or UNAVAILABLE (> 24h).
        """
        latest_reading = (
            self.db.query(AirQualityReading)
            .filter(AirQualityReading.location_id == location_id)
            .order_by(AirQualityReading.timestamp.desc())
            .first()
        )
        if not latest_reading or not latest_reading.timestamp:
            return "UNAVAILABLE", None

        now_utc = datetime.now(timezone.utc)
        reading_ts = latest_reading.timestamp
        if reading_ts.tzinfo is None:
            reading_ts = reading_ts.replace(tzinfo=timezone.utc)

        age_hours = (now_utc - reading_ts).total_seconds() / 3600.0
        if age_hours < 3.0:
            return "FRESH", reading_ts
        elif age_hours <= 24.0:
            return "STALE", reading_ts
        else:
            return "UNAVAILABLE", reading_ts

    def _generate_predictions_for_station(self, location_id: int) -> List[PredictionSummaryItem]:
        """
        Enforces actual ML history sufficiency (>= 4 valid continuous readings)
        before running General Model Suite predictions.
        """
        recent_readings = (
            self.db.query(AirQualityReading)
            .filter(
                AirQualityReading.location_id == location_id,
                AirQualityReading.quality_status == QualityStatus.VALID,
            )
            .order_by(AirQualityReading.timestamp.desc())
            .limit(4)
            .all()
        )

        if len(recent_readings) < 4:
            # Insufficient history
            return [
                PredictionSummaryItem(
                    horizon_hours=h,
                    predicted_aqi=None,
                    category=None,
                    status="INSUFFICIENT_HISTORY",
                    message=(
                        f"Insufficient historical data: location {location_id} has {len(recent_readings)} observations; "
                        "at least 4 continuous hourly observations are required to evaluate atmospheric trend lags."
                    ),
                )
                for h in DEFAULT_HORIZONS
            ]

        # Generate predictions across all 5 horizons
        items: List[PredictionSummaryItem] = []
        for h in DEFAULT_HORIZONS:
            try:
                pred_res = predict_with_general_model(self.db, location_id=location_id, horizon_hours=h)
                items.append(
                    PredictionSummaryItem(
                        horizon_hours=h,
                        predicted_aqi=pred_res.get("predicted_aqi"),
                        category=pred_res.get("predicted_category"),
                        base_timestamp=pred_res.get("base_timestamp"),
                        target_timestamp=pred_res.get("target_timestamp"),
                        model_version=pred_res.get("model_name"),
                        status="PREDICTED",
                    )
                )
            except Exception as exc:
                items.append(
                    PredictionSummaryItem(
                        horizon_hours=h,
                        predicted_aqi=None,
                        category=None,
                        status="MODEL_UNAVAILABLE",
                        message=str(exc),
                    )
                )

        return items

    def _evaluate_and_get_alerts(self, location_id: int) -> List[AlertResponse]:
        """Invokes existing Phase 10 alert engine and retrieves active alerts."""
        try:
            evaluate_location_alerts(self.db, location_id=location_id)
        except Exception as exc:
            logger.warning("Alert evaluation encountered exception: %s", exc)

        try:
            alerts = get_active_alerts(self.db, location_id=location_id)
            return [AlertResponse.model_validate(a) for a in alerts]
        except Exception:
            return []

    def _evaluate_and_get_recommendations(self, location_id: int) -> List[RecommendationItem]:
        """Invokes existing Phase 11 recommendation engine and retrieves recommendations."""
        try:
            recs_resp = evaluate_location_recommendations(
                self.db, location_id=location_id, include_forecast=True, include_alerts=True
            )
            return recs_resp.recommendations
        except Exception as exc:
            logger.warning("Recommendation evaluation encountered exception: %s", exc)
            return []

    def _get_local_db_candidates(self, user_lat: float, user_lon: float) -> List[OpenAQLocationNormalized]:
        """
        Constructs normalized location objects from existing database OpenAQ stations
        when upstream OpenAQ API is unavailable.
        """
        local_locs = (
            self.db.query(Location)
            .filter(
                Location.external_provider == "OPENAQ",
                Location.is_active == True,
            )
            .all()
        )

        candidates: List[OpenAQLocationNormalized] = []
        for l in local_locs:
            if l.latitude is None or l.longitude is None:
                continue
            candidates.append(
                OpenAQLocationNormalized(
                    id=l.external_id or l.id,
                    name=l.name,
                    locality=l.city,
                    country_code="IN",
                    country_name="India",
                    latitude=l.latitude,
                    longitude=l.longitude,
                    is_monitor=True,
                    datetime_last=None,
                    sensors=[],
                )
            )
        return candidates


def get_location_workflow_service(db: Session) -> LocationWorkflowService:
    return LocationWorkflowService(db=db)
