"""
FastAPI router for Phase 13 Automated Environmental & Air-Quality Report Generator.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.api.deps import get_current_user
from backend.app.models.user import User
from backend.app.schemas.report import (
    ReportGenerateRequest,
    ReportPreviewResponse,
)
from backend.app.services.report_service import (
    compile_report_data,
    generate_report_preview,
    build_pdf_report,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post(
    "/preview",
    response_model=ReportPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview Environmental Report Summary",
)
def preview_report(
    request: ReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Statelessly aggregates telemetry, descriptive analytics, anomalies,
    forecasts, alerts, and preventive recommendations into a structured preview.
    Non-destructive with zero database writes.
    """
    return generate_report_preview(request=request, db=db)


@router.post(
    "/generate",
    status_code=status.HTTP_200_OK,
    summary="Generate Publication-Grade PDF Report",
)
def generate_report_pdf(
    request: ReportGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dynamically generates and streams a publication-grade PDF report
    via ReportLab. Strictly non-destructive and stateless.
    """
    report_data = compile_report_data(request=request, db=db)
    pdf_bytes = build_pdf_report(report_data=report_data)

    loc_slug = report_data["location"]["city"].replace(" ", "_")
    timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"AeroPulse_Report_{request.report_type.value}_{loc_slug}_{timestamp_slug}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Report-Type": request.report_type.value,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Report-Type",
        },
    )
