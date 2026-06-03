import copy
import os


DEFAULT_NICHES = [
    {
        "name": "Poussettes premium",
        "enabled": True,
        "min_heat_score": 75,
        "min_price": 50,
        "max_price": 800,
        "liquidity_score": 8,
        "product_families": [
            {
                "name": "poussette",
                "synonyms": ["poussette", "cosy", "nacelle", "trio", "pack naissance"],
            }
        ],
        "target_products": [
            {"brand": "Cybex", "models": ["Priam", "Balios", "Mios"]},
            {"brand": "Babyzen", "models": ["Yoyo", "Yoyo2", "Yoyo 3"]},
            {"brand": "Bugaboo", "models": ["Fox", "Dragonfly", "Donkey"]},
            {"brand": "Stokke", "models": ["Xplory", "Trailz"]},
        ],
        "positive_keywords": ["poussette", "cosy", "nacelle", "trio"],
        "negative_keywords": ["housse seule", "adaptateur seul", "notice", "jouet"],
        "accessory_keywords": ["cosy", "nacelle", "base isofix", "housse pluie"],
        "risk_keywords": ["manque", "cassé", "abîmé", "incomplet", "frein défectueux"],
        "default_estimated_costs": {"cleaning": 15, "travel": 10, "misc": 10},
    },
    {
        "name": "Aspirateurs Dyson",
        "enabled": True,
        "min_heat_score": 75,
        "min_price": 40,
        "max_price": 600,
        "liquidity_score": 9,
        "product_families": [
            {"name": "aspirateur", "synonyms": ["aspirateur", "dyson", "balai"]}
        ],
        "target_products": [
            {"brand": "Dyson", "models": ["V8", "V10", "V11", "V12", "V15", "Gen5"]}
        ],
        "positive_keywords": ["aspirateur", "dyson", "balai"],
        "negative_keywords": ["brosse seule", "filtre seul", "chargeur seul", "pour pièces"],
        "accessory_keywords": ["chargeur", "station", "brosse motorisée", "accessoires"],
        "risk_keywords": ["batterie faible", "ne charge plus", "cassé", "pour pièces"],
        "default_estimated_costs": {"cleaning": 10, "travel": 10, "misc": 15},
    },
    {
        "name": "Consoles",
        "enabled": True,
        "min_heat_score": 72,
        "min_price": 50,
        "max_price": 700,
        "liquidity_score": 9,
        "product_families": [
            {"name": "console", "synonyms": ["console", "playstation", "xbox", "switch"]}
        ],
        "target_products": [
            {"brand": "Sony", "models": ["PS5", "Playstation 5", "PS4"]},
            {"brand": "Microsoft", "models": ["Xbox Series X", "Xbox Series S"]},
            {"brand": "Nintendo", "models": ["Switch", "Switch OLED"]},
        ],
        "positive_keywords": ["console", "manette", "jeu"],
        "negative_keywords": ["boîte vide", "manette seule", "jeu seul", "pour pièces"],
        "accessory_keywords": ["manette", "câble hdmi", "boîte", "jeux", "dock"],
        "risk_keywords": ["ban", "drift", "ne s'allume plus", "lecteur hs"],
        "default_estimated_costs": {"cleaning": 10, "travel": 10, "misc": 10},
    },
]


def _config_path() -> str:
    return os.getenv(
        "LBC_NICHES_FILE",
        os.path.join(os.path.dirname(__file__), "niches.yaml"),
    )


def _parse_scalar(value: str):
    value = value.strip().strip('"').strip("'")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _load_simple_yaml(path: str) -> list[dict]:
    niches: list[dict] = []
    current_niche = None
    current_section = None
    current_subsection = None
    current_product = None
    current_family = None

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            line = raw_line.strip()

            if indent == 0:
                continue

            if indent == 2 and line.startswith("- "):
                current_niche = {}
                niches.append(current_niche)
                current_section = None
                current_subsection = None
                current_product = None
                current_family = None
                item = line[2:]
                if ":" in item:
                    key, value = item.split(":", 1)
                    current_niche[key.strip()] = _parse_scalar(value)
                continue

            if current_niche is None:
                continue

            if indent == 4:
                key, _, value = line.partition(":")
                key = key.strip()
                if value.strip():
                    current_niche[key] = _parse_scalar(value)
                    current_section = None
                    current_subsection = None
                else:
                    current_section = key
                    current_subsection = None
                    if key == "default_estimated_costs":
                        current_niche[key] = {}
                    else:
                        current_niche[key] = []
                current_product = None
                current_family = None
                continue

            if indent == 6 and line.startswith("- "):
                item = line[2:]
                if current_section == "target_products":
                    current_product = {"models": []}
                    current_family = None
                    current_niche[current_section].append(current_product)
                    if ":" in item:
                        key, value = item.split(":", 1)
                        current_product[key.strip()] = _parse_scalar(value)
                elif current_section == "product_families":
                    current_family = {"synonyms": []}
                    current_product = None
                    current_niche[current_section].append(current_family)
                    if ":" in item:
                        key, value = item.split(":", 1)
                        current_family[key.strip()] = _parse_scalar(value)
                elif current_section:
                    current_niche[current_section].append(_parse_scalar(item))
                continue

            if indent == 6 and current_section == "default_estimated_costs":
                key, _, value = line.partition(":")
                current_niche[current_section][key.strip()] = _parse_scalar(value)
                continue

            if indent == 8 and current_product is not None:
                key, _, value = line.partition(":")
                if value.strip():
                    current_product[key.strip()] = _parse_scalar(value)
                else:
                    current_subsection = key.strip()
                continue

            if indent == 8 and current_family is not None:
                key, _, value = line.partition(":")
                if value.strip():
                    current_family[key.strip()] = _parse_scalar(value)
                else:
                    current_subsection = key.strip()
                continue

            if indent == 10 and line.startswith("- "):
                item = _parse_scalar(line[2:])
                if current_product is not None and current_subsection == "models":
                    current_product.setdefault("models", []).append(item)
                elif current_family is not None and current_subsection == "synonyms":
                    current_family.setdefault("synonyms", []).append(item)

    return [niche for niche in niches if niche.get("enabled", True)]


def load_niches() -> list[dict]:
    path = _config_path()
    if os.path.exists(path):
        try:
            import yaml  # type: ignore

            with open(path, "r", encoding="utf-8") as f:
                payload = yaml.safe_load(f) or {}
            niches = payload.get("niches", payload if isinstance(payload, list) else [])
            return [niche for niche in niches if niche.get("enabled", True)]
        except Exception:
            parsed = _load_simple_yaml(path)
            if parsed:
                return parsed
    return [copy.deepcopy(niche) for niche in DEFAULT_NICHES if niche.get("enabled", True)]


def load_premium_stroller_niche() -> dict:
    for niche in load_niches():
        if niche.get("name") == "Poussettes premium":
            return niche
    return copy.deepcopy(DEFAULT_NICHES[0])
