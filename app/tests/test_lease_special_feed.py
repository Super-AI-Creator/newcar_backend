from sqlalchemy import create_engine, text

from app.services.legacy_tables import build_inventory_query, query_active_feed_new_vins


def _seed(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE dealer_sources (id INTEGER PRIMARY KEY, dealer_name TEXT)"))
        conn.execute(text("CREATE TABLE scrape_runs (id INTEGER PRIMARY KEY, source_id INTEGER)"))
        conn.execute(text("CREATE TABLE canonical_vehicles (id INTEGER PRIMARY KEY, vin TEXT UNIQUE)"))
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
                    carfax_url TEXT,
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
                (id, source_id, vin, vehicle_type, condition, mileage, listed_price, msrp, year, make, model, trim,
                 listing_payload, photo_urls, carfax_url, status, last_seen_at)
                VALUES
                (1, 1, 'OFFERVIN1', 'new', 'new', 10, 40000, 42000, 2026, 'Honda', 'Civic', 'Sport',
                 '{}', '[]', 'https://carfax.example/1', 'active', '2026-01-02'),
                (2, 2, 'FEEDVIN1', 'new', 'new', 10, 30095, NULL, 2026, 'Hyundai', 'IONIQ 5', 'SEL',
                 '{}', '[]', 'feed_csv', 'active', '2026-01-03'),
                (3, 2, 'FEEDVIN2', 'new', 'new', 10, NULL, NULL, 2026, 'Kia', 'EV6', 'Wind',
                 '{}', '[]', 'feed_csv', 'inactive', '2026-01-03'),
                (4, 1, 'SCRAPED1', 'new', 'new', 10, 35000, NULL, 2026, 'Toyota', 'Camry', 'LE',
                 '{}', '[]', 'https://carfax.example/2', 'active', '2026-01-04')
                """
            )
        )


def test_query_active_feed_new_vins_only_active_feed():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _seed(engine)
    vins = query_active_feed_new_vins(engine)
    assert vins == ["FEEDVIN1"]


def test_inventory_query_includes_feed_vin_when_vin_in_union():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _seed(engine)
    rows = engine.connect().execute(
        build_inventory_query(engine, {"vehicle_type": "new", "vin_in": ["OFFERVIN1", "FEEDVIN1", "SCRAPED1"]})
    ).fetchall()
    assert {r._mapping["vin"] for r in rows} == {"OFFERVIN1", "FEEDVIN1", "SCRAPED1"}
