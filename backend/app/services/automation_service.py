import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models.location import Location
from backend.app.schemas.automation import (
    AutomationCycleSummary,
    AutomationStatusResponse,
)
from backend.app.schemas.openaq import OpenAQIngestRequest
from backend.app.services.openaq_ingestion_service import OpenAQIngestionService
from backend.app.services.openaq_service import OpenAQRatelimitError

logger = logging.getLogger(__name__)


class AutomationSupervisor:
    """
    Asynchronous supervisor for intelligent continuous monitoring and background automation.
    Manages an autonomous asyncio worker loop, concurrency protection, upstream rate-limit backoff,
    and operational observability without external scheduler dependencies.
    """

    def __init__(self):
        self._enabled = settings.SCHEDULER_ENABLED
        self._paused = False
        self._status = "IDLE" if self._enabled else "DISABLED"
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Operational metrics and status
        self._last_run: Optional[datetime] = None
        self._next_run: Optional[datetime] = None
        self._last_run_duration: Optional[float] = None
        self._observations_ingested: int = 0
        self._predictions_generated: int = 0
        self._models_retrained: bool = False
        self._stations_processed: int = 0
        self._stations_failed: int = 0
        self._last_error: Optional[str] = None
        self._backoff_until: Optional[datetime] = None
        self._recent_cycles: List[AutomationCycleSummary] = []
        self._max_history = 10

        # Fair rotation tracking
        self._station_rotation_offset = 0

    @property
    def status(self) -> str:
        if not self._enabled:
            return "DISABLED"
        if self._paused:
            return "PAUSED"
        if self.is_in_backoff():
            return "BACKOFF"
        return self._status

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_running(self) -> bool:
        return self._lock.locked()

    def is_in_backoff(self) -> bool:
        if self._backoff_until is not None:
            now_utc = datetime.now(timezone.utc)
            if now_utc < self._backoff_until:
                return True
            # Backoff expired
            self._backoff_until = None
        return False

    def get_status(self, db: Optional[Session] = None) -> AutomationStatusResponse:
        """Generates comprehensive operational status response."""
        active_count = 0
        should_close = False
        if db is None:
            db = SessionLocal()
            should_close = True

        try:
            active_count = (
                db.query(Location)
                .filter(
                    Location.external_provider == "OPENAQ",
                    Location.is_active == True,
                )
                .count()
            )
        except Exception as e:
            logger.debug("Failed to count active stations: %s", e)
        finally:
            if should_close:
                db.close()

        return AutomationStatusResponse(
            status=self.status,
            enabled=self._enabled,
            paused=self._paused,
            last_run=self._last_run,
            next_run=self._next_run,
            last_run_duration_seconds=self._last_run_duration,
            observations_ingested=self._observations_ingested,
            predictions_generated=self._predictions_generated,
            models_retrained=self._models_retrained,
            stations_processed=self._stations_processed,
            stations_failed=self._stations_failed,
            active_stations_count=active_count,
            last_error=self._last_error,
            backoff_until=self._backoff_until,
            poll_interval_minutes=settings.SCHEDULER_INTERVAL_MINUTES,
            recent_cycles=list(self._recent_cycles),
        )

    def pause(self) -> None:
        """Pauses scheduled background sync cycles."""
        self._paused = True
        logger.info("Automation supervisor paused by administrator.")

    def resume(self) -> None:
        """Resumes scheduled background sync cycles."""
        self._paused = False
        logger.info("Automation supervisor resumed by administrator.")

    def compute_next_run(self) -> datetime:
        """
        Computes the next target synchronization timestamp based on
        settings.SCHEDULER_INTERVAL_MINUTES and settings.SCHEDULER_POLL_MINUTE.
        """
        now = datetime.now(timezone.utc)
        target_minute = settings.SCHEDULER_POLL_MINUTE

        # Candidate time in the current hour
        candidate = now.replace(minute=target_minute, second=0, microsecond=0)
        # If candidate is in the past (or less than 15s in the future), advance by interval
        if candidate <= now + timedelta(seconds=15):
            candidate += timedelta(minutes=settings.SCHEDULER_INTERVAL_MINUTES)

        return candidate

    async def start(self) -> None:
        """Starts the background supervisor task if enabled."""
        if not self._enabled:
            self._status = "DISABLED"
            logger.info("Automation supervisor is disabled by configuration.")
            return

        self._shutdown_event.clear()
        self._status = "IDLE"
        self._next_run = self.compute_next_run()
        self._task = asyncio.create_task(self._run_loop(), name="aeropulse-automation-loop")
        logger.info(
            "Automation supervisor started. Next scheduled sync at %s (interval: %dm, minute: :%02d).",
            self._next_run.isoformat(),
            settings.SCHEDULER_INTERVAL_MINUTES,
            settings.SCHEDULER_POLL_MINUTE,
        )

    async def stop(self) -> None:
        """Gracefully halts the background supervisor task."""
        logger.info("Stopping automation supervisor...")
        self._shutdown_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._status = "IDLE"
        logger.info("Automation supervisor stopped cleanly.")

    async def _run_loop(self) -> None:
        """Internal asynchronous worker loop executing periodic synchronization."""
        while not self._shutdown_event.is_set():
            now_utc = datetime.now(timezone.utc)
            if not self._next_run or now_utc >= self._next_run:
                self._next_run = self.compute_next_run()

            sleep_duration = max(1.0, (self._next_run - now_utc).total_seconds())

            try:
                # Wait until next run or until shutdown signal
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_duration)
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Scheduled time arrived
                if self._enabled and not self._paused:
                    if self.is_in_backoff():
                        logger.warning(
                            "Skipping scheduled sync cycle: OpenAQ rate-limit backoff active until %s.",
                            self._backoff_until.isoformat() if self._backoff_until else "unknown",
                        )
                    else:
                        logger.info("Executing scheduled continuous monitoring cycle...")
                        try:
                            await self.run_sync_cycle(source="scheduled")
                        except Exception as e:
                            logger.error("Unhandled error in scheduled automation cycle: %s", e, exc_info=True)
                self._next_run = self.compute_next_run()

    async def run_sync_cycle(self, source: str = "manual") -> AutomationCycleSummary:
        """
        Executes a single end-to-end synchronization cycle with concurrency protection.
        Offloads blocking database and network operations to a background thread.
        """
        if self._lock.locked():
            logger.warning("Automation cycle skipped: another cycle is already running.")
            raise BlockingIOError("Automation job is already in progress.")

        async with self._lock:
            cycle_id = f"cycle_{int(time.time())}_{uuid.uuid4().hex[:6]}"
            start_dt = datetime.now(timezone.utc)
            start_perf = time.time()
            self._status = "RUNNING"

            logger.info("Starting automation cycle %s (source: %s)...", cycle_id, source)

            summary = AutomationCycleSummary(
                cycle_id=cycle_id,
                started_at=start_dt,
            )

            try:
                # Offload heavy synchronous DB, OpenAQ, ML and Alert work to worker thread
                worker_result = await asyncio.to_thread(self._sync_worker)

                duration = round(time.time() - start_perf, 2)
                summary.completed_at = datetime.now(timezone.utc)
                summary.duration_seconds = duration
                summary.stations_processed = worker_result["stations_processed"]
                summary.stations_failed = worker_result["stations_failed"]
                summary.observations_ingested = worker_result["observations_ingested"]
                summary.predictions_generated = worker_result["predictions_generated"]
                summary.models_retrained = worker_result["models_retrained"]
                summary.errors = worker_result["errors"]

                if worker_result.get("backoff_seconds"):
                    self._backoff_until = datetime.now(timezone.utc) + timedelta(
                        seconds=worker_result["backoff_seconds"]
                    )
                    summary.status = "backoff"
                elif summary.stations_failed > 0 and summary.stations_processed > summary.stations_failed:
                    summary.status = "partial_success"
                elif summary.stations_failed > 0 and summary.stations_processed == summary.stations_failed:
                    summary.status = "error"
                else:
                    summary.status = "success"

                # Update supervisor operational state
                self._last_run = summary.completed_at
                self._last_run_duration = duration
                self._observations_ingested = summary.observations_ingested
                self._predictions_generated = summary.predictions_generated
                self._models_retrained = summary.models_retrained
                self._stations_processed = summary.stations_processed
                self._stations_failed = summary.stations_failed
                self._last_error = summary.errors[0] if summary.errors else None

                # Record in rolling history
                self._recent_cycles.insert(0, summary)
                if len(self._recent_cycles) > self._max_history:
                    self._recent_cycles.pop()

                logger.info(
                    "Completed automation cycle %s: status=%s, stations=%d, obs=%d, preds=%d, retrained=%s in %.2fs",
                    cycle_id,
                    summary.status,
                    summary.stations_processed,
                    summary.observations_ingested,
                    summary.predictions_generated,
                    summary.models_retrained,
                    duration,
                )
                return summary

            except Exception as e:
                duration = round(time.time() - start_perf, 2)
                logger.error("Automation cycle %s failed with exception: %s", cycle_id, e, exc_info=True)
                summary.completed_at = datetime.now(timezone.utc)
                summary.duration_seconds = duration
                summary.status = "error"
                summary.errors.append(str(e))
                self._last_error = str(e)
                self._recent_cycles.insert(0, summary)
                if len(self._recent_cycles) > self._max_history:
                    self._recent_cycles.pop()
                return summary

            finally:
                if self._paused:
                    self._status = "PAUSED"
                elif self.is_in_backoff():
                    self._status = "BACKOFF"
                else:
                    self._status = "IDLE"

    def _sync_worker(self) -> Dict[str, Any]:
        """
        Synchronous worker executed in a thread pool.
        Iterates over active OpenAQ locations, performs incremental ingestion,
        and triggers the post-ingestion intelligence cascade.
        """
        db = SessionLocal()
        try:
            # 1. Query registered active OpenAQ stations strictly
            active_locations = (
                db.query(Location)
                .filter(
                    Location.external_provider == "OPENAQ",
                    Location.is_active == True,
                )
                .order_by(Location.id.asc())
                .all()
            )

            if not active_locations:
                logger.info("No active OpenAQ stations registered. Sync cycle complete.")
                return {
                    "stations_processed": 0,
                    "stations_failed": 0,
                    "observations_ingested": 0,
                    "predictions_generated": 0,
                    "models_retrained": False,
                    "errors": [],
                    "backoff_seconds": None,
                }

            # 2. Maximum stations per run and fair rotation
            max_stations = settings.SCHEDULER_MAX_STATIONS_PER_RUN
            total_active = len(active_locations)

            if total_active > max_stations:
                offset = self._station_rotation_offset % total_active
                rotated = active_locations[offset:] + active_locations[:offset]
                target_locations = rotated[:max_stations]
                self._station_rotation_offset = (offset + max_stations) % total_active
                logger.info(
                    "Active stations (%d) exceed max per run (%d). Processing rotated slice of %d stations.",
                    total_active,
                    max_stations,
                    len(target_locations),
                )
            else:
                target_locations = active_locations

            total_obs = 0
            total_preds = 0
            any_retrained = False
            stations_processed = 0
            stations_failed = 0
            errors: List[str] = []
            backoff_sec: Optional[int] = None

            ingest_service = OpenAQIngestionService(db=db)

            # 3. Process each station independently with failure isolation
            for loc in target_locations:
                if not loc.external_id:
                    continue

                try:
                    ext_id_int = int(loc.external_id)
                except ValueError:
                    logger.warning("Location %s has invalid non-integer external_id: %s", loc.id, loc.external_id)
                    continue

                stations_processed += 1
                try:
                    # Ingest incremental data (existing service automatically handles 30m freshness & incremental window)
                    ingest_req = OpenAQIngestRequest(
                        location_ids=[ext_id_int],
                        history_days=1,
                        max_locations=1,
                    )
                    ingest_res = ingest_service.ingest(ingest_req)

                    if hasattr(ingest_res, "observations_inserted"):
                        obs_cnt = ingest_res.observations_inserted
                        preds_cnt = getattr(ingest_res, "predictions_generated", 0)
                        retrained = getattr(ingest_res, "models_retrained", False)
                        res_errors = getattr(ingest_res, "errors", [])
                    elif isinstance(ingest_res, dict):
                        obs_cnt = ingest_res.get("observations_inserted", ingest_res.get("records_inserted", 0))
                        preds_cnt = ingest_res.get("predictions_generated", ingest_res.get("predictions_count", 0))
                        retrained = ingest_res.get("models_retrained", False)
                        res_errors = ingest_res.get("errors", [])
                    else:
                        obs_cnt, preds_cnt, retrained, res_errors = 0, 0, False, []

                    total_obs += obs_cnt
                    total_preds += preds_cnt
                    if retrained:
                        any_retrained = True

                    if res_errors:
                        errors.extend(res_errors)

                except OpenAQRatelimitError as rate_err:
                    stations_failed += 1
                    backoff_sec = rate_err.retry_after or 900  # Default 15m backoff if not specified
                    err_msg = f"Rate limit hit on station {loc.name} ({loc.external_id}): {rate_err}. Backing off for {backoff_sec}s."
                    logger.warning(err_msg)
                    errors.append(err_msg)
                    break  # Cease querying upstream immediately

                except Exception as st_err:
                    stations_failed += 1
                    err_msg = f"Failed to sync station {loc.name} (ID: {loc.id}): {st_err}"
                    logger.warning(err_msg, exc_info=True)
                    errors.append(err_msg)
                    # Failure isolated; continue to next station

            return {
                "stations_processed": stations_processed,
                "stations_failed": stations_failed,
                "observations_ingested": total_obs,
                "predictions_generated": total_preds,
                "models_retrained": any_retrained,
                "errors": errors,
                "backoff_seconds": backoff_sec,
            }

        finally:
            db.close()


# Singleton supervisor instance
_automation_supervisor: Optional[AutomationSupervisor] = None


def get_automation_supervisor() -> AutomationSupervisor:
    """Returns the singleton instance of the AutomationSupervisor."""
    global _automation_supervisor
    if _automation_supervisor is None:
        _automation_supervisor = AutomationSupervisor()
    return _automation_supervisor
