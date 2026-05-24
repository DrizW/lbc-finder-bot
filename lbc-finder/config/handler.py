import lbc
from bot import load_settings, send_alert_threadsafe


def handle(ad: lbc.Ad, search_name: str):
    settings = load_settings()
    cfg = settings.get(search_name)

    # Support both new dict format and legacy int format
    if isinstance(cfg, dict):
        max_price = cfg.get("max_price")
    elif isinstance(cfg, (int, float)):
        max_price = cfg
    else:
        max_price = None

    if max_price is not None and ad.price is not None and ad.price > max_price:
        print(
            f"[{search_name}] Annonce ignorée — prix ({ad.price} €) "
            f"> limite ({max_price} €)."
        )
        return

    print(f"[{search_name}] 🔔 Nouvelle annonce : {ad.subject} à {ad.price} €")
    send_alert_threadsafe(ad, search_name)
