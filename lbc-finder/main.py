from model import Search, Parameters
from searcher import Searcher
from config.handler import handle
from bot import load_settings, set_searcher, start_bot
import lbc


def build_searches_from_settings() -> list[Search]:
    """Reconstruit les objets Search depuis le fichier settings.json au démarrage."""
    settings = load_settings()
    searches = []
    for name, cfg in settings.items():
        if not isinstance(cfg, dict):
            continue

        # Skip paused searches at startup
        if cfg.get("paused", False):
            print(f"[Startup] ⏸️ Niche '{name}' en pause — ignorée au démarrage.")
            continue

        params_kwargs = {"text": cfg.get("keywords", name)}

        if cfg.get("lat") and cfg.get("lng"):
            params_kwargs["locations"] = [
                lbc.City(
                    lat=cfg["lat"],
                    lng=cfg["lng"],
                    radius=cfg.get("radius_km", 20) * 1000,
                    city=cfg.get("city", ""),
                )
            ]

        if cfg.get("owner_type") == "private":
            params_kwargs["owner_type"] = lbc.OwnerType.PRIVATE

        searches.append(
            Search(
                name=name,
                parameters=Parameters(**params_kwargs),
                delay=60,
                handler=handle,
            )
        )
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
