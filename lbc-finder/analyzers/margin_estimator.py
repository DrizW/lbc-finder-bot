from database.models import MarginEstimate, MarketStats, RawListing


def estimate_margin(
    listing: RawListing,
    market: MarketStats,
    cleaning_cost: float = 15,
    travel_cost: float = 10,
    misc_cost: float = 10,
) -> MarginEstimate:
    total_costs = cleaning_cost + travel_cost + misc_cost
    if listing.price is None or market.median is None:
        return MarginEstimate(total_costs=total_costs)

    resale_low = round(market.median * 0.85, 2)
    resale_realistic = round(market.median, 2)
    resale_high = round(market.median * 1.12, 2)
    return MarginEstimate(
        resale_price_low=resale_low,
        resale_price_realistic=resale_realistic,
        resale_price_high=resale_high,
        estimated_margin_low=round(resale_low - listing.price - total_costs, 2),
        estimated_margin_realistic=round(
            resale_realistic - listing.price - total_costs, 2
        ),
        estimated_margin_high=round(resale_high - listing.price - total_costs, 2),
        total_costs=total_costs,
    )
