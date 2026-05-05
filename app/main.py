import os
import logging
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError, ProgrammingError

from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.core.config import settings
from app.core.database import SessionLocal
from app.routes import auth, inventory, favorites, broker, credit, docs, admin, dealer, payments, recommendations, vehicles, search_compat, frontend_compat, testimonials, deals, lenders, leads, webhooks, seo, credit_unions, landing, articles, cu_demo_contact
from app.models.user import User
from app.schemas.user import UserOut
from app.services.user_out import build_user_out
from app.services.sheets_scheduler import SheetsSyncScheduler

app = FastAPI(title="NewCarSuperstore App Backend")
_sheets_scheduler = SheetsSyncScheduler()
_uploads_dir = Path(__file__).resolve().parents[1] / "uploads"
logger = logging.getLogger(__name__)

_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
    "https://newcar-frontend.vercel.app",
    "http://newcar-frontend.vercel.app",
    "https://newcarsuperstore.com",
    "http://newcarsuperstore.com",
    "http://power-auto-buying-nextjs.vercel.app",
    "https://power-auto-buying-nextjs.vercel.app",
    "https://www.carscu.com",
    "http://www.carscu.com",
    "https://carscu.com",
    "http://carscu.com"
]
_extra = os.getenv("CORS_ORIGINS", "").strip()
if _extra:
    _cors_origins = [*_cors_origins, *(o.strip() for o in _extra.split(",") if o.strip())]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir), check_dir=False), name="uploads")


def _looks_like_missing_schema(exc: BaseException) -> bool:
    """True when ORM expects columns/tables that are not in the database (migrations not applied)."""
    raw = str(getattr(exc, "orig", exc) or exc).lower()
    return (
        "unknown column" in raw
        or "no such column" in raw
        or ("column" in raw and "does not exist" in raw)
        or "doesn't exist" in raw
    )


@app.exception_handler(OperationalError)
async def handle_db_operational_error(_, exc: OperationalError):
    logger.error("Database operational error", exc_info=exc)
    code = None
    original = getattr(exc, "orig", None)
    if hasattr(original, "args") and original.args:
        code = original.args[0]

    if code in {1040, 1203, 2013}:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is temporarily busy. Please retry in a few seconds."},
        )

    if _looks_like_missing_schema(exc):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Database schema is out of date for this API version.",
                "hint": "In manage_backend, run: alembic upgrade head",
            },
        )

    return JSONResponse(status_code=500, content={"detail": "Database operation failed."})


@app.exception_handler(ProgrammingError)
async def handle_db_programming_error(_, exc: ProgrammingError):
    logger.error("Database programming error", exc_info=exc)
    if _looks_like_missing_schema(exc):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Database schema is out of date for this API version.",
                "hint": "In manage_backend, run: alembic upgrade head",
            },
        )
    return JSONResponse(status_code=500, content={"detail": "Database operation failed."})


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    detail_text = str(exc.detail or "").strip().lower()
    if exc.status_code == 401 and detail_text == "not authenticated":
        headers = dict(getattr(exc, "headers", {}) or {})
        if "WWW-Authenticate" not in headers:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=401,
            content={"detail": "Login to continue"},
            headers=headers,
        )
    return await http_exception_handler(request, exc)


@app.get("/health")
def health():
    return JSONResponse(content={"status": "ok"}, status_code=200, media_type="application/json")


@app.on_event("startup")
def start_background_jobs():
    try:
        _sheets_scheduler.start()
    except Exception:
        logger.exception("Sheets scheduler startup failed; continuing without background sync.")
    if settings.inventory_startup_warmup_enabled:
        def _run_inventory_warmup():
            delay_seconds = max(0, int(settings.inventory_startup_warmup_delay_seconds))
            if delay_seconds:
                time.sleep(delay_seconds)
            db = SessionLocal()
            try:
                inventory.warm_inventory_hot_cache(db)
                logger.info("Inventory startup warmup completed.")
            except Exception:
                logger.exception("Inventory startup warmup failed; continuing without warm cache.")
            finally:
                db.close()

        threading.Thread(
            target=_run_inventory_warmup,
            name="inventory-startup-warmup",
            daemon=True,
        ).start()


@app.on_event("shutdown")
def stop_background_jobs():
    try:
        _sheets_scheduler.stop()
    except Exception:
        logger.exception("Sheets scheduler shutdown failed.")


@app.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return build_user_out(db, user)


app.include_router(auth.router)
app.include_router(inventory.router)
app.include_router(favorites.router)
app.include_router(broker.router)
app.include_router(credit.router)
app.include_router(docs.router)
app.include_router(admin.router)
app.include_router(dealer.router)
app.include_router(payments.router)
app.include_router(recommendations.router)
app.include_router(vehicles.router)
app.include_router(search_compat.router)
app.include_router(frontend_compat.router)
app.include_router(testimonials.router)
app.include_router(deals.router)
app.include_router(lenders.router)
app.include_router(leads.router)
app.include_router(webhooks.router)
app.include_router(seo.router)
app.include_router(credit_unions.router)
app.include_router(landing.router)
app.include_router(articles.router)
app.include_router(cu_demo_contact.router)
