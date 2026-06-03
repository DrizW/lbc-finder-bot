import os
import sqlite3
from contextlib import closing


def get_db_path() -> str:
    data_dir = os.getenv("LBC_DATA_DIR", os.path.join(os.getcwd(), "data"))
    return os.getenv("LBC_DB_PATH", os.path.join(data_dir, "listings.sqlite3"))


def connect() -> sqlite3.Connection:
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                price REAL,
                location TEXT,
                category TEXT,
                url TEXT,
                image_urls TEXT,
                published_at TEXT,
                first_seen_at TEXT,
                detected_product_type TEXT,
                detected_brand TEXT,
                detected_model TEXT,
                detected_condition TEXT,
                detected_accessories TEXT,
                missing_accessories TEXT,
                risk_flags TEXT,
                identification_confidence REAL,
                market_avg_price REAL,
                market_median_price REAL,
                comparable_count INTEGER,
                resale_price_low REAL,
                resale_price_realistic REAL,
                resale_price_high REAL,
                estimated_margin_low REAL,
                estimated_margin_realistic REAL,
                estimated_margin_high REAL,
                heat_score INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(platform, external_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_listings_comparable
            ON listings(detected_product_type, detected_brand, detected_model, detected_condition)
            """
        )
        conn.commit()
