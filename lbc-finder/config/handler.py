import lbc
from bot import load_settings, send_alert_threadsafe, record_stat


def handle(ad: lbc.Ad, search_name: str):
    settings = load_settings()
    cfg = settings.get(search_name)

    # Support both new dict format and legacy int format
    if isinstance(cfg, dict):
        max_price = cfg.get("max_price")
        min_price = cfg.get("min_price", 0)
    elif isinstance(cfg, (int, float)):
        max_price = cfg
        min_price = 0
    else:
        max_price = None
        min_price = 0

    # Count every ad found
    record_stat(search_name, "found")

    # Filter by max price
    if max_price is not None and ad.price is not None and ad.price > max_price:
        print(
            f"[{search_name}] 🚫 Ignorée — prix ({ad.price} €) > limite ({max_price} €)."
        )
        record_stat(search_name, "filtered")
        return

    # Detect bargain (price below min_price threshold)
    is_bargain = (
        min_price > 0
        and ad.price is not None
        and ad.price < min_price
    )

    if is_bargain:
        print(f"[{search_name}] 🚨 PÉPITE détectée : {ad.subject} à {ad.price} € (seuil: {min_price} €)")
    else:
        print(f"[{search_name}] 🔔 Nouvelle annonce : {ad.subject} à {ad.price} €")

    record_stat(search_name, "alerted")
    send_alert_threadsafe(ad, search_name, is_bargain=is_bargain)
