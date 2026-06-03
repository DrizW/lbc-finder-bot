import os


PREMIUM_STROLLER_NICHE = {
    "name": "Poussettes premium",
    "enabled": True,
    "min_heat_score": 75,
    "min_price": 50,
    "max_price": 800,
    "target_products": [
        {"brand": "Cybex", "models": ["Priam", "Balios", "Mios"]},
        {"brand": "Babyzen", "models": ["Yoyo", "Yoyo2", "Yoyo 3"]},
        {"brand": "Bugaboo", "models": ["Fox", "Dragonfly", "Donkey"]},
        {"brand": "Stokke", "models": ["Xplory", "Trailz"]},
    ],
    "positive_keywords": [
        "poussette",
        "cosy",
        "nacelle",
        "trio",
        "pack naissance",
        "bébé",
    ],
    "negative_keywords": [
        "housse seule",
        "adaptateur seul",
        "notice",
        "jouet",
        "miniature",
        "recherche",
        "donne",
    ],
}


def load_premium_stroller_niche() -> dict:
    # The YAML file is kept as human-readable config for the MVP. To avoid adding
    # a dependency, this loader returns the same default structure directly.
    yaml_path = os.path.join(os.path.dirname(__file__), "niches.yaml")
    niche = dict(PREMIUM_STROLLER_NICHE)
    niche["config_path"] = yaml_path
    return niche
