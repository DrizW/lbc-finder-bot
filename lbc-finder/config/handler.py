import lbc
from bot import load_settings, send_alert_threadsafe

def handle(ad: lbc.Ad, search_name: str):
    settings = load_settings()
    max_price = settings.get(search_name)

    if max_price is not None and ad.price > max_price:
        print(f"[{search_name}] Annonce ignorée car le prix ({ad.price} €) dépasse la limite ({max_price} €).")
        return

    print(f"[{search_name}] Nouvelle annonce: {ad.subject} à {ad.price} €")
    send_alert_threadsafe(ad, search_name)
