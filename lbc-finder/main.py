from model import Search, Parameters
from searcher import Searcher
from config.handler import handle
from bot import (
    get_settings_path,
    load_settings,
    parse_expires_at,
    parse_sources,
    set_searcher,
    start_bot,
)
import lbc


def build_searches_from_settings() -> list[Search]:
    """Reconstruit les objets Search depuis le fichier settings.json au démarrage."""
    settings = load_settings()
    print(f"[Startup] Configuration chargée depuis: {get_settings_path()}")
    searches = []
    for name, cfg in settings.items():
        if not isinstance(cfg, dict):
            continue

        # Skip paused searches at startup
        if cfg.get("paused", False):
            print(f"[Startup] ⏸️ Niche '{name}' en pause — ignorée au démarrage.")
            continue

        expires_at = parse_expires_at(cfg.get("expires_at"))
        if expires_at is not None:
            import time

            if time.time() >= expires_at:
                print(f"[Startup] ⏳ Niche '{name}' expirée — ignorée au démarrage.")
                continue

        query = f"{cfg.get('keywords', name)} {cfg.get('marque', '')}".strip()
        params_kwargs = {"text": query}

        if cfg.get("lat") and cfg.get("lng"):
            params_kwargs["locations"] = [
                lbc.City(
                    lat=cfg["lat"],
                    lng=cfg["lng"],
                    radius=cfg.get("radius_km", 20) * 1000,
                    city=cfg.get("city", ""),
                )
            ]

        max_price = cfg.get("max_price")
        if isinstance(max_price, (int, float)) and max_price > 0:
            params_kwargs["price"] = [0, max_price]

        if cfg.get("owner_type") == "private":
            params_kwargs["owner_type"] = lbc.OwnerType.PRIVATE

        searches.append(
            Search(
                name=name,
                parameters=Parameters(**params_kwargs),
                delay=60,
                handler=handle,
                sources=parse_sources(cfg.get("sources")),
                expires_at=expires_at,
            )
        )
        print(f"[Startup] ✅ Niche chargée: {name}")
    return searches


def main() -> None:
    initial_searches = build_searches_from_settings()
    searcher = Searcher(searches=initial_searches)

    # Inject searcher into bot so /addsearch, /delsearch, /pause, /resume can control it live
    set_searcher(searcher)

    searcher.start()
    start_bot()  # Blocking — runs the Discord event loop


if __name__ == "__main__":
    main()
