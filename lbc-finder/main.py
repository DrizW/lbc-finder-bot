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
            # Ancienne structure (simple int) : on ignore
            continue

        params_kwargs = {"text": cfg.get("keywords", name)}

        lat = cfg.get("lat")
        lng = cfg.get("lng")
        city = cfg.get("city", "")
        radius_km = cfg.get("radius_km", 20)

        if lat and lng:
            params_kwargs["locations"] = [
                lbc.City(
                    lat=lat,
                    lng=lng,
                    radius=radius_km * 1000,
                    city=city,
                )
            ]

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

    # Inject searcher into bot so /addsearch and /delsearch can control it live
    set_searcher(searcher)

    searcher.start()
    start_bot()  # Blocking — runs the Discord event loop


if __name__ == "__main__":
    main()
