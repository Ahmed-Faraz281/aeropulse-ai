"""
Analytics and Trends Engine for Intelligent Air Quality Monitoring System.

Provides purely descriptive, explainable statistical calculations, temporal aggregations,
anomaly detection, and pollution event analysis without predictive or black-box modeling.
"""

import math
import statistics
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class TrendDirection(str, Enum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def _is_finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not math.isnan(v) and not math.isinf(v)


def calculate_summary_statistics(values: Sequence[Optional[float]]) -> Dict[str, Any]:
    """
    Computes count, mean, min, max, median, and stddev for a series of numbers.
    Missing (None) values are strictly excluded and never treated as zero.
    """
    clean_values = [float(v) for v in values if v is not None and _is_finite_number(v)]
    count = len(clean_values)

    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "minimum": None,
            "maximum": None,
            "median": None,
            "stddev": None,
        }

    mean_val = round(sum(clean_values) / count, 2)
    min_val = round(min(clean_values), 2)
    max_val = round(max(clean_values), 2)
    median_val = round(float(statistics.median(clean_values)), 2)
    stddev_val = round(float(statistics.stdev(clean_values)), 2) if count > 1 else 0.0

    return {
        "count": count,
        "mean": mean_val,
        "minimum": min_val,
        "maximum": max_val,
        "median": median_val,
        "stddev": stddev_val,
    }


def compute_trend_direction(
    recent_values: Sequence[Optional[float]],
    baseline_values: Sequence[Optional[float]],
    threshold_pct: float = 0.05,
) -> TrendDirection:
    """
    Compares the mean of the recent period against the baseline period.
    Uses a 5% hysteresis threshold to avoid noise flapping.
    """
    clean_recent = [float(v) for v in recent_values if v is not None and _is_finite_number(v)]
    clean_baseline = [float(v) for v in baseline_values if v is not None and _is_finite_number(v)]

    if len(clean_recent) == 0 or len(clean_baseline) == 0:
        return TrendDirection.INSUFFICIENT_DATA

    recent_mean = sum(clean_recent) / len(clean_recent)
    baseline_mean = sum(clean_baseline) / len(clean_baseline)

    if baseline_mean == 0:
        if recent_mean > 0:
            return TrendDirection.INCREASING
        elif recent_mean == 0:
            return TrendDirection.STABLE
        else:
            return TrendDirection.DECREASING

    change_ratio = (recent_mean - baseline_mean) / baseline_mean

    if change_ratio > threshold_pct:
        return TrendDirection.INCREASING
    elif change_ratio < -threshold_pct:
        return TrendDirection.DECREASING
    else:
        return TrendDirection.STABLE


def aggregate_time_series(
    records: List[Dict[str, Any]],
    metric_field: str = "value",
    aggregation: str = "hourly",
) -> List[Dict[str, Any]]:
    """
    Groups time-series records into hourly, daily, weekly, or monthly buckets.
    Computes average, maximum, and observation count per bucket.
    """
    if not records:
        return []

    buckets: Dict[str, List[float]] = {}

    for record in records:
        ts = record.get("timestamp")
        if not isinstance(ts, datetime):
            continue

        val = record.get(metric_field)
        if val is None:
            # Check alternative fields
            val = record.get("aqi") if metric_field == "aqi" else record.get("value")
        if val is None or not _is_finite_number(val):
            continue

        if aggregation == "hourly":
            key = ts.strftime("%Y-%m-%dT%H:00:00Z")
        elif aggregation == "daily":
            key = ts.strftime("%Y-%m-%dT00:00:00Z")
        elif aggregation == "weekly":
            # Monday of current week
            week_start = ts - timedelta(days=ts.weekday())
            key = week_start.strftime("%Y-%m-%dT00:00:00Z")
        elif aggregation == "monthly":
            key = ts.strftime("%Y-%m-01T00:00:00Z")
        else:
            key = ts.strftime("%Y-%m-%dT%H:00:00Z")

        if key not in buckets:
            buckets[key] = []
        buckets[key].append(float(val))

    result = []
    for key in sorted(buckets.keys()):
        vals = buckets[key]
        result.append({
            "timestamp": key,
            "average": round(sum(vals) / len(vals), 2),
            "maximum": round(max(vals), 2),
            "count": len(vals),
        })

    return result


def detect_anomalies(
    records: List[Dict[str, Any]],
    metric: str = "aqi",
    method: str = "zscore",
    threshold: float = 2.5,
) -> List[Dict[str, Any]]:
    """
    Identifies statistically anomalous data points using Z-score or IQR.
    Returns structured, explainable anomalies with observed vs expected reference values.
    """
    valid_items = []
    for r in records:
        val = r.get(metric) or r.get("value") or r.get("aqi")
        if val is not None and _is_finite_number(val):
            valid_items.append((r, float(val)))

    if len(valid_items) < 3:
        return []

    values = [v for _, v in valid_items]
    anomalies = []

    if method == "zscore":
        mean = sum(values) / len(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        if stdev == 0:
            return []

        for record, val in valid_items:
            z_score = (val - mean) / stdev
            if abs(z_score) >= threshold:
                severity = "HIGH" if abs(z_score) >= 3.0 else "MEDIUM"
                anomalies.append({
                    "timestamp": record.get("timestamp"),
                    "location_id": record.get("location_id"),
                    "metric": metric,
                    "observed_value": val,
                    "expected_value": round(mean, 2),
                    "score": round(abs(z_score), 2),
                    "severity": severity,
                    "reason": f"Value {val} deviates by {abs(z_score):.2f} standard deviations from historical mean of {mean:.2f}.",
                })

    elif method == "iqr":
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[int(n * 0.25)]
        q3 = sorted_vals[int(n * 0.75)]
        iqr = q3 - q1
        lower_bound = q1 - (1.5 * iqr)
        upper_bound = q3 + (1.5 * iqr)
        median_val = statistics.median(values)

        for record, val in valid_items:
            if val < lower_bound or val > upper_bound:
                dist = max(lower_bound - val, val - upper_bound)
                score = round(dist / iqr, 2) if iqr > 0 else 2.0
                severity = "HIGH" if score >= 3.0 else "MEDIUM"
                anomalies.append({
                    "timestamp": record.get("timestamp"),
                    "location_id": record.get("location_id"),
                    "metric": metric,
                    "observed_value": val,
                    "expected_value": round(float(median_val), 2),
                    "score": score,
                    "severity": severity,
                    "reason": f"Value {val} falls outside IQR normal range [{lower_bound:.2f}, {upper_bound:.2f}].",
                })

    return anomalies


def detect_pollution_events(
    records: List[Dict[str, Any]],
    aqi_threshold: int = 201,
    min_duration_hours: float = 2.0,
) -> List[Dict[str, Any]]:
    """
    Scans a sorted time-series of readings and detects sustained episodes
    where AQI >= aqi_threshold for at least min_duration_hours.
    """
    if not records:
        return []

    # Sort chronological
    sorted_records = sorted(
        [r for r in records if r.get("aqi") is not None],
        key=lambda x: x["timestamp"]
    )

    events = []
    current_run: List[Dict[str, Any]] = []

    def finalize_run(run: List[Dict[str, Any]]):
        if not run:
            return
        duration = float(len(run))
        if duration >= min_duration_hours:
            peak_aqi = max(r["aqi"] for r in run)
            dom_poll = run[0].get("dominant_pollutant", "Unknown")
            events.append({
                "location_id": run[0].get("location_id"),
                "start_time": run[0]["timestamp"],
                "end_time": run[-1]["timestamp"],
                "duration_hours": duration,
                "max_aqi": peak_aqi,
                "dominant_pollutant": dom_poll,
                "increase_percentage": 0.0,
                "detection_reason": f"Sustained elevated AQI >= {aqi_threshold} for {duration:.1f} hours (peak AQI: {peak_aqi}).",
            })

    for r in sorted_records:
        if r["aqi"] >= aqi_threshold:
            current_run.append(r)
        else:
            finalize_run(current_run)
            current_run = []

    finalize_run(current_run)
    return events
