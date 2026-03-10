from __future__ import annotations

from typing import Any, Callable, Dict

from sqlalchemy.orm import Session

from app.models.sheet_sources_meta import SheetSourceMeta
from app.services.sheets_sync import (
    compute_sheet_data_hash,
    resolve_offers_sheet_target,
    resolve_scores_sheet_target,
    sync_offers,
    sync_scores,
)


SHEETS_SYNC_LOCK_NAME = "management1_sheets_sync"


def _last_meta_hash(db: Session, *, sheet_name: str, sheet_id: str, tab_name: str) -> str | None:
    meta = (
        db.query(SheetSourceMeta)
        .filter(
            SheetSourceMeta.sheet_name == sheet_name,
            SheetSourceMeta.sheet_id == sheet_id,
            SheetSourceMeta.tab_name == tab_name,
        )
        .order_by(SheetSourceMeta.id.desc())
        .first()
    )
    return meta.last_row_hash if meta else None


def run_sheets_sync(db: Session) -> Dict[str, Any]:
    offers_count = 0
    offers_hash = None
    offers_error = None
    try:
        offers_count, offers_hash = sync_offers(db)
    except Exception as exc:
        db.rollback()
        offers_error = str(exc)

    scores_count = 0
    scores_hash = None
    scores_error = None
    try:
        scores_count, scores_hash = sync_scores(db)
    except Exception as exc:
        db.rollback()
        scores_error = str(exc)

    ok = (offers_error is None) and (scores_error is None)
    return {
        "ok": ok,
        "checked_only": False,
        "offers": {"count": offers_count, "hash": offers_hash, "error": offers_error},
        "scores": {"count": scores_count, "hash": scores_hash, "error": scores_error},
    }


def _sync_one_if_changed(
    db: Session,
    *,
    name: str,
    resolve_target: Callable[[], tuple[str, str]],
    sync_fn: Callable[[Session], tuple[int, str]],
) -> Dict[str, Any]:
    try:
        sheet_id, tab_name = resolve_target()
    except Exception as exc:
        return {
            "count": 0,
            "hash": None,
            "error": str(exc),
            "changed": False,
            "skipped": False,
        }

    try:
        current_hash = compute_sheet_data_hash(sheet_id, tab_name)
    except Exception as exc:
        return {
            "count": 0,
            "hash": None,
            "error": str(exc),
            "changed": False,
            "skipped": False,
            "sheet_id": sheet_id,
            "tab_name": tab_name,
        }

    previous_hash = _last_meta_hash(db, sheet_name=name, sheet_id=sheet_id, tab_name=tab_name)
    changed = previous_hash is None or current_hash != previous_hash
    if not changed:
        return {
            "count": 0,
            "hash": current_hash,
            "error": None,
            "changed": False,
            "skipped": True,
            "sheet_id": sheet_id,
            "tab_name": tab_name,
        }

    try:
        count, row_hash = sync_fn(db)
        return {
            "count": count,
            "hash": row_hash,
            "error": None,
            "changed": True,
            "skipped": False,
            "sheet_id": sheet_id,
            "tab_name": tab_name,
        }
    except Exception as exc:
        db.rollback()
        return {
            "count": 0,
            "hash": current_hash,
            "error": str(exc),
            "changed": True,
            "skipped": False,
            "sheet_id": sheet_id,
            "tab_name": tab_name,
        }


def run_sheets_sync_if_changed(db: Session) -> Dict[str, Any]:
    offers = _sync_one_if_changed(
        db,
        name="offers",
        resolve_target=resolve_offers_sheet_target,
        sync_fn=sync_offers,
    )
    scores = _sync_one_if_changed(
        db,
        name="scores",
        resolve_target=resolve_scores_sheet_target,
        sync_fn=sync_scores,
    )
    ok = (offers.get("error") is None) and (scores.get("error") is None)
    return {
        "ok": ok,
        "checked_only": True,
        "offers": offers,
        "scores": scores,
    }


def _run_with_lock(
    db: Session,
    *,
    run_fn: Callable[[Session], Dict[str, Any]],
    lock_name: str = SHEETS_SYNC_LOCK_NAME,
    wait_seconds: int = 0,
) -> Dict[str, Any]:
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)
    lock_conn = engine.raw_connection()
    lock_acquired = False
    try:
        with lock_conn.cursor() as cursor:
            cursor.execute("SELECT GET_LOCK(%s, %s)", (lock_name, max(0, int(wait_seconds or 0))))
            row = cursor.fetchone()
        lock_result = row[0] if row else None
        lock_acquired = str(lock_result) == "1"
        if not lock_acquired:
            return {
                "ok": False,
                "locked": True,
                "detail": "A sheets sync is already running.",
                "checked_only": False,
                "offers": {"count": 0, "hash": None, "error": None},
                "scores": {"count": 0, "hash": None, "error": None},
            }

        result = run_fn(db)
        result["locked"] = False
        return result
    finally:
        try:
            if lock_acquired:
                with lock_conn.cursor() as cursor:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
        finally:
            lock_conn.close()


def run_sheets_sync_with_lock(
    db: Session,
    *,
    lock_name: str = SHEETS_SYNC_LOCK_NAME,
    wait_seconds: int = 0,
) -> Dict[str, Any]:
    return _run_with_lock(
        db,
        run_fn=run_sheets_sync,
        lock_name=lock_name,
        wait_seconds=wait_seconds,
    )


def run_sheets_sync_if_changed_with_lock(
    db: Session,
    *,
    lock_name: str = SHEETS_SYNC_LOCK_NAME,
    wait_seconds: int = 0,
) -> Dict[str, Any]:
    return _run_with_lock(
        db,
        run_fn=run_sheets_sync_if_changed,
        lock_name=lock_name,
        wait_seconds=wait_seconds,
    )
