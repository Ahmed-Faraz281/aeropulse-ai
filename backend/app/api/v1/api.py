from fastapi import APIRouter
from backend.app.api.v1 import (
    analytics,
    aqi,
    air_quality,
    auth,
    data_sources,
    health,
    locations,
    prediction,
    simulation,
    alerts,
    recommendations,
    what_if,
    reports,
    admin,
    openaq,
    location_workflow,
    automation,
    trust,
)

api_router = APIRouter()

# Register Health check router
api_router.include_router(health.router, prefix="/health", tags=["Health"])

# Register Authentication router
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# Register Locations router
api_router.include_router(locations.router, prefix="/locations", tags=["Locations"])

# Register Data Sources router
api_router.include_router(data_sources.router, prefix="/data-sources", tags=["Data Sources"])

# Register Air Quality Readings router
api_router.include_router(air_quality.router, prefix="/air-quality", tags=["Air Quality"])

# Register AQI Calculation router
api_router.include_router(aqi.router, prefix="/aqi", tags=["AQI"])

# Register Analytics & Trends router
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])

# Register Simulation Engine router
api_router.include_router(simulation.router, prefix="/simulation", tags=["Simulation"])

# Register ML Prediction router
api_router.include_router(prediction.router, tags=["ML Prediction"])

# Register Automated Alerts router
api_router.include_router(alerts.router, tags=["Automated Alerts"])

# Register Recommendations router
api_router.include_router(recommendations.router, tags=["Recommendations"])

# Register What-If Simulation router
api_router.include_router(what_if.router, tags=["What-If Simulation"])

# Register Reports Generator router
api_router.include_router(reports.router, tags=["Reports"])

# Register Administration router
api_router.include_router(admin.router)

# Register OpenAQ API v3 Connector router (Phase 17 Step 1)
api_router.include_router(openaq.router, prefix="/openaq", tags=["OpenAQ Connector"])

# Register Location-Based Workflow Orchestration router (Phase 17 Step 4)
api_router.include_router(
    location_workflow.router,
    prefix="/location-workflow",
    tags=["Location Workflow"],
)

# Register Intelligent Continuous Monitoring & Automation router (Phase 18)
api_router.include_router(automation.router)

# Register Production Data Quality, Reliability & Trust Layer router (Phase 19)
api_router.include_router(trust.router)




