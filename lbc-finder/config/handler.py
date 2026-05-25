import lbc
from bot import (
    get_filter_reason,
    is_bargain_ad,
    load_settings,
    record_stat,
    send_alert_threadsafe,
)


def handle(ad: lbc.Ad, search_name: str):
    settings = load_settings()
    cfg = settings.get(search_name)

    # Support both new dict format and legacy int format
    if isinstance(cfg, (int, float)):
        cfg = {"max_price": cfg, "min_price": 0}
    elif not isinstance(cfg, dict):
        cfg = {"max_price": None, "min_price": 0}

    # Count every ad found
    record_stat(search_name, "found")

    reason = get_filter_reason(ad, cfg)
    if reason:
        print(f"[{search_name}] 🚫 Ignorée — {reason}.")
        record_stat(search_name, "filtered")
        return

    # Detect bargain (price below min_price threshold)
    is_bargain = is_bargain_ad(ad, cfg)

    if is_bargain:
        print(f"[{search_name}] 🚨 PÉPITE détectée : {ad.subject} à {ad.price} €")
    else:
        print(f"[{search_name}] 🔔 Nouvelle annonce : {ad.subject} à {ad.price} €")

    record_stat(search_name, "alerted")
    send_alert_threadsafe(ad, search_name, is_bargain=is_bargain)
