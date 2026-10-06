"""
Report compilation and ReportLab PDF generation service for AeroPulse AI.

Provides stateless, deterministic, non-destructive report generation across:
- Location Summary Reports
- Environmental Period Reports
- Factual Multi-Location Comparison Reports
- What-If Scenario Impact Reports

Strictly reuses existing Phase 4-12 services:
- CPCB AQI engine (aqi_engine.py)
- Descriptive analytics, anomalies, events (analytics.py)
- ML forecasts (prediction_service.py)
- Threshold alerts (alert_service.py)
- Prevention & explainable recommendations (recommendation_service.py)
- What-If simulation (what_if_service.py)
"""

from datetime import datetime, timedelta, timezone
import io
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Table,
    TableStyle,
    Spacer,
    PageBreak,
    KeepTogether,
    HRFlowable,
)
from reportlab.pdfgen import canvas

from backend.app.models.location import Location
from backend.app.models.air_quality import AirQualityReading, QualityStatus
from backend.app.models.aqi import AQIRecord
from backend.app.models.alert import Alert, AlertSeverity, AlertStatus
from backend.app.models.prediction import PredictionRecord
from backend.app.api.v1.aqi import _get_or_create_aqi_record
from backend.app.schemas.report import (
    ReportType,
    ReportGenerateRequest,
    ReportPreviewResponse,
)
from backend.app.schemas.what_if import WhatIfSimulationRequest
from backend.app.services.analytics import (
    calculate_summary_statistics,
    compute_trend_direction,
    aggregate_time_series,
    detect_anomalies,
    detect_pollution_events,
    TrendDirection,
)
from backend.app.services.recommendation_service import (
    evaluate_location_recommendations,
    generate_recommendations_from_context,
)
from backend.app.services.what_if_service import run_what_if_simulation
from backend.app.services.aqi_breakpoints import get_aqi_category

SUPPORTED_POLLUTANTS = ["pm25", "pm10", "no2", "so2", "co", "o3", "nh3", "pb"]

POLLUTANT_METADATA = {
    "pm25": {"label": "PM2.5", "unit": "µg/m³", "name": "Fine Particulate Matter"},
    "pm10": {"label": "PM10", "unit": "µg/m³", "name": "Coarse Particulate Matter"},
    "no2": {"label": "NO2", "unit": "µg/m³", "name": "Nitrogen Dioxide"},
    "so2": {"label": "SO2", "unit": "µg/m³", "name": "Sulfur Dioxide"},
    "co": {"label": "CO", "unit": "mg/m³", "name": "Carbon Monoxide"},
    "o3": {"label": "O3", "unit": "µg/m³", "name": "Ozone"},
    "nh3": {"label": "NH3", "unit": "µg/m³", "name": "Ammonia"},
    "pb": {"label": "Pb", "unit": "µg/m³", "name": "Lead Particulate"},
}

CPCB_COLORS = {
    "Good": colors.HexColor("#10b981"),
    "Satisfactory": colors.HexColor("#84cc16"),
    "Moderate": colors.HexColor("#f59e0b"),
    "Poor": colors.HexColor("#f97316"),
    "Very Poor": colors.HexColor("#ef4444"),
    "Severe": colors.HexColor("#881337"),
    "Unknown": colors.HexColor("#64748b"),
}

STANDARD_DISCLAIMER = (
    "AeroPulse AI is a purely software-based environmental monitoring, prediction, "
    "and recommendation platform based on telemetry from authorized monitoring stations. "
    "All outputs, including AQI evaluations, trend analyses, ML forecasts, and preventive guidance, "
    "are for informational and public awareness purposes only and DO NOT constitute medical advice. "
    "Physical hardware sensors are neither operated nor physically simulated as measured."
)


def _resolve_time_window(
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    preset: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Resolves start and end timestamps based on preset or explicit ISO timestamps."""
    now = datetime.now(timezone.utc)
    if preset:
        preset_map = {
            "24h": timedelta(hours=24),
            "48h": timedelta(hours=48),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        delta = preset_map.get(preset.lower())
        if delta:
            return now - delta, now

    if start_time and end_time and start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time must be earlier than end_time.",
        )

    return start_time, end_time


def compile_report_data(request: ReportGenerateRequest, db: Session) -> Dict[str, Any]:
    """
    Statelessly compiles all structured environmental data, statistics,
    anomalies, alerts, predictions, and recommendations for a report.
    """
    start_time, end_time = _resolve_time_window(
        request.start_time, request.end_time, request.period_preset
    )

    location = db.query(Location).filter(Location.id == request.location_id).first()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Location with ID {request.location_id} not found.",
        )

    # Fetch readings for primary location
    query = db.query(AirQualityReading).filter(
        AirQualityReading.location_id == request.location_id,
        AirQualityReading.quality_status == QualityStatus.VALID,
    )
    if start_time:
        query = query.filter(AirQualityReading.timestamp >= start_time)
    if end_time:
        query = query.filter(AirQualityReading.timestamp <= end_time)

    readings: List[AirQualityReading] = query.order_by(AirQualityReading.timestamp.asc()).all()

    # Synchronize AQI records
    aqi_records: List[AQIRecord] = [_get_or_create_aqi_record(r, db) for r in readings]

    # AQI Statistics
    aqi_values = [r.aqi for r in aqi_records if r and r.aqi is not None]
    aqi_stats = calculate_summary_statistics(aqi_values)

    # Category distribution
    category_counts = {
        "Good": 0,
        "Satisfactory": 0,
        "Moderate": 0,
        "Poor": 0,
        "Very Poor": 0,
        "Severe": 0,
    }
    for rec in aqi_records:
        if rec and rec.category and rec.category in category_counts:
            category_counts[rec.category] += 1

    # Latest observation
    latest_reading = readings[-1] if readings else None
    latest_aqi_rec = aqi_records[-1] if aqi_records else None

    latest_aqi = latest_aqi_rec.aqi if latest_aqi_rec else None
    latest_category = latest_aqi_rec.category if latest_aqi_rec else None
    dominant_pollutant = latest_aqi_rec.dominant_pollutant if latest_aqi_rec else None

    # Trend Direction
    if len(aqi_values) >= 2:
        midpoint = len(aqi_values) // 2
        trend_direction = compute_trend_direction(
            recent_values=aqi_values[midpoint:],
            baseline_values=aqi_values[:midpoint],
        ).value
    else:
        trend_direction = TrendDirection.INSUFFICIENT_DATA.value

    # Pollutant Summaries (strict NULL preservation)
    pollutant_summary: Dict[str, Any] = {}
    for p in SUPPORTED_POLLUTANTS:
        vals = [getattr(r, p) for r in readings if hasattr(r, p)]
        p_stats = calculate_summary_statistics(vals)
        latest_val = getattr(latest_reading, p) if latest_reading and hasattr(latest_reading, p) else None

        if p_stats["count"] == 0:
            pollutant_summary[p] = {
                "available": False,
                "label": POLLUTANT_METADATA[p]["label"],
                "unit": POLLUTANT_METADATA[p]["unit"],
                "message": "Data unavailable for this pollutant during the selected period.",
                "statistics": p_stats,
                "latest": None,
            }
        else:
            clean_vals = [v for v in vals if v is not None]
            mid = len(clean_vals) // 2
            p_trend = (
                compute_trend_direction(clean_vals[mid:], clean_vals[:mid]).value
                if mid > 0
                else TrendDirection.STABLE.value
            )
            pollutant_summary[p] = {
                "available": True,
                "label": POLLUTANT_METADATA[p]["label"],
                "unit": POLLUTANT_METADATA[p]["unit"],
                "message": None,
                "statistics": p_stats,
                "latest": latest_val,
                "trend": p_trend,
            }

    # Anomalies & Events
    reading_dicts = [
        {
            "timestamp": r.timestamp,
            "location_id": r.location_id,
            "aqi": aqi_records[idx].aqi if idx < len(aqi_records) and aqi_records[idx] else None,
            "pm25": r.pm25,
            "pm10": r.pm10,
        }
        for idx, r in enumerate(readings)
    ]
    detected_anomalies = detect_anomalies(reading_dicts, metric="aqi", method="zscore", threshold=2.5)
    detected_events = detect_pollution_events(reading_dicts, aqi_threshold=201, min_duration_hours=2.0)

    # Alerts (Observation vs Forecast Alerts)
    alert_query = db.query(Alert).filter(Alert.location_id == request.location_id)
    if start_time:
        alert_query = alert_query.filter(Alert.detected_at >= start_time)
    if end_time:
        alert_query = alert_query.filter(Alert.detected_at <= end_time)

    db_alerts: List[Alert] = alert_query.order_by(Alert.detected_at.desc()).limit(20).all()
    alerts_data: List[Dict[str, Any]] = []
    for a in db_alerts:
        is_pred = getattr(a, "is_prediction", False)
        tag = "FORECAST ALERT" if is_pred else "OBSERVATION ALERT"
        val = getattr(a, "observed_value", None)
        ts = getattr(a, "detected_at", getattr(a, "created_at", None))
        alerts_data.append({
            "id": a.id,
            "type": a.alert_type.value if hasattr(a.alert_type, "value") else str(a.alert_type),
            "severity": a.severity.value if hasattr(a.severity, "value") else str(a.severity),
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "current_value": val,
            "threshold_value": a.threshold_value,
            "message": a.message,
            "triggered_at": ts.isoformat() if ts else None,
            "tag": tag,
            "is_predicted": is_pred,
        })

    # ML Predictions (from Phase 9)
    prediction_record = (
        db.query(PredictionRecord)
        .filter(PredictionRecord.location_id == request.location_id)
        .order_by(PredictionRecord.created_at.desc())
        .first()
    )
    forecast_data: Optional[Dict[str, Any]] = None
    if prediction_record:
        forecast_data = {
            "horizon_hours": prediction_record.horizon_hours,
            "predicted_aqi": round(prediction_record.predicted_aqi, 1),
            "predicted_category": prediction_record.predicted_category,
            "model_name": prediction_record.model_name,
            "target_timestamp": prediction_record.target_timestamp.isoformat() if prediction_record.target_timestamp else None,
            "mae": round(prediction_record.mae, 2) if prediction_record.mae is not None else None,
            "rmse": round(prediction_record.rmse, 2) if prediction_record.rmse is not None else None,
            "r2": round(prediction_record.r2, 3) if prediction_record.r2 is not None else None,
            "has_simulated_data": prediction_record.has_simulated_data,
            "label": "FORECAST — NOT CURRENT OBSERVATION",
        }

    # Preventive Recommendations (from Phase 11)
    rec_response = evaluate_location_recommendations(
        db=db,
        location_id=request.location_id,
    )
    recommendations_data = [
        {
            "id": rec.id,
            "type": rec.type.value if hasattr(rec.type, "value") else str(rec.type),
            "priority": rec.priority.value if hasattr(rec.priority, "value") else str(rec.priority),
            "action": rec.action,
            "reason": rec.reason,
            "triggered_by": rec.triggered_by,
            "supporting_data": rec.supporting_data,
            "source_type": rec.source_type,
        }
        for rec in rec_response.recommendations[:6]
    ]

    # Data Provenance Distribution
    sources_count: Dict[str, int] = {}
    for r in readings:
        s_type = r.source_type.value if hasattr(r.source_type, "value") else str(r.source_type)
        sources_count[s_type] = sources_count.get(s_type, 0) + 1

    primary_source = (
        max(sources_count.keys(), key=lambda k: sources_count[k])
        if sources_count
        else "API"
    )

    provenance_summary = {
        "observed_provenance": primary_source,
        "forecast_provenance": "PREDICTED" if forecast_data else "NONE",
        "scenario_provenance": (
            "WHAT_IF / SIMULATED"
            if request.report_type == ReportType.WHAT_IF_REPORT
            else "NONE"
        ),
    }

    # Specific Scenario: WHAT-IF REPORT (Phase 12)
    what_if_data: Optional[Dict[str, Any]] = None
    if request.report_type == ReportType.WHAT_IF_REPORT:
        what_if_req = request.what_if_request
        if not what_if_req:
            # Default hypothetical scenario if none specified
            what_if_req = WhatIfSimulationRequest(
                location_id=request.location_id,
                reading_id=latest_reading.id if latest_reading else None,
                pollutant_changes={"pm25": -20.0, "no2": -15.0},
            )
        sim_res = run_what_if_simulation(db=db, request=what_if_req)
        what_if_data = sim_res.model_dump()

    # Specific Scenario: COMPARISON REPORT (Phase 5)
    comparison_data: Optional[List[Dict[str, Any]]] = None
    if request.report_type == ReportType.COMPARISON_REPORT:
        comp_loc_ids = [request.location_id]
        if request.comparison_location_ids:
            for c_id in request.comparison_location_ids:
                if c_id not in comp_loc_ids:
                    comp_loc_ids.append(c_id)

        comparison_data = []
        for loc_id in comp_loc_ids:
            c_loc = db.query(Location).filter(Location.id == loc_id).first()
            if not c_loc:
                continue
            c_q = db.query(AirQualityReading).filter(
                AirQualityReading.location_id == loc_id,
                AirQualityReading.quality_status == QualityStatus.VALID,
            )
            if start_time:
                c_q = c_q.filter(AirQualityReading.timestamp >= start_time)
            if end_time:
                c_q = c_q.filter(AirQualityReading.timestamp <= end_time)
            c_readings = c_q.all()
            c_aqi_records = [_get_or_create_aqi_record(r, db) for r in c_readings]
            c_aqis = [rec.aqi for rec in c_aqi_records if rec and rec.aqi is not None]
            c_stats = calculate_summary_statistics(c_aqis)
            latest_c_aqi = c_aqi_records[-1].aqi if c_aqi_records and c_aqi_records[-1] else None
            latest_c_cat = c_aqi_records[-1].category if c_aqi_records and c_aqi_records[-1] else "Unknown"

            comparison_data.append({
                "location_id": c_loc.id,
                "location_name": c_loc.name,
                "city": c_loc.city,
                "state": c_loc.state,
                "reading_count": len(c_readings),
                "latest_aqi": latest_c_aqi,
                "latest_category": latest_c_cat,
                "mean_aqi": c_stats["mean"],
                "min_aqi": c_stats["minimum"],
                "max_aqi": c_stats["maximum"],
            })

    # Period label
    if start_time and end_time:
        period_label = f"{start_time.strftime('%Y-%m-%d %H:%M UTC')} to {end_time.strftime('%Y-%m-%d %H:%M UTC')}"
    elif start_time:
        period_label = f"Since {start_time.strftime('%Y-%m-%d %H:%M UTC')}"
    elif end_time:
        period_label = f"Until {end_time.strftime('%Y-%m-%d %H:%M UTC')}"
    else:
        period_label = "Complete Historical Record"

    # Executive narrative
    exec_summary = (
        f"During the reporting period ({period_label}), {location.name} in {location.city} "
        f"recorded an average Air Quality Index of {aqi_stats['mean'] if aqi_stats['mean'] is not None else 'N/A'}, "
        f"spanning from a minimum of {aqi_stats['minimum'] if aqi_stats['minimum'] is not None else 'N/A'} "
        f"to a peak of {aqi_stats['maximum'] if aqi_stats['maximum'] is not None else 'N/A'}. "
        f"The most recent assessment measured an AQI of {latest_aqi if latest_aqi is not None else 'N/A'} "
        f"({latest_category or 'Unclassified'}), driven primarily by {dominant_pollutant or 'insufficient data'}. "
        f"Descriptive trend evaluation indicates a {trend_direction} trajectory over the analyzed window. "
        f"A total of {len(detected_anomalies)} statistical anomalies and {len(detected_events)} sustained pollution episodes were detected."
    )

    report_title_map = {
        ReportType.LOCATION_SUMMARY: "Location Environmental Summary Report",
        ReportType.PERIOD_REPORT: "Environmental Period Performance Report",
        ReportType.COMPARISON_REPORT: "Comparative Multi-Station Environmental Report",
        ReportType.WHAT_IF_REPORT: "Hypothetical What-If Pollution Impact Report",
    }

    return {
        "report_title": report_title_map.get(request.report_type, "Environmental Air Quality Report"),
        "report_type": request.report_type,
        "location": {
            "id": location.id,
            "name": location.name,
            "city": location.city,
            "state": location.state,
            "country": location.country,
            "latitude": location.latitude,
            "longitude": location.longitude,
            "description": location.description,
        },
        "period_label": period_label,
        "start_time": start_time.isoformat() if start_time else None,
        "end_time": end_time.isoformat() if end_time else None,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "provenance_summary": provenance_summary,
        "primary_source": primary_source,
        "latest_aqi": latest_aqi,
        "latest_category": latest_category,
        "dominant_pollutant": dominant_pollutant,
        "aqi_statistics": aqi_stats,
        "category_distribution": category_counts,
        "trend_direction": trend_direction,
        "pollutant_summary": pollutant_summary,
        "anomalies": detected_anomalies,
        "events": detected_events,
        "alerts": alerts_data,
        "forecast": forecast_data,
        "recommendations": recommendations_data,
        "what_if": what_if_data,
        "comparison": comparison_data,
        "executive_summary": exec_summary,
        "disclaimer": STANDARD_DISCLAIMER,
    }


def generate_report_preview(request: ReportGenerateRequest, db: Session) -> ReportPreviewResponse:
    """Generates structured JSON preview for fast client-side rendering."""
    data = compile_report_data(request=request, db=db)
    loc = data["location"]

    return ReportPreviewResponse(
        report_title=data["report_title"],
        report_type=data["report_type"],
        location_name=loc["name"],
        city=loc["city"],
        state=loc["state"],
        country=loc["country"],
        reporting_period=data["period_label"],
        generated_at=data["generated_at"],
        provenance_summary=data["provenance_summary"],
        latest_aqi=data["latest_aqi"],
        latest_category=data["latest_category"],
        dominant_pollutant=data["dominant_pollutant"],
        aqi_statistics=data["aqi_statistics"],
        category_distribution=data["category_distribution"],
        pollutant_summary=data["pollutant_summary"],
        trend_direction=data["trend_direction"],
        anomalies_count=len(data["anomalies"]),
        events_count=len(data["events"]),
        alerts_count=len(data["alerts"]),
        forecast_available=data["forecast"] is not None,
        forecast_summary=data["forecast"],
        top_recommendations=data["recommendations"],
        comparison_data=data["comparison"],
        what_if_summary=data["what_if"],
        executive_summary=data["executive_summary"],
        disclaimer=data["disclaimer"],
    )


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas for dynamic total page count ('Page X of Y')
    and running professional headers and footers.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 750, "AeroPulse AI — Environmental Air-Quality Analysis Report")
            self.drawRightString(558, 750, "CPCB NAQI Standard Architecture")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(54, 744, 558, 744)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(54, 45, 558, 45)
        self.drawString(54, 32, "Confidential & Informational • Software Analytics Only • Not Medical Advice")
        self.drawRightString(558, 32, f"Page {self._pageNumber} of {page_count}")
        self.restoreState()


def build_pdf_report(report_data: Dict[str, Any]) -> bytes:
    """
    Compiles a complete, publication-grade PDF report binary using ReportLab.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    styles = getSampleStyleSheet()
    
    # Custom typography
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#0d9488"),
    )
    h1_style = ParagraphStyle(
        "SectionH1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    bold_body = ParagraphStyle(
        "BoldBody",
        parent=body_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1e293b"),
    )
    cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=cell_style,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0f172a"),
    )
    alert_box_style = ParagraphStyle(
        "AlertBoxText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#991b1b"),
    )
    provenance_style = ParagraphStyle(
        "ProvenanceBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0f766e"),
    )

    story = []
    loc = report_data["location"]

    # 1. Header Banner
    header_table = Table(
        [
            [
                Paragraph(
                    "<b>AEROPULSE AI</b> &nbsp;|&nbsp; INTELLIGENT AIR QUALITY MONITORING & PREVENTION",
                    subtitle_style,
                ),
                Paragraph(f"Generated: {report_data['generated_at']}", cell_style),
            ],
            [
                Paragraph(report_data["report_title"], title_style),
                Paragraph(
                    f"<b>Station:</b> {loc['name']}<br/><b>City:</b> {loc['city']}, {loc['state']}",
                    cell_style,
                ),
            ],
        ],
        colWidths=[330, 174],
    )
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0d9488"), spaceAfter=10))

    # 2. Executive Summary Callout Box
    cat_name = report_data.get("latest_category") or "Unknown"
    cat_color = CPCB_COLORS.get(cat_name, colors.HexColor("#64748b"))

    summary_content = [
        [
            Paragraph("<b>EXECUTIVE ENVIRONMENTAL SUMMARY</b>", bold_body),
            Paragraph(
                f"<b>Current AQI: {report_data.get('latest_aqi') or 'N/A'}</b> &nbsp; "
                f"<font color='{cat_color.hexval()}'>({cat_name.upper()})</font>",
                bold_body,
            ),
        ],
        [
            Paragraph(report_data["executive_summary"], body_style),
            "",
        ],
    ]
    summary_table = Table(summary_content, colWidths=[360, 144])
    summary_table.setStyle(
        TableStyle([
            ("SPAN", (0, 1), (1, 1)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("LINEBEFORE", (0, 0), (0, -1), 3.5, colors.HexColor("#0d9488")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # 3. Provenance & Metadata Strip
    prov = report_data["provenance_summary"]
    prov_text = (
        f"<b>Data Provenance:</b> Observed Telemetry: <b>{prov['observed_provenance']}</b> | "
        f"Forecast Data: <b>{prov['forecast_provenance']}</b> | "
        f"Scenario Data: <b>{prov['scenario_provenance']}</b>"
    )
    prov_table = Table([[Paragraph(prov_text, provenance_style)]], colWidths=[504])
    prov_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ccfbf1")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#5eead4")),
            ("PADDING", (0, 0), (-1, -1), 5),
        ])
    )
    story.append(prov_table)
    story.append(Spacer(1, 10))

    # 4. Section 1: Location & Observation Period Information
    story.append(Paragraph("1. Monitoring Station & Geography", h1_style))
    loc_grid = [
        [
            Paragraph("<b>Station Name:</b>", cell_bold),
            Paragraph(loc["name"], cell_style),
            Paragraph("<b>Coordinates:</b>", cell_bold),
            Paragraph(f"{loc['latitude']:.4f}°N, {loc['longitude']:.4f}°E" if loc['latitude'] else "N/A", cell_style),
        ],
        [
            Paragraph("<b>City / State:</b>", cell_bold),
            Paragraph(f"{loc['city']}, {loc['state']}", cell_style),
            Paragraph("<b>Country:</b>", cell_bold),
            Paragraph(loc["country"], cell_style),
        ],
        [
            Paragraph("<b>Reporting Period:</b>", cell_bold),
            Paragraph(report_data["period_label"], cell_style),
            Paragraph("<b>Primary Source:</b>", cell_bold),
            Paragraph(report_data["primary_source"], cell_style),
        ],
    ]
    loc_table = Table(loc_grid, colWidths=[100, 152, 100, 152])
    loc_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#ffffff")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("PADDING", (0, 0), (-1, -1), 4),
        ])
    )
    story.append(loc_table)
    story.append(Spacer(1, 10))

    # 5. Section 2: AQI Overview & Category Distribution
    story.append(Paragraph("2. Air Quality Index (CPCB NAQI) Overview", h1_style))
    aqi_st = report_data["aqi_statistics"]
    aqi_overview_grid = [
        [
            Paragraph("<b>Metric</b>", cell_bold),
            Paragraph("<b>Value</b>", cell_bold),
            Paragraph("<b>Metric</b>", cell_bold),
            Paragraph("<b>Value</b>", cell_bold),
        ],
        [
            Paragraph("Latest AQI", cell_style),
            Paragraph(f"<b>{report_data.get('latest_aqi') or 'N/A'}</b>", cell_style),
            Paragraph("Latest Category", cell_style),
            Paragraph(f"<font color='{cat_color.hexval()}'><b>{cat_name}</b></font>", cell_style),
        ],
        [
            Paragraph("Mean AQI", cell_style),
            Paragraph(str(aqi_st.get("mean") or "N/A"), cell_style),
            Paragraph("Dominant Pollutant", cell_style),
            Paragraph(report_data.get("dominant_pollutant") or "N/A", cell_style),
        ],
        [
            Paragraph("Minimum AQI", cell_style),
            Paragraph(str(aqi_st.get("minimum") or "N/A"), cell_style),
            Paragraph("AQI Trend", cell_style),
            Paragraph(report_data.get("trend_direction") or "N/A", cell_style),
        ],
        [
            Paragraph("Maximum AQI", cell_style),
            Paragraph(str(aqi_st.get("maximum") or "N/A"), cell_style),
            Paragraph("Observations Count", cell_style),
            Paragraph(str(aqi_st.get("count") or "0"), cell_style),
        ],
    ]
    aqi_table = Table(aqi_overview_grid, colWidths=[120, 132, 120, 132])
    aqi_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("PADDING", (0, 0), (-1, -1), 3.5),
        ])
    )
    story.append(aqi_table)
    story.append(Spacer(1, 10))

    # 6. Section 3: Detailed Pollutant Analysis
    story.append(Paragraph("3. Multi-Pollutant Detailed Analysis", h1_style))
    poll_grid = [
        [
            Paragraph("<b>Pollutant</b>", cell_bold),
            Paragraph("<b>Unit</b>", cell_bold),
            Paragraph("<b>Min</b>", cell_bold),
            Paragraph("<b>Mean</b>", cell_bold),
            Paragraph("<b>Max</b>", cell_bold),
            Paragraph("<b>Latest</b>", cell_bold),
            Paragraph("<b>Trend</b>", cell_bold),
        ]
    ]

    for p_key in SUPPORTED_POLLUTANTS:
        p_info = report_data["pollutant_summary"].get(p_key, {})
        if not p_info.get("available", False):
            poll_grid.append([
                Paragraph(f"<b>{POLLUTANT_METADATA[p_key]['label']}</b>", cell_style),
                Paragraph(POLLUTANT_METADATA[p_key]["unit"], cell_style),
                Paragraph("<font color='#94a3b8'>Unavailable</font>", cell_style),
                Paragraph("<font color='#94a3b8'>-</font>", cell_style),
                Paragraph("<font color='#94a3b8'>-</font>", cell_style),
                Paragraph("<font color='#94a3b8'>-</font>", cell_style),
                Paragraph("<font color='#94a3b8'>No data</font>", cell_style),
            ])
        else:
            st = p_info.get("statistics", {})
            latest_v = p_info.get("latest")
            poll_grid.append([
                Paragraph(f"<b>{p_info.get('label')}</b>", cell_style),
                Paragraph(p_info.get("unit"), cell_style),
                Paragraph(str(st.get("minimum") if st.get("minimum") is not None else "N/A"), cell_style),
                Paragraph(str(st.get("mean") if st.get("mean") is not None else "N/A"), cell_style),
                Paragraph(str(st.get("maximum") if st.get("maximum") is not None else "N/A"), cell_style),
                Paragraph(str(latest_v if latest_v is not None else "N/A"), cell_style),
                Paragraph(p_info.get("trend") or "STABLE", cell_style),
            ])

    poll_table = Table(poll_grid, colWidths=[70, 50, 60, 65, 60, 65, 134])
    poll_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("PADDING", (0, 0), (-1, -1), 3),
        ])
    )
    story.append(poll_table)
    story.append(Spacer(1, 10))

    # 7. Section 4: Anomalies & Sustained Pollution Episodes
    story.append(Paragraph("4. Anomalies & Sustained Episodes", h1_style))
    anomalies = report_data.get("anomalies", [])
    events = report_data.get("events", [])

    if not anomalies and not events:
        story.append(
            Paragraph("No statistical anomalies or sustained pollution episodes detected during this observation period.", body_style)
        )
    else:
        if anomalies:
            story.append(Paragraph("<b>Statistical Anomalies (Z-Score ≥ 2.5):</b>", cell_bold))
            anom_grid = [
                [
                    Paragraph("<b>Timestamp</b>", cell_bold),
                    Paragraph("<b>Observed</b>", cell_bold),
                    Paragraph("<b>Expected</b>", cell_bold),
                    Paragraph("<b>Severity</b>", cell_bold),
                    Paragraph("<b>Statistical Reason</b>", cell_bold),
                ]
            ]
            for a in anomalies[:5]:
                anom_grid.append([
                    Paragraph(str(a.get("timestamp"))[:19], cell_style),
                    Paragraph(str(a.get("observed_value")), cell_style),
                    Paragraph(str(a.get("expected_value")), cell_style),
                    Paragraph(str(a.get("severity")), cell_style),
                    Paragraph(str(a.get("reason")), cell_style),
                ])
            anom_table = Table(anom_grid, colWidths=[110, 55, 55, 60, 224])
            anom_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fee2e2")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#fca5a5")),
                    ("PADDING", (0, 0), (-1, -1), 3),
                ])
            )
            story.append(anom_table)
            story.append(Spacer(1, 6))

        if events:
            story.append(Paragraph("<b>Sustained Pollution Episodes (AQI ≥ 201 for ≥ 2h):</b>", cell_bold))
            event_grid = [
                [
                    Paragraph("<b>Start Window</b>", cell_bold),
                    Paragraph("<b>End Window</b>", cell_bold),
                    Paragraph("<b>Duration</b>", cell_bold),
                    Paragraph("<b>Peak AQI</b>", cell_bold),
                    Paragraph("<b>Dominant</b>", cell_bold),
                ]
            ]
            for e in events[:5]:
                event_grid.append([
                    Paragraph(str(e.get("start_time"))[:19], cell_style),
                    Paragraph(str(e.get("end_time"))[:19], cell_style),
                    Paragraph(f"{e.get('duration_hours', 0):.1f}h", cell_style),
                    Paragraph(str(e.get("max_aqi")), cell_style),
                    Paragraph(str(e.get("dominant_pollutant")), cell_style),
                ])
            event_table = Table(event_grid, colWidths=[120, 120, 70, 70, 124])
            event_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ffedd5")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#fdba74")),
                    ("PADDING", (0, 0), (-1, -1), 3),
                ])
            )
            story.append(event_table)

    story.append(Spacer(1, 10))

    # 8. Section 5: Automated Alerts Log
    story.append(Paragraph("5. Automated Threshold & Forecast Alerts", h1_style))
    alerts_list = report_data.get("alerts", [])
    if not alerts_list:
        story.append(Paragraph("No automated threshold alerts were triggered during this period.", body_style))
    else:
        alert_grid = [
            [
                Paragraph("<b>Triggered At</b>", cell_bold),
                Paragraph("<b>Classification</b>", cell_bold),
                Paragraph("<b>Severity</b>", cell_bold),
                Paragraph("<b>Observed / Threshold</b>", cell_bold),
                Paragraph("<b>Alert Details</b>", cell_bold),
            ]
        ]
        for al in alerts_list[:6]:
            tag_display = f"<font color='#d97706'><b>{al['tag']}</b></font>" if al["is_predicted"] else al["tag"]
            alert_grid.append([
                Paragraph(str(al.get("triggered_at"))[:19], cell_style),
                Paragraph(tag_display, cell_style),
                Paragraph(al.get("severity", "WARNING"), cell_style),
                Paragraph(f"{al.get('current_value')} / {al.get('threshold_value')}", cell_style),
                Paragraph(al.get("message", "-"), cell_style),
            ])
        alert_table = Table(alert_grid, colWidths=[100, 100, 60, 94, 150])
        alert_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("PADDING", (0, 0), (-1, -1), 3),
            ])
        )
        story.append(alert_table)

    story.append(Spacer(1, 10))

    # 9. Section 6: Machine Learning Forecasts
    story.append(Paragraph("6. Machine Learning Forecasts (Phase 9 ML)", h1_style))
    forecast = report_data.get("forecast")
    if not forecast:
        story.append(
            Paragraph(
                "<i>Machine learning prediction data is unavailable for this station during the selected window.</i>",
                body_style,
            )
        )
    else:
        fc_box_text = (
            "<b>[IMPORTANT MANDATORY PROVENANCE NOTICE: FORECAST — NOT CURRENT OBSERVATION]</b><br/>"
            f"Model: <b>{forecast.get('model_name')}</b> &nbsp;|&nbsp; "
            f"Horizon: <b>+{forecast.get('horizon_hours')} Hours</b> &nbsp;|&nbsp; "
            f"Target Timestamp: <b>{forecast.get('target_timestamp')}</b><br/>"
            f"Predicted AQI: <b>{forecast.get('predicted_aqi')}</b> &nbsp;|&nbsp; "
            f"Predicted Category: <b>{forecast.get('predicted_category')}</b> &nbsp;|&nbsp; "
            f"Model Accuracy (Test): MAE: {forecast.get('mae')} | RMSE: {forecast.get('rmse')} | R²: {forecast.get('r2')}"
        )
        fc_table = Table([[Paragraph(fc_box_text, alert_box_style)]], colWidths=[504])
        fc_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef2f2")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f87171")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(fc_table)

    story.append(Spacer(1, 10))

    # 10. Section 7: Preventive Recommendations
    story.append(Paragraph("7. Explainable Preventive Guidance (Phase 11)", h1_style))
    recs = report_data.get("recommendations", [])
    if not recs:
        story.append(Paragraph("No active preventive recommendations recorded for this state.", body_style))
    else:
        rec_grid = [
            [
                Paragraph("<b>Priority</b>", cell_bold),
                Paragraph("<b>Type</b>", cell_bold),
                Paragraph("<b>Recommended Action</b>", cell_bold),
                Paragraph("<b>Explainable Rationale & Telemetry Trigger</b>", cell_bold),
            ]
        ]
        for r in recs:
            rec_grid.append([
                Paragraph(f"<b>{r.get('priority')}</b>", cell_style),
                Paragraph(r.get("type", "").replace("_", " "), cell_style),
                Paragraph(f"<b>{r.get('action')}</b>", cell_style),
                Paragraph(f"{r.get('reason')}<br/><i>Triggered by: {r.get('triggered_by')}</i>", cell_style),
            ])
        rec_table = Table(rec_grid, colWidths=[65, 85, 160, 194])
        rec_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(rec_table)

    story.append(Spacer(1, 10))

    # 11. Section 8: WHAT-IF SCENARIO (If applicable)
    what_if = report_data.get("what_if")
    if report_data["report_type"] == ReportType.WHAT_IF_REPORT and what_if:
        story.append(PageBreak())
        story.append(Paragraph("8. What-If Scenario Simulation (Phase 12)", h1_style))
        wi_banner_text = (
            "<b>[HYPOTHETICAL SIMULATION ADVISORY: WHAT-IF / SIMULATED SCENARIO — NOT AN ACTUAL MEASUREMENT]</b><br/>"
            "This section evaluates a purely hypothetical mathematical modification of atmospheric telemetry "
            "using the official CPCB NAQI standard. No physical measurements were altered in the database."
        )
        wi_banner = Table([[Paragraph(wi_banner_text, alert_box_style)]], colWidths=[504])
        wi_banner.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f59e0b")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(wi_banner)
        story.append(Spacer(1, 8))

        impact = what_if.get("impact", {})
        baseline = what_if.get("baseline", {})
        scenario = what_if.get("scenario", {})
        threshold = what_if.get("threshold_impact", {})

        wi_grid = [
            [
                Paragraph("<b>Parameter</b>", cell_bold),
                Paragraph("<b>Baseline State</b>", cell_bold),
                Paragraph("<b>Simulated Scenario</b>", cell_bold),
                Paragraph("<b>Impact / Transition</b>", cell_bold),
            ],
            [
                Paragraph("Air Quality Index (AQI)", cell_style),
                Paragraph(str(baseline.get("aqi")), cell_style),
                Paragraph(str(scenario.get("simulated_aqi")), cell_style),
                Paragraph(
                    f"Δ {impact.get('aqi_delta')} ({impact.get('aqi_percent_delta')}%) — {impact.get('direction')}",
                    cell_style,
                ),
            ],
            [
                Paragraph("CPCB Category", cell_style),
                Paragraph(str(baseline.get("category")), cell_style),
                Paragraph(str(scenario.get("category")), cell_style),
                Paragraph(str(impact.get("category_transition")), cell_style),
            ],
            [
                Paragraph("Dominant Pollutant", cell_style),
                Paragraph(str(baseline.get("dominant_pollutant")), cell_style),
                Paragraph(str(scenario.get("dominant_pollutant")), cell_style),
                Paragraph(
                    f"Shifted: {'Yes' if impact.get('dominant_pollutant_changed') else 'No'}",
                    cell_style,
                ),
            ],
            [
                Paragraph("Threshold Crossing Alert", cell_style),
                Paragraph("In-Memory Evaluation", cell_style),
                Paragraph(
                    "<b>CROSSES THRESHOLD</b>" if threshold.get("crosses_threshold") else "No Violation",
                    cell_style,
                ),
                Paragraph(threshold.get("message") or "Within standard limits", cell_style),
            ],
        ]
        wi_table = Table(wi_grid, colWidths=[120, 110, 110, 164])
        wi_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 4),
            ])
        )
        story.append(wi_table)
        story.append(Spacer(1, 8))

        story.append(Paragraph(f"<b>Scenario Explanation:</b> {impact.get('explanation')}", body_style))
        story.append(Spacer(1, 10))

    # 12. Section 9: COMPARISON REPORT (If applicable)
    comparison = report_data.get("comparison")
    if report_data["report_type"] == ReportType.COMPARISON_REPORT and comparison:
        story.append(PageBreak())
        story.append(Paragraph("8. Multi-Station Factual Comparison (Phase 5)", h1_style))
        comp_grid = [
            [
                Paragraph("<b>Station Name</b>", cell_bold),
                Paragraph("<b>City / State</b>", cell_bold),
                Paragraph("<b>Latest AQI</b>", cell_bold),
                Paragraph("<b>Category</b>", cell_bold),
                Paragraph("<b>Mean AQI</b>", cell_bold),
                Paragraph("<b>Min AQI</b>", cell_bold),
                Paragraph("<b>Max AQI</b>", cell_bold),
            ]
        ]
        for item in comparison:
            comp_grid.append([
                Paragraph(item.get("location_name"), cell_style),
                Paragraph(f"{item.get('city')}, {item.get('state')}", cell_style),
                Paragraph(str(item.get("latest_aqi") or "N/A"), cell_style),
                Paragraph(str(item.get("latest_category") or "N/A"), cell_style),
                Paragraph(str(item.get("mean_aqi") or "N/A"), cell_style),
                Paragraph(str(item.get("min_aqi") or "N/A"), cell_style),
                Paragraph(str(item.get("max_aqi") or "N/A"), cell_style),
            ])
        comp_table = Table(comp_grid, colWidths=[100, 100, 50, 74, 60, 60, 60])
        comp_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("PADDING", (0, 0), (-1, -1), 3.5),
            ])
        )
        story.append(comp_table)
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                "<i>Note: Stations are presented factually without subjective rankings (e.g. 'best' or 'worst').</i>",
                body_style,
            )
        )
        story.append(Spacer(1, 10))

    # 13. Section: Technical Methodology & CPCB NAQI Standards
    story.append(KeepTogether([
        Paragraph("Technical Methodology & Limitations", h1_style),
        Paragraph(
            "<b>CPCB NAQI Standard:</b> Overall AQI is computed via linear interpolation across official Indian "
            "Central Pollution Control Board concentration breakpoints for up to 8 criteria pollutants (PM2.5, PM10, "
            "NO2, SO2, CO, O3, NH3, Pb). The maximum sub-index dictates the overall AQI, provided sufficiency rules "
            "are satisfied (at least 3 pollutants monitored, with at least PM2.5 or PM10 present).",
            body_style,
        ),
        Spacer(1, 4),
        Paragraph(
            "<b>Descriptive Analytics & Event Engine:</b> Trend trajectories utilize a 5% hysteresis band comparing "
            "recent vs baseline halves. Statistical anomalies are identified through Z-score standard deviation thresholds (≥2.5). "
            "Sustained episodes require AQI ≥ 201 continuously for at least 2 hours.",
            body_style,
        ),
        Spacer(1, 6),
        Paragraph(f"<b>System Advisory & Medical Disclaimer:</b> {STANDARD_DISCLAIMER}", body_style),
    ]))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()
