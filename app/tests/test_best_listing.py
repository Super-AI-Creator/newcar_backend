from sqlalchemy import create_engine, text

from app.services.inventory_logic import select_best_listing
from app.services.legacy_tables import build_inventory_query


def test_best_listing_selection_prefers_active_latest():
    listings = [
        {"vin": "1", "status": "inactive", "last_seen_at": "2026-01-01"},
        {"vin": "1", "status": "active", "last_seen_at": "2026-01-02"},
        {"vin": "1", "status": "active", "last_seen_at": "2026-01-01"},
    ]
    best = select_best_listing(listings)
    assert best["status"] == "active"
    assert best["last_seen_at"] == "2026-01-02"


def _seed_inventory_schema(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE dealer_sources (id INTEGER PRIMARY KEY, website_url TEXT, vehicle_type TEXT)"))
        conn.execute(text("CREATE TABLE scrape_runs (id INTEGER PRIMARY KEY, source_id INTEGER)"))
        conn.execute(
            text(
                """
                CREATE TABLE canonical_vehicles (
                    id INTEGER PRIMARY KEY,
                    vin TEXT UNIQUE,
                    year INTEGER,
                    make TEXT,
                    model TEXT,
                    trim TEXT,
                    msrp REAL,
                    details TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE vehicle_listings (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER,
                    vin TEXT,
                    vehicle_type TEXT,
                    condition TEXT,
                    mileage INTEGER,
                    listed_price REAL,
                    msrp REAL,
                    year INTEGER,
                    make TEXT,
                    model TEXT,
                    trim TEXT,
                    listing_payload TEXT,
                    photo_urls TEXT,
                    status TEXT,
                    last_seen_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO vehicle_listings
                (id, source_id, vin, vehicle_type, condition, mileage, listed_price, msrp, year, make, model, trim, listing_payload, photo_urls, status, last_seen_at)
                VALUES
                (1, 1, 'VINNEW1', 'new', NULL, NULL, NULL, 42000, 2025, 'Honda', 'Civic', 'Sport', '{}', '[]', 'active', '2026-01-03'),
                (2, 1, 'VINUSED1', 'used', 'cpo', 32000, 24999, NULL, 2022, 'Honda', 'Accord', 'EX', '{}', '["https://example.com/car.jpg"]', 'active', '2026-01-02'),
                (3, 1, 'VINMISMATCH1', 'used', 'new', 10, 39350, 39350, 2025, 'Acura', 'ADX', 'A-Spec Package', '{}', '[]', 'active', '2026-01-04'),
                (4, 1, 'VINZEROUSED1', 'used', 'used', 0, 38995, 40995, 2026, 'Acura', 'Integra', 'A-Spec', '{}', '[]', 'active', '2026-01-05')
                """
            )
        )
        # Stale canonical row: would incorrectly win make/model if canonical were preferred over listing.
        conn.execute(
            text(
                """
                INSERT INTO canonical_vehicles (id, vin, year, make, model, trim, msrp, details)
                VALUES (1, 'VINUSED1', 2022, 'Audi', 'A4', 'Bad trim', NULL, '{}')
                """
            )
        )


def test_inventory_query_vehicle_type_filters_and_fields():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _seed_inventory_schema(engine)

    with engine.connect() as conn:
        all_rows = conn.execute(build_inventory_query(engine, {"vehicle_type": "all"})).fetchall()
        new_rows = conn.execute(build_inventory_query(engine, {"vehicle_type": "new"})).fetchall()
        used_rows = conn.execute(build_inventory_query(engine, {"vehicle_type": "used"})).fetchall()
        used_price_filtered = conn.execute(
            build_inventory_query(engine, {"vehicle_type": "used", "max_price": 20000})
        ).fetchall()
        used_condition_filtered = conn.execute(
            build_inventory_query(engine, {"vehicle_type": "used", "condition": "cpo"})
        ).fetchall()
        used_mileage_filtered = conn.execute(
            build_inventory_query(engine, {"vehicle_type": "used", "max_mileage": 20000})
        ).fetchall()
        audi_rows = conn.execute(build_inventory_query(engine, {"vehicle_type": "all", "make": "Audi"})).fetchall()

    assert len(all_rows) == 4
    assert len(new_rows) == 3
    assert len(used_rows) == 1
    assert len(used_price_filtered) == 0
    assert len(used_condition_filtered) == 1
    assert len(used_mileage_filtered) == 0
    assert all_rows[0]._mapping.get("vehicle_type") in {"new", "used"}
    assert used_rows[0]._mapping.get("listed_price") == 24999
    assert used_rows[0]._mapping.get("mileage") == 32000
    assert used_rows[0]._mapping.get("condition") == "cpo"
    assert used_rows[0]._mapping.get("photos") == '["https://example.com/car.jpg"]'

    all_types = {row._mapping.get("vin"): row._mapping.get("vehicle_type") for row in all_rows}
    assert all_types["VINMISMATCH1"] == "new"
    assert all_types["VINZEROUSED1"] == "new"

    used1 = next(r._mapping for r in all_rows if r._mapping.get("vin") == "VINUSED1")
    assert used1.get("make") == "Honda"
    assert used1.get("model") == "Accord"
    assert used1.get("trim") == "EX"

    assert {r._mapping.get("vin") for r in audi_rows} == set()
