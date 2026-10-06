from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.api.deps import get_current_user
from backend.app.models.user import User
from backend.app.models.location import Location
from backend.app.models.air_quality import AirQualityReading
from backend.app.models.aqi import AQIRecord
from backend.app.api.v1.aqi import _get_or_create_aqi_record
from backend.app.schemas.analytics import (
    AnomalyItem,
    HotspotIndicatorItem,
    LocationAnalyticsSummary,
    LocationComparisonItem,
    MetricStatistics,
    PollutionEventItem,
    TimeAggregatedPoint,
)
from backend.app.services.analytics import (
    aggregate_time_series,
    calculate_summary_statistics,
    compute_trend_direction,
    detect_anomalies,
    detect_pollution_events,
)

router = APIRouter()

SUPPORTED_POLLUTANTS = ["pm25", "pm10", "no2", "so2", "co", "o3", "nh3", "pb"]
SUPPORTED_AGGREGATIONS = ["hourly", "daily", "weekly", "monthly"]


def _validate_time_window(start_time: Optional[datetime], end_time: Optional[datetime]):
    if start_time and end_time and start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time must be earlier than end_time.",
        )


def _get_location_or_404(location_id: int, db: Session) -> Location:
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {location_id} not found.",
        )
    return location


@router.get(
    "/summary",
    response_model=LocationAnalyticsSummary,
    summary="Get Location Analytics Summary",
    description="Computes multi-pollutant statistics, AQI statistics, and descriptive trend direction.",
)
def get_location_summary(
    location_id: int = Query(..., description="Location ID to summarize"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    location = _get_location_or_404(location_id, db)

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.asc()).all()

    # Synchronize and fetch corresponding AQIRecords
    aqi_records: List[AQIRecord] = [_get_or_create_aqi_record(r, db) for r in readings]

    # AQI statistics
    aqi_values = [r.aqi for r in aqi_records if r.aqi is not None]
    aqi_stats = MetricStatistics(**calculate_summary_statistics(aqi_values))

    # Pollutant statistics
    pollutant_stats = {}
    for poll in SUPPORTED_POLLUTANTS:
        vals = [getattr(r, poll, None) for r in readings]
        pollutant_stats[poll] = MetricStatistics(**calculate_summary_statistics(vals))

    # Descriptive trend direction (split into baseline vs recent window)
    if len(aqi_values) >= 2:
        halfway = len(aqi_values) // 2
        baseline = aqi_values[:halfway]
        recent = aqi_values[halfway:]
        trend_dir = compute_trend_direction(recent, baseline).value
    else:
        trend_dir = "INSUFFICIENT_DATA"

    return LocationAnalyticsSummary(
        location_id=location.id,
        location_name=location.name,
        city=location.city,
        start_time=start_time,
        end_time=end_time,
        aqi_statistics=aqi_stats,
        pollutant_statistics=pollutant_stats,
        trend_direction=trend_dir,
    )


@router.get(
    "/aqi-trend",
    response_model=List[TimeAggregatedPoint],
    summary="Get Aggregated AQI Trend",
    description="Returns time-aggregated AQI metrics (average, maximum, count) grouped by specified interval.",
)
def get_aqi_trend(
    location_id: int = Query(..., description="Location ID to query"),
    aggregation: str = Query("hourly", description="Interval: hourly, daily, weekly, monthly"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    limit: int = Query(500, ge=1, le=1000, description="Max aggregated buckets to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid aggregation '{aggregation}'. Supported values: {', '.join(SUPPORTED_AGGREGATIONS)}",
        )
    _get_location_or_404(location_id, db)

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.asc()).all()
    aqi_records = [_get_or_create_aqi_record(r, db) for r in readings]

    records = [
        {"timestamp": r.timestamp, "value": r.aqi}
        for r in aqi_records
        if r.aqi is not None
    ]

    aggregated = aggregate_time_series(records, metric_field="value", aggregation=aggregation)
    return [TimeAggregatedPoint(**pt) for pt in aggregated[:limit]]


@router.get(
    "/pollutants/{pollutant}",
    response_model=List[TimeAggregatedPoint],
    summary="Get Aggregated Pollutant Trend",
    description="Returns time-aggregated concentration metrics for a specific pollutant.",
)
def get_pollutant_trend(
    pollutant: str,
    location_id: int = Query(..., description="Location ID to query"),
    aggregation: str = Query("hourly", description="Interval: hourly, daily, weekly, monthly"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    limit: int = Query(500, ge=1, le=1000, description="Max aggregated buckets to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    norm_poll = pollutant.lower().replace(".", "")
    if norm_poll not in SUPPORTED_POLLUTANTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid pollutant '{pollutant}'. Supported values: {', '.join(SUPPORTED_POLLUTANTS)}",
        )
    if aggregation not in SUPPORTED_AGGREGATIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid aggregation '{aggregation}'. Supported values: {', '.join(SUPPORTED_AGGREGATIONS)}",
        )
    _get_location_or_404(location_id, db)

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.asc()).all()

    records = [
        {"timestamp": r.timestamp, "value": getattr(r, norm_poll, None)}
        for r in readings
        if getattr(r, norm_poll, None) is not None
    ]

    aggregated = aggregate_time_series(records, metric_field="value", aggregation=aggregation)
    return [TimeAggregatedPoint(**pt) for pt in aggregated[:limit]]


@router.get(
    "/location-comparison",
    response_model=List[LocationComparisonItem],
    summary="Compare Multiple Locations",
    description="Compares objective AQI metrics across multiple stations over a uniform time range.",
)
def compare_locations(
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    locations = db.query(Location).filter(Location.is_active == True).all()

    results = []
    for loc in locations:
        q = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc.id)
        if start_time:
            q = q.filter(AirQualityReading.timestamp >= start_time)
        if end_time:
            q = q.filter(AirQualityReading.timestamp <= end_time)
        readings = q.all()

        aqi_records = [_get_or_create_aqi_record(r, db) for r in readings]
        valid_aqis = [r.aqi for r in aqi_records if r.aqi is not None]

        dom_poll = aqi_records[-1].dominant_pollutant if aqi_records else None
        avg_aqi = round(sum(valid_aqis) / len(valid_aqis), 2) if valid_aqis else None
        max_aqi = max(valid_aqis) if valid_aqis else None

        results.append(
            LocationComparisonItem(
                location_id=loc.id,
                location_name=loc.name,
                city=loc.city,
                average_aqi=avg_aqi,
                max_aqi=max_aqi,
                observation_count=len(valid_aqis),
                dominant_pollutant=dom_poll,
            )
        )

    return results


@router.get(
    "/anomalies",
    response_model=List[AnomalyItem],
    summary="Detect Metric Anomalies",
    description="Executes explainable statistical anomaly detection using Z-score or IQR methods.",
)
def get_anomalies(
    location_id: int = Query(..., description="Location ID to analyze"),
    metric: str = Query("aqi", description="Metric to inspect: aqi, pm25, pm10, no2, etc."),
    method: str = Query("zscore", description="Detection method: zscore or iqr"),
    threshold: float = Query(2.5, ge=1.0, le=5.0, description="Outlier threshold factor"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    norm_metric = metric.lower().replace(".", "")
    if norm_metric != "aqi" and norm_metric not in SUPPORTED_POLLUTANTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid metric '{metric}'. Supported values: aqi, {', '.join(SUPPORTED_POLLUTANTS)}",
        )
    if method not in ["zscore", "iqr"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Detection method must be 'zscore' or 'iqr'.",
        )
    _get_location_or_404(location_id, db)

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.asc()).all()

    if norm_metric == "aqi":
        aqi_records = [_get_or_create_aqi_record(r, db) for r in readings]
        records = [
            {"timestamp": r.timestamp, "location_id": r.location_id, "aqi": r.aqi}
            for r in aqi_records
        ]
    else:
        records = [
            {"timestamp": r.timestamp, "location_id": r.location_id, norm_metric: getattr(r, norm_metric, None)}
            for r in readings
        ]

    anomalies = detect_anomalies(records, metric=norm_metric, method=method, threshold=threshold)
    return [AnomalyItem(**a) for a in anomalies]


@router.get(
    "/events",
    response_model=List[PollutionEventItem],
    summary="Detect Pollution Events",
    description="Identifies sustained episodes where AQI exceeds configured threshold for minimum duration.",
)
def get_pollution_events(
    location_id: int = Query(..., description="Location ID to analyze"),
    aqi_threshold: int = Query(201, ge=50, le=500, description="AQI cutoff threshold (default 201: Poor)"),
    min_duration_hours: float = Query(2.0, ge=1.0, le=24.0, description="Minimum episode duration in hours"),
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    _get_location_or_404(location_id, db)

    query = db.query(AirQualityReading).filter(AirQualityReading.location_id == location_id)
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings = query.order_by(AirQualityReading.timestamp.asc()).all()
    aqi_records = [_get_or_create_aqi_record(r, db) for r in readings]

    records = [
        {
            "timestamp": r.timestamp,
            "location_id": r.location_id,
            "aqi": r.aqi,
            "dominant_pollutant": r.dominant_pollutant,
        }
        for r in aqi_records
    ]

    events = detect_pollution_events(
        records,
        aqi_threshold=aqi_threshold,
        min_duration_hours=min_duration_hours,
    )
    return [PollutionEventItem(**e) for e in events]


@router.get(
    "/hotspots",
    response_model=List[HotspotIndicatorItem],
    summary="Identify Pollution Hotspot Indicators",
    description="Provides purely objective measurements (peak AQI, mean AQI, event count) for stations.",
)
def get_hotspot_indicators(
    start_time: Optional[datetime] = Query(None, description="Start timestamp filter (ISO-8601)"),
    end_time: Optional[datetime] = Query(None, description="End timestamp filter (ISO-8601)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_time_window(start_time, end_time)
    locations = db.query(Location).filter(Location.is_active == True).all()

    hotspots = []
    for loc in locations:
        q = db.query(AirQualityReading).filter(AirQualityReading.location_id == loc.id)
        if start_time:
            q = q.filter(AirQualityReading.timestamp >= start_time)
        if end_time:
            q = q.filter(AirQualityReading.timestamp <= end_time)
        readings = q.order_by(AirQualityReading.timestamp.asc()).all()

        aqi_records = [_get_or_create_aqi_record(r, db) for r in readings]
        valid_aqis = [r.aqi for r in aqi_records if r.aqi is not None]

        mean_aqi = round(sum(valid_aqis) / len(valid_aqis), 2) if valid_aqis else None
        max_aqi = max(valid_aqis) if valid_aqis else None
        high_pollution_hours = sum(1 for a in valid_aqis if a >= 201)

        events = detect_pollution_events(
            [{"timestamp": r.timestamp, "location_id": r.location_id, "aqi": r.aqi, "dominant_pollutant": r.dominant_pollutant} for r in aqi_records],
            aqi_threshold=201,
            min_duration_hours=2.0,
        )

        hotspots.append(
            HotspotIndicatorItem(
                location_id=loc.id,
                location_name=loc.name,
                city=loc.city,
                mean_aqi=mean_aqi,
                max_aqi=max_aqi,
                observation_count=len(valid_aqis),
                high_pollution_hours=high_pollution_hours,
                event_count=len(events),
            )
        )

    return hotspots
