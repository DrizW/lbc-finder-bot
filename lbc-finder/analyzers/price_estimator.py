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
    ("Dyson", "V8"): 180,
    ("Dyson", "V10"): 260,
    ("Dyson", "V11"): 330,
    ("Dyson", "V12"): 420,
    ("Dyson", "V15"): 520,
    ("Sony", "PS5"): 430,
    ("Sony", "Playstation 5"): 430,
    ("Nintendo", "Switch"): 210,
    ("Nintendo", "Switch OLED"): 280,
    ("Microsoft", "Xbox Series X"): 330,
    ("Apple", "iPhone 13"): 380,
    ("Apple", "iPhone 14"): 520,
    ("Apple", "iPhone 15"): 690,
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
