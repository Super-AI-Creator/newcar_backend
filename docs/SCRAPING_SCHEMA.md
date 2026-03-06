# Scraping Backend Data Schema

This document describes the database schema produced by the **scraping backend**. The marketplace backend (this app) **reads** from these tables; it does not create or alter them. The scraper is responsible for populating `dealer_sources`, `scrape_runs`, `canonical_vehicles`, and `vehicle_listings`.

---

## Enums

| Enum | Values |
|------|--------|
| `ScrapeMethod` | `static`, `playwright`, `api` |
| `VehicleType` | `new`, `used` |
| `VehicleCondition` | `new`, `used`, `cpo` |
| `ScrapeStatus` | `never`, `running`, `success`, `partial`, `failed` |
| `RunStatus` | `running`, `success`, `partial`, `failed` |
| `ListingStatus` | `active`, `inactive`, `sold`, `unknown` |
| `JobStatus` | `queued`, `running`, `success`, `failed` |

---

## Tables

### `dealer_sources`

Dealer websites to scrape. Links to a Google Sheet row for URL management (URLs can change monthly).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger (PK) | |
| `enabled` | Integer | 1 = enabled |
| `brand` | String(64) | e.g. Toyota, Honda |
| `dealer_name` | String(128) | |
| `website_url` | String(512) | Unique per (website_url, vehicle_type) |
| `vehicle_type` | Enum(VehicleType) | `new` / `used` |
| `inventory_url` | String(512) | nullable |
| `scrape_method` | Enum(ScrapeMethod) | static / playwright / api |
| `scrape_recipe` | JSON | nullable |
| `sheet_row_id` | String(64) | nullable, Google Sheet reference |
| `sheet_row_hash` | CHAR(64) | nullable |
| `last_scrape_status` | Enum(ScrapeStatus) | |
| `last_scrape_started_at` | DateTime | nullable |
| `last_scrape_finished_at` | DateTime | nullable |
| `last_success_at` | DateTime | nullable |
| `fail_count` | Integer | default 0 |
| `last_error` | Text | nullable |
| `created_at`, `updated_at` | DateTime | |

**Indexes:** `(website_url, vehicle_type)` unique, `(brand, enabled)`, `(last_scrape_status)`.

---

### `scrape_runs`

One row per scrape run for a given source.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger (PK) | |
| `source_id` | FK → dealer_sources.id | CASCADE delete |
| `started_at` | DateTime | |
| `finished_at` | DateTime | nullable |
| `status` | Enum(RunStatus) | |
| `vehicles_discovered` | Integer | default 0 |
| `vehicles_parsed` | Integer | default 0 |
| `vehicles_upserted` | Integer | default 0 |
| `discovered_new` / `discovered_used` | Integer | default 0 |
| `upserted_new` / `upserted_used` | Integer | default 0 |
| `pages_fetched` | Integer | default 0 |
| `error_summary` | Text | nullable |
| `created_at` | DateTime | |

---

### `canonical_vehicles`

One row per VIN: normalized vehicle data (shared across listings).

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger (PK) | |
| `vin` | CHAR(17) | **Unique** |
| `year` | SmallInteger | nullable |
| `make` | String(64) | nullable |
| `model` | String(64) | nullable |
| `trim` | String(128) | nullable |
| `msrp` | DECIMAL(12,2) | nullable |
| `details` | Text | nullable, JSON or text |
| `body_style` | String(64) | nullable |
| `drivetrain` | String(64) | nullable |
| `engine` | String(128) | nullable |
| `transmission` | String(128) | nullable |
| `exterior_color` | String(64) | nullable |
| `interior_color` | String(64) | nullable |
| `created_at`, `updated_at` | DateTime | |

**Indexes:** unique on `vin`, index on `(make, model, year)`.

---

### `vehicle_listings`

One row per listing (per dealer, per vehicle). Joins to `canonical_vehicles` by `vin`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BigInteger (PK) | |
| `source_id` | FK → dealer_sources.id | CASCADE delete |
| `run_id` | FK → scrape_runs.id | SET NULL on delete |
| `canonical_vehicle_id` | FK → canonical_vehicles.id | SET NULL on delete |
| `source_vehicle_key` | String(128) | nullable |
| `url` | String(768) | listing URL |
| `vehicle_type` | Enum(VehicleType) | `new` / `used` |
| `condition` | Enum(VehicleCondition) | new / used / cpo |
| `mileage` | Integer | nullable |
| `stock_number` | String(64) | nullable |
| `listed_price` | DECIMAL(12,2) | nullable |
| `vin` | CHAR(17) | nullable |
| `year` | SmallInteger | nullable |
| `make` | String(64) | nullable |
| `model` | String(64) | nullable |
| `trim` | String(128) | nullable |
| `msrp` | DECIMAL(12,2) | nullable |
| `first_registration_date` | Date | nullable |
| `carfax_url` | String(768) | nullable |
| `accident_count` | Integer | nullable |
| `seller_notes` | Text | nullable |
| `photo_urls` | JSON | nullable, array of URLs (1–5) |
| `listing_payload` | JSON | nullable, raw payload |
| `raw_snapshot_hash` | CHAR(64) | nullable |
| `status` | Enum(ListingStatus) | active / inactive / sold / unknown |
| `first_seen_at` | DateTime | |
| `last_seen_at` | DateTime | |
| `updated_at` | DateTime | |

**Unique:** `(source_id, source_vehicle_key)`, `(source_id, stock_number, vehicle_type)`. **Indexes:** `vin`, `(vin, vehicle_type)`, `(vehicle_type, make, model, year)`, `(vehicle_type, listed_price)`, `(vehicle_type, mileage)`, `(status, last_seen_at)`.

---

### `jobs`

Task queue for the scraping backend (not used by the marketplace API).

| Column | Type |
|--------|------|
| `id` | BigInteger (PK) |
| `task_name` | String(64) |
| `payload` | JSON nullable |
| `status` | Enum(JobStatus) |
| `started_at`, `finished_at` | DateTime nullable |
| `error` | Text nullable |
| `created_at` | DateTime |

---

## Marketplace overlay (this app)

The marketplace adds its own tables in the **same** database:

- **`offer_overrides`** – Down payment, monthly payment, discounted price (and visibility flags) per VIN. Source: spreadsheet sync or dealer dashboard. Only shown when non-blank.
- **`model_scores`** – Per make/model/trim/year: design, performance, technology, practicality, future_value (1–10). Source: spreadsheet. Used for “best car” ranking.
- **Users, favorites, broker, credit, etc.** – As in the main app models.

Inventory API reads from `vehicle_listings` + `canonical_vehicles`, left-joins `dealer_sources` for `dealer_name`, and merges in `offer_overrides` and `model_scores` for display and ranking. Responses include `listing_url` and `carfax_url` from `vehicle_listings` when present.
