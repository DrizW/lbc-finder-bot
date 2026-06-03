from database.models import ListingAnalysis, MarketStats


FALLBACK_MARKET = {
    ("Cybex", "Priam"): 520,
    ("Cybex", "Balios"): 330,
    ("Cybex", "Mios"): 390,
    ("Babyzen", "Yoyo"): 310,
    ("Babyzen", "Yoyo2"): 360,
    ("Babyzen", "Yoyo 3"): 430,
    ("Bugaboo", "Fox"): 520,
    ("Bugaboo", "Dragonfly"): 560,
    ("Bugaboo", "Donkey"): 620,
    ("Stokke", "Xplory"): 390,
    ("Stokke", "Trailz"): 330,
}


def with_fallback_market(stats: MarketStats, analysis: ListingAnalysis) -> MarketStats:
    if stats.comparable_count:
        return stats
    key = (analysis.detected_brand, analysis.detected_model)
    fallback = FALLBACK_MARKET.get(key)
    if not fallback:
        return stats
    return MarketStats(
        average=fallback,
        median=fallback,
        minimum=None,
        maximum=None,
        comparable_count=0,
        used_fallback=True,
    )
