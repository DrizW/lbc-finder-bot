from dataclasses import dataclass, field


@dataclass
class RawListing:
    platform: str
    external_id: str
    title: str
    description: str = ""
    price: float | None = None
    location: str = ""
    category: str = ""
    url: str = ""
    image_urls: list[str] = field(default_factory=list)
    published_at: str | None = None


@dataclass
class ListingAnalysis:
    detected_product_type: str | None = None
    detected_brand: str | None = None
    detected_model: str | None = None
    detected_condition: str | None = None
    detected_accessories: list[str] = field(default_factory=list)
    missing_accessories: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    identification_confidence: float = 0.0
    resale_difficulty: str = "moyenne"
    recommended_action: str = "surveiller"


@dataclass
class MarketStats:
    average: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    comparable_count: int = 0
    used_fallback: bool = False


@dataclass
class MarginEstimate:
    resale_price_low: float | None = None
    resale_price_realistic: float | None = None
    resale_price_high: float | None = None
    estimated_margin_low: float | None = None
    estimated_margin_realistic: float | None = None
    estimated_margin_high: float | None = None
    total_costs: float = 35.0


@dataclass
class Opportunity:
    raw: RawListing
    analysis: ListingAnalysis
    market: MarketStats
    margin: MarginEstimate
    heat_score: int
    heat_label: str
    reasons: list[str] = field(default_factory=list)
