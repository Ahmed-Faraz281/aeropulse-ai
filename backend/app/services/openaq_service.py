from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.schemas.openaq import (
    OpenAQCoverageNormalized,
    OpenAQHourlyMeasurement,
    OpenAQLocationNormalized,
    OpenAQSensorHoursResponse,
    OpenAQSensorNormalized,
    OpenAQSensorSummary,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Domain Exceptions (Credentials never included in message or repr)
# ==============================================================================

class OpenAQError(Exception):
    """Base exception for all OpenAQ operations."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.message!r})"


class OpenAQConfigError(OpenAQError):
    """Raised when OPENAQ_API_KEY is not configured or missing."""
    pass


class OpenAQAuthError(OpenAQError):
    """Raised when OpenAQ upstream returns 401 Unauthorized or 403 Forbidden."""
    pass


class OpenAQNotFoundError(OpenAQError):
    """Raised when an OpenAQ upstream resource is not found (404)."""
    pass


class OpenAQRatelimitError(OpenAQError):
    """Raised when OpenAQ upstream returns 429 Too Many Requests."""
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after


class OpenAQUpstreamError(OpenAQError):
    """Raised on upstream 5xx errors or malformed payloads."""
    pass


class OpenAQTimeoutError(OpenAQError):
    """Raised on connection or read timeouts."""
    pass


class OpenAQValidationError(OpenAQError):
    """Raised when input parameters fail OpenAQ constraints."""
    pass


# ==============================================================================
# Helper Utilities
# ==============================================================================

def parse_iso_datetime(val: Any) -> Optional[datetime]:
    """Parse ISO datetime safely from string or nested dict."""
    if not val:
        return None
    if isinstance(val, dict):
        val = val.get("utc") or val.get("local")
    if not isinstance(val, str):
        return None
    try:
        cleaned = val.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ==============================================================================
# OpenAQ Service Implementation
# ==============================================================================

class OpenAQService:
    """
    Authenticated connector and discovery client for the OpenAQ API v3.
    Strictly read-only; does not write to database or trigger downstream tasks.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.OPENAQ_API_KEY
        self.base_url = (base_url or settings.OPENAQ_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.OPENAQ_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.OPENAQ_MAX_RETRIES
        self._custom_client = client

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=self.timeout)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an HTTP request against the OpenAQ API v3.
        Safety and retry rules:
        - Must have valid api_key configured; raises OpenAQConfigError otherwise.
        - Fast-fail without retry on 401, 403, 404, 422, or 429.
        - On 429: preserve Retry-After header, raise OpenAQRatelimitError without consuming quota.
        - On transient 5xx or connection/read timeout: allow at most 1 controlled retry (max_retries).
        """
        if not self.api_key or not self.api_key.strip():
            raise OpenAQConfigError("OpenAQ API key is not configured. Set OPENAQ_API_KEY in .env")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "X-API-Key": self.api_key,
            "User-Agent": "AeroPulse-AI/1.0",
            "Accept": "application/json",
        }

        # Filter out None params
        cleaned_params = {k: v for k, v in (params or {}).items() if v is not None}

        client = self._get_client()
        should_close_client = self._custom_client is None

        attempt = 0
        try:
            while attempt <= self.max_retries:
                try:
                    response = client.request(
                        method=method,
                        url=url,
                        params=cleaned_params,
                        headers=headers,
                    )
                    status_code = response.status_code

                    # Fast-fail without retry on client errors and rate limits
                    if status_code in (401, 403):
                        raise OpenAQAuthError(
                            f"OpenAQ authentication failed with HTTP {status_code}"
                        )
                    if status_code == 404:
                        raise OpenAQNotFoundError(
                            f"OpenAQ resource not found at '{endpoint}'"
                        )
                    if status_code == 422:
                        raise OpenAQValidationError(
                            f"OpenAQ rejected request with validation error: {response.text}"
                        )
                    if status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        retry_sec: Optional[int] = None
                        if retry_after and retry_after.isdigit():
                            retry_sec = int(retry_after)
                        raise OpenAQRatelimitError(
                            "OpenAQ rate limit exceeded (HTTP 429)",
                            retry_after=retry_sec,
                        )

                    # Transient server errors: allow at most 1 controlled retry
                    if 500 <= status_code <= 599:
                        if attempt < self.max_retries:
                            attempt += 1
                            time.sleep(0.5)
                            continue
                        raise OpenAQUpstreamError(
                            f"OpenAQ upstream server error (HTTP {status_code})"
                        )

                    if not (200 <= status_code < 300):
                        raise OpenAQUpstreamError(
                            f"OpenAQ returned unexpected HTTP {status_code}: {response.text}"
                        )

                    try:
                        return response.json()
                    except Exception as json_err:
                        raise OpenAQUpstreamError(
                            f"Failed to decode OpenAQ response JSON: {json_err}"
                        ) from None

                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout):
                    if attempt < self.max_retries:
                        attempt += 1
                        time.sleep(0.5)
                        continue
                    raise OpenAQTimeoutError("OpenAQ request timed out") from None
                except (httpx.ConnectError, httpx.NetworkError):
                    if attempt < self.max_retries:
                        attempt += 1
                        time.sleep(0.5)
                        continue
                    raise OpenAQUpstreamError("OpenAQ network connection failure") from None
                except (OpenAQError, Exception):
                    raise
        finally:
            if should_close_client:
                client.close()

    # ==========================================================================
    # Location Operations
    # ==========================================================================

    def get_location(self, location_id: int) -> OpenAQLocationNormalized:
        """Fetch and normalize details for an OpenAQ location by ID."""
        data = self._request("GET", f"/locations/{location_id}")
        results = data.get("results")
        if not results:
            raise OpenAQNotFoundError(f"Location with ID {location_id} not found")

        raw = results[0]
        return self._normalize_location(raw)

    def search_locations(
        self,
        query: Optional[str] = None,
        country: Optional[str] = None,
        coordinates: Optional[str] = None,
        radius: Optional[int] = None,
        limit: int = 20,
        page: int = 1,
    ) -> List[OpenAQLocationNormalized]:
        """
        Search OpenAQ locations with strict radius constraint validation:
        - radius must be >= 0 and <= 25,000 meters.
        - coordinates must be a valid latitude,longitude pair.
        - Does NOT silently clamp invalid values; raises OpenAQValidationError.
        """
        if radius is not None:
            if radius < 0 or radius > 25000:
                raise OpenAQValidationError(
                    f"Radius must be between 0 and 25,000 meters. Received: {radius}"
                )

        if coordinates is not None:
            parts = [p.strip() for p in coordinates.split(",")]
            if len(parts) != 2:
                raise OpenAQValidationError(
                    "Coordinates must be in 'latitude,longitude' format"
                )
            try:
                lat = float(parts[0])
                lon = float(parts[1])
            except ValueError:
                raise OpenAQValidationError("Coordinates must contain valid float numbers")
            if not (-90.0 <= lat <= 90.0):
                raise OpenAQValidationError("Latitude must be between -90 and 90 degrees")
            if not (-180.0 <= lon <= 180.0):
                raise OpenAQValidationError("Longitude must be between -180 and 180 degrees")

        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
        }
        if query:
            params["query"] = query
        if country:
            params["country"] = country
        if coordinates:
            params["coordinates"] = coordinates
        if radius is not None:
            params["radius"] = radius

        data = self._request("GET", "/locations", params=params)
        results = data.get("results", [])
        return [self._normalize_location(item) for item in results]

    # ==========================================================================
    # Sensor Operations
    # ==========================================================================

    def get_location_sensors(self, location_id: int) -> List[OpenAQSensorNormalized]:
        """Fetch all normalized sensors associated with a location."""
        data = self._request("GET", f"/locations/{location_id}/sensors")
        results = data.get("results", [])
        return [self._normalize_sensor(item, location_id=location_id) for item in results]

    def get_sensor(self, sensor_id: int) -> OpenAQSensorNormalized:
        """Fetch detailed metadata for a single sensor."""
        data = self._request("GET", f"/sensors/{sensor_id}")
        results = data.get("results")
        if not results:
            raise OpenAQNotFoundError(f"Sensor with ID {sensor_id} not found")
        return self._normalize_sensor(results[0])

    def get_sensor_hours(
        self,
        sensor_id: int,
        limit: int = 24,
        datetime_from: Optional[datetime] = None,
        datetime_to: Optional[datetime] = None,
    ) -> OpenAQSensorHoursResponse:
        """Fetch normalized hourly measurements for a sensor."""
        params: Dict[str, Any] = {"limit": limit}
        if datetime_from:
            params["datetime_from"] = datetime_from.isoformat()
        if datetime_to:
            params["datetime_to"] = datetime_to.isoformat()

        data = self._request("GET", f"/sensors/{sensor_id}/hours", params=params)
        results = data.get("results", [])

        # Fetch sensor metadata to supply parameter_name and units
        sensor_meta = self.get_sensor(sensor_id)

        measurements: List[OpenAQHourlyMeasurement] = []
        for item in results:
            period = item.get("period", {})
            dt_from_raw = period.get("datetimeFrom", {})
            dt_to_raw = period.get("datetimeTo", {})

            dt_from_utc = parse_iso_datetime(dt_from_raw)
            dt_to_utc = parse_iso_datetime(dt_to_raw)

            # Require valid UTC dates
            if not dt_from_utc or not dt_to_utc:
                continue

            dt_from_local = dt_from_raw.get("local") if isinstance(dt_from_raw, dict) else None
            dt_to_local = dt_to_raw.get("local") if isinstance(dt_to_raw, dict) else None

            coverage = item.get("coverage", {})
            cov_percent = coverage.get("percentComplete") or coverage.get("percentCoverage")
            cov_count = coverage.get("observedCount")

            val = item.get("value")
            if val is not None:
                measurements.append(
                    OpenAQHourlyMeasurement(
                        datetime_from_utc=dt_from_utc,
                        datetime_to_utc=dt_to_utc,
                        datetime_from_local=dt_from_local,
                        datetime_to_local=dt_to_local,
                        value=float(val),
                        coverage_percent=float(cov_percent) if cov_percent is not None else None,
                        coverage_count=int(cov_count) if cov_count is not None else None,
                    )
                )

        return OpenAQSensorHoursResponse(
            sensor_id=sensor_id,
            parameter_name=sensor_meta.parameter_name,
            units=sensor_meta.units,
            period="hours",
            total_records=len(measurements),
            measurements=measurements,
        )

    # ==========================================================================
    # Normalization Helpers
    # ==========================================================================

    def _normalize_location(self, raw: Dict[str, Any]) -> OpenAQLocationNormalized:
        coords = raw.get("coordinates") or {}
        country = raw.get("country") or {}
        owner = raw.get("owner") or {}
        provider = raw.get("provider") or {}

        # Instruments can be list of dicts [{"name": "..."}] or strings
        instruments_raw = raw.get("instruments") or []
        instruments: List[str] = []
        for inst in instruments_raw:
            if isinstance(inst, dict) and "name" in inst:
                instruments.append(str(inst["name"]))
            elif isinstance(inst, str):
                instruments.append(inst)

        # Sensors summaries
        sensors_raw = raw.get("sensors") or []
        sensor_summaries: List[OpenAQSensorSummary] = []
        for s in sensors_raw:
            param = s.get("parameter") or {}
            param_name = param.get("name") or s.get("name") or "unknown"
            units = param.get("units") or s.get("units") or ""
            sensor_summaries.append(
                OpenAQSensorSummary(
                    id=s.get("id"),
                    name=s.get("name"),
                    parameter_id=param.get("id"),
                    parameter_name=param_name,
                    parameter_display_name=param.get("displayName"),
                    units=units,
                )
            )

        return OpenAQLocationNormalized(
            id=raw.get("id"),
            name=raw.get("name") or f"Location #{raw.get('id')}",
            locality=raw.get("locality"),
            timezone=raw.get("timezone"),
            country_code=country.get("code") if isinstance(country, dict) else None,
            country_name=country.get("name") if isinstance(country, dict) else (country if isinstance(country, str) else None),
            owner_name=owner.get("name") if isinstance(owner, dict) else None,
            provider_name=provider.get("name") if isinstance(provider, dict) else None,
            latitude=coords.get("latitude"),
            longitude=coords.get("longitude"),
            is_mobile=bool(raw.get("isMobile", False)),
            is_monitor=bool(raw.get("isMonitor", True)),
            instruments=instruments,
            sensors=sensor_summaries,
            datetime_first=parse_iso_datetime(raw.get("datetimeFirst")),
            datetime_last=parse_iso_datetime(raw.get("datetimeLast")),
        )

    def _normalize_sensor(
        self,
        raw: Dict[str, Any],
        location_id: Optional[int] = None,
    ) -> OpenAQSensorNormalized:
        param = raw.get("parameter") or {}
        param_name = param.get("name") or raw.get("name") or "unknown"
        units = param.get("units") or raw.get("units") or ""

        coverage_raw = raw.get("coverage") or {}
        coverage = OpenAQCoverageNormalized(
            expected_count=coverage_raw.get("expectedCount"),
            observed_count=coverage_raw.get("observedCount"),
            percent_complete=coverage_raw.get("percentComplete"),
            percent_coverage=coverage_raw.get("percentCoverage"),
            observed_interval=coverage_raw.get("observedInterval"),
        ) if coverage_raw else None

        summary_raw = raw.get("summary") or {}
        dt_first = parse_iso_datetime(raw.get("datetimeFirst"))
        dt_last = parse_iso_datetime(raw.get("datetimeLast"))

        # Derive is_active safely:
        # User Correction 1: Do not assume sensor-level is_active exists upstream.
        # Derived as True if datetime_last is within last 7 days of current UTC time;
        # False if older; None if datetime_last is missing.
        is_active: Optional[bool] = None
        if dt_last:
            diff_seconds = (datetime.now(timezone.utc) - dt_last).total_seconds()
            is_active = diff_seconds < (7 * 86400)

        loc_id = location_id or raw.get("locationId") or (raw.get("location", {}).get("id") if isinstance(raw.get("location"), dict) else None)

        return OpenAQSensorNormalized(
            id=raw.get("id"),
            name=raw.get("name"),
            parameter_id=param.get("id"),
            parameter_name=param_name,
            parameter_display_name=param.get("displayName"),
            units=units,
            location_id=loc_id,
            is_active=is_active,
            datetime_first=dt_first,
            datetime_last=dt_last,
            coverage=coverage,
            summary_min=summary_raw.get("min"),
            summary_max=summary_raw.get("max"),
            summary_avg=summary_raw.get("avg"),
        )


# Singleton factory for dependency injection
def get_openaq_service() -> OpenAQService:
    return OpenAQService()
