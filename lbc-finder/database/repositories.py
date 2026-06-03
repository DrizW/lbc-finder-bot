import json
from contextlib import closing
from datetime import datetime, timezone
from statistics import mean, median

from .db import connect, init_db
from .models import ListingAnalysis, MarginEstimate, MarketStats, RawListing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ListingRepository:
    def __init__(self):
        init_db()

    def upsert_raw(self, listing: RawListing) -> None:
        now = _now()
        with closing(connect()) as conn:
            conn.execute(
                """
                INSERT INTO listings (
                    platform, external_id, title, description, price, location,
                    category, url, image_urls, published_at, first_seen_at,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, external_id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    price=excluded.price,
                    location=excluded.location,
                    category=excluded.category,
                    url=excluded.url,
                    image_urls=excluded.image_urls,
                    published_at=excluded.published_at,
                    updated_at=excluded.updated_at
                """,
                (
                    listing.platform,
                    listing.external_id,
                    listing.title,
                    listing.description,
                    listing.price,
                    listing.location,
                    listing.category,
                    listing.url,
                    json.dumps(listing.image_urls, ensure_ascii=False),
                    listing.published_at,
                    now,
                    "detected",
                    now,
                    now,
                ),
            )
            conn.commit()

    def update_analysis(
        self,
        listing: RawListing,
        analysis: ListingAnalysis,
        market: MarketStats,
        margin: MarginEstimate,
        heat_score: int,
        status: str,
    ) -> None:
        with closing(connect()) as conn:
            conn.execute(
                """
                UPDATE listings SET
                    detected_product_type=?,
                    detected_brand=?,
                    detected_model=?,
                    detected_condition=?,
                    detected_accessories=?,
                    missing_accessories=?,
                    risk_flags=?,
                    identification_confidence=?,
                    market_avg_price=?,
                    market_median_price=?,
                    comparable_count=?,
                    resale_price_low=?,
                    resale_price_realistic=?,
                    resale_price_high=?,
                    estimated_margin_low=?,
                    estimated_margin_realistic=?,
                    estimated_margin_high=?,
                    heat_score=?,
                    status=?,
                    updated_at=?
                WHERE platform=? AND external_id=?
                """,
                (
                    analysis.detected_product_type,
                    analysis.detected_brand,
                    analysis.detected_model,
                    analysis.detected_condition,
                    json.dumps(analysis.detected_accessories, ensure_ascii=False),
                    json.dumps(analysis.missing_accessories, ensure_ascii=False),
                    json.dumps(analysis.risk_flags, ensure_ascii=False),
                    analysis.identification_confidence,
                    market.average,
                    market.median,
                    market.comparable_count,
                    margin.resale_price_low,
                    margin.resale_price_realistic,
                    margin.resale_price_high,
                    margin.estimated_margin_low,
                    margin.estimated_margin_realistic,
                    margin.estimated_margin_high,
                    heat_score,
                    status,
                    _now(),
                    listing.platform,
                    listing.external_id,
                ),
            )
            conn.commit()

    def market_stats(
        self,
        product_type: str | None,
        brand: str | None,
        model: str | None,
        condition: str | None = None,
    ) -> MarketStats:
        if not product_type or not brand or not model:
            return MarketStats()

        query = """
            SELECT price FROM listings
            WHERE detected_product_type = ?
              AND detected_brand = ?
              AND detected_model = ?
              AND price IS NOT NULL
        """
        params: list[object] = [product_type, brand, model]
        if condition:
            query += " AND detected_condition = ?"
            params.append(condition)

        with closing(connect()) as conn:
            prices = [row["price"] for row in conn.execute(query, params).fetchall()]

        if len(prices) < 3 and condition:
            return self.market_stats(product_type, brand, model, None)
        if not prices:
            return MarketStats()

        return MarketStats(
            average=round(mean(prices), 2),
            median=round(median(prices), 2),
            minimum=min(prices),
            maximum=max(prices),
            comparable_count=len(prices),
        )
