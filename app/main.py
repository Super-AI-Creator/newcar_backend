import os
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from app.core.deps import get_current_user
from app.routes import auth, inventory, favorites, broker, credit, docs, admin, dealer, payments, recommendations, vehicles, search_compat, frontend_compat, testimonials, deals, lenders, leads, webhooks, seo
from app.schemas.user import UserOut
from app.services.sheets_scheduler import SheetsSyncScheduler

app = FastAPI(title="NewCarSuperstore App Backend")
_sheets_scheduler = SheetsSyncScheduler()
_uploads_dir = Path(__file__).resolve().parents[1] / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)

_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://newcar-frontend.vercel.app",
    "http://newcar-frontend.vercel.app",
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
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


@app.exception_handler(OperationalError)
async def handle_db_operational_error(_, exc: OperationalError):
    code = None
    original = getattr(exc, "orig", None)
    if hasattr(original, "args") and original.args:
        code = original.args[0]

    if code in {1040, 1203, 2013}:
        return JSONResponse(
            status_code=503,
            content={"detail": "Database is temporarily busy. Please retry in a few seconds."},
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
    return {"status": "ok"}


@app.on_event("startup")
def start_background_jobs():
    _sheets_scheduler.start()


@app.on_event("shutdown")
def stop_background_jobs():
    _sheets_scheduler.stop()


@app.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    return user


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
