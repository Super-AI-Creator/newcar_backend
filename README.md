# NewCarSuperstore App Backend

FastAPI backend that serves inventory and member features from MySQL.

## Requirements
- Python 3.9
- MySQL 8

**MySQL driver:** The app uses `pymysql` by default (works on Windows without a C compiler). If you prefer `mysqlclient`, install it and it will be used when available.

## Setup
1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and fill values.

4. Initialize the database and run migrations:

```bash
python scripts/init_db.py
```

5. Run the server:

```bash
uvicorn app.main:app --reload
```

## Environment Variables
See `.env.example` for the full list.

Key values:
- `MYSQL_*`: database connection
- `JWT_SECRET`: signing key for access tokens
- `GOOGLE_CLIENT_ID`: Google OAuth client ID for ID token verification
- `GOOGLE_SERVICE_ACCOUNT_JSON`: path to service account JSON for Sheets sync
- `SMTP_*`: SMTP credentials
- `EMAIL_PROVIDER`: `auto` (default), `smtp`, or `resend`
- `RESEND_API_KEY`: API key for Resend (used when `EMAIL_PROVIDER=resend` or `auto` with key present)
- `RESEND_FROM_EMAIL`: optional sender override for Resend
- `BROKER_EMAIL`: destination for broker emails
- `OFFERS_SHEET_*` / `SCORES_SHEET_*`: Google Sheets IDs + tab names
- `CORS_ORIGINS`: optional comma-separated list of frontend origins (e.g. `https://newcarsuperstore.com`) for production

## API Endpoints (summary)
- `GET /health`
- `GET /me`
- `POST /auth/google`
- `POST /auth/register/request-otp`
- `POST /auth/register/verify-otp`
- `POST /auth/login`
- `GET /inventory/search`
- `GET /inventory/{vin}`
- `POST /favorites/{vin}`
- `DELETE /favorites/{vin}`
- `GET /favorites`
- `POST /broker/message`
- `POST /credit/apply`
- `POST /docs/forward`
- `GET /payments/estimate`
- `GET /recommendations/best`
- `GET /testimonials`
- `GET /admin/sources`
- `POST /admin/sync-sheets`
- `PUT /dealer/offers/{vin}`

## Google Sheets Sync
- API: `POST /admin/sync-sheets`
- CLI: `python -m app.sync --offers --scores`

## Deploy (production)
1. Set `.env` from `.env.example` with production values (strong `JWT_SECRET`, production MySQL, SMTP/Resend, `CORS_ORIGINS` with your frontend origin).
2. Create DB and run migrations:
   ```bash
   python scripts/init_db.py
   ```
3. Seed testimonials (optional, so `/testimonials` is not empty):
   ```bash
   python -m scripts.seed_testimonials
   ```
4. Run with a production ASGI server, e.g.:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Or use Gunicorn: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000`.

## Notes
- This app never scrapes. It only **reads** from the scraping backend tables: `dealer_sources`, `scrape_runs`, `canonical_vehicles`, `vehicle_listings`. The scraping backend populates these; see **Scraping schema** below.
- Offer visibility: Down / monthly / discounted from `offer_overrides` (or spreadsheet) are only shown when non-blank.
- Recommendations use `model_scores` (design, performance, technology, practicality, future_value 1–10). Weights: `styling`→design, `fun`+`performance`→performance, `practical`→practicality, `value`→future_value, `technology`→technology.

## Scraping schema (inventory source)

Inventory and search read from the same database the **scraping backend** writes to. Table and column expectations:

- **dealer_sources** – `id`, `enabled`, `brand`, `dealer_name`, `website_url`, `vehicle_type`, `scrape_method`, `last_scrape_status`, etc. (Google Sheet row ref optional.)
- **scrape_runs** – `id`, `source_id`, `started_at`, `finished_at`, `status`, counts.
- **canonical_vehicles** – `vin` (unique), `year`, `make`, `model`, `trim`, `msrp`, `details`, optional attributes (body_style, drivetrain, engine, transmission, exterior_color, interior_color).
- **vehicle_listings** – `id`, `source_id`, `run_id`, `canonical_vehicle_id`, `vin`, `vehicle_type`, `condition`, `year`, `make`, `model`, `trim`, `msrp`, `listed_price`, `mileage`, `photo_urls` (JSON), `listing_payload` (JSON), `status`, `last_seen_at`, `url`, etc.

Full reference: **[docs/SCRAPING_SCHEMA.md](docs/SCRAPING_SCHEMA.md)**. If the scraping schema changes, update that doc and `app/services/legacy_tables.py` as needed.
