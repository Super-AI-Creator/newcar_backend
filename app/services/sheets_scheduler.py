import logging
import threading
from typing import Optional

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.sheets_runner import SHEETS_SYNC_LOCK_NAME, run_sheets_sync_if_changed_with_lock


logger = logging.getLogger(__name__)


class SheetsSyncScheduler:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock_name = SHEETS_SYNC_LOCK_NAME

    def start(self) -> None:
        if not settings.sheets_auto_sync_enabled:
            logger.info("Sheets auto-sync is disabled.")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="sheets-auto-sync", daemon=True)
        self._thread.start()
        logger.info(
            "Sheets auto-sync started (interval=%s minutes, run_on_startup=%s, lock_wait=%s seconds).",
            settings.sheets_auto_sync_interval_minutes,
            settings.sheets_auto_sync_run_on_startup,
            settings.sheets_auto_sync_lock_wait_seconds,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        logger.info("Sheets auto-sync stopped.")

    def _run_loop(self) -> None:
        interval_minutes = max(1, int(settings.sheets_auto_sync_interval_minutes or 10))
        interval_seconds = interval_minutes * 60

        if settings.sheets_auto_sync_run_on_startup and not self._stop_event.is_set():
            self._run_once()

        while not self._stop_event.wait(interval_seconds):
            self._run_once()

    def _run_once(self) -> None:
        db = SessionLocal()
        try:
            result = run_sheets_sync_if_changed_with_lock(
                db,
                lock_name=self._lock_name,
                wait_seconds=max(0, int(settings.sheets_auto_sync_lock_wait_seconds or 0)),
            )
            if result.get("locked"):
                logger.info(
                    "Sheets auto-sync skipped (lock held by another worker, wait_seconds=%s).",
                    settings.sheets_auto_sync_lock_wait_seconds,
                )
                return

            offers = result.get("offers", {})
            scores = result.get("scores", {})
            offers_count = offers.get("count", 0)
            scores_count = scores.get("count", 0)
            offers_error = offers.get("error")
            scores_error = scores.get("error")
            offers_changed = bool(offers.get("changed"))
            scores_changed = bool(scores.get("changed"))

            if offers_error or scores_error:
                logger.warning(
                    "Sheets auto-sync check completed with errors (offers_count=%s, scores_count=%s, offers_error=%s, scores_error=%s).",
                    offers_count,
                    scores_count,
                    offers_error,
                    scores_error,
                )
            elif not offers_changed and not scores_changed:
                logger.info("Sheets auto-sync check: no changes detected.")
            else:
                logger.info(
                    "Sheets auto-sync completed (offers_changed=%s, offers_count=%s, scores_changed=%s, scores_count=%s).",
                    offers_changed,
                    offers_count,
                    scores_changed,
                    scores_count,
                )
        except Exception as exc:
            logger.exception("Sheets auto-sync failed: %s", exc)
        finally:
            db.close()
