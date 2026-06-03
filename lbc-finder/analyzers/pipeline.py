from database.models import Opportunity, RawListing
from database.repositories import ListingRepository
from .condition_estimator import estimate_condition
from .heat_score import calculate_heat_score, heat_label
from .margin_estimator import estimate_margin
from .price_estimator import with_fallback_market
from .product_identifier import identify_product


def analyze_listing(
    listing: RawListing,
    niche: dict,
    repository: ListingRepository,
) -> Opportunity:
    analysis = identify_product(listing, niche)
    condition, risks = estimate_condition(
        listing.title,
        listing.description,
        niche.get("risk_keywords", []),
    )
    analysis.detected_condition = condition
    analysis.risk_flags = sorted(set(analysis.risk_flags + risks))

    market = repository.market_stats(
        analysis.detected_product_type,
        analysis.detected_brand,
        analysis.detected_model,
        analysis.detected_condition,
    )
    market = with_fallback_market(market, analysis)
    costs = niche.get("default_estimated_costs", {})
    margin = estimate_margin(
        listing,
        market,
        cleaning_cost=costs.get("cleaning", 15),
        travel_cost=costs.get("travel", 10),
        misc_cost=costs.get("misc", 10),
    )
    score, reasons = calculate_heat_score(
        listing,
        analysis,
        market,
        margin,
        liquidity_score=int(niche.get("liquidity_score", 0)),
    )
    return Opportunity(
        raw=listing,
        analysis=analysis,
        market=market,
        margin=margin,
        heat_score=score,
        heat_label=heat_label(score),
        reasons=reasons,
    )
