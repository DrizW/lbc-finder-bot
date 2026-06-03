import lbc
from analyzers import analyze_listing
from analyzers.niche_matcher import match_niche
from bot import (
    get_filter_reason,
    load_settings,
    record_stat,
    send_opportunity_alert_threadsafe,
)
from config.niches import load_niches
from database.models import RawListing
from database.repositories import ListingRepository
from analyzers.text import contains_phrase, joined_text


_repository = ListingRepository()


def _ad_field(ad, *names, default=None):
    for name in names:
        if hasattr(ad, name):
            value = getattr(ad, name)
            if value is not None:
                return value
    return default


def _raw_listing_from_ad(ad) -> RawListing:
    images = _ad_field(ad, "images", default=[]) or []
    if isinstance(images, str):
        images = [images]
    return RawListing(
        platform=str(_ad_field(ad, "source", default="leboncoin")),
        external_id=str(_ad_field(ad, "id", default=_ad_field(ad, "url", default=""))),
        title=str(_ad_field(ad, "subject", "title", default="")),
        description=str(_ad_field(ad, "body", "description", default="")),
        price=_ad_field(ad, "price", default=None),
        location=str(_ad_field(ad, "location", default="")),
        category=str(_ad_field(ad, "category", default="")),
        url=str(_ad_field(ad, "url", default="")),
        image_urls=list(images),
        published_at=str(_ad_field(ad, "index_date", "published_at", default="")),
    )


def _blocked_by_niche(raw: RawListing, niche: dict) -> str | None:
    text = joined_text(raw.title, raw.description, raw.category)
    for keyword in niche.get("negative_keywords", []):
        if contains_phrase(text, keyword):
            return f"mot-clé bloquant: {keyword}"
    if raw.price is not None:
        min_price = niche.get("min_price")
        max_price = niche.get("max_price")
        if min_price is not None and raw.price < min_price:
            return f"prix {raw.price} € < min niche {min_price} €"
        if max_price is not None and raw.price > max_price:
            return f"prix {raw.price} € > max niche {max_price} €"
    return None


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
    raw = _raw_listing_from_ad(ad)
    niches = load_niches()

    reason = get_filter_reason(ad, cfg)
    if reason:
        print(f"[{search_name}] 🚫 Ignorée — {reason}.")
        record_stat(search_name, "filtered")
        _repository.upsert_raw(raw)
        return

    _repository.upsert_raw(raw)
    niche, niche_score = match_niche(raw, niches)
    if niche is None:
        print(f"[{search_name}] 🚫 Aucune niche active ne correspond à l'annonce.")
        record_stat(search_name, "filtered")
        return

    opportunity = analyze_listing(raw, niche, _repository)
    blocked_reason = _blocked_by_niche(raw, niche)
    min_heat_score = niche.get("min_heat_score", 75)
    status = "ignored"

    if blocked_reason:
        print(f"[{search_name}] 🚫 Ignorée — {blocked_reason}.")
        record_stat(search_name, "filtered")
    elif opportunity.heat_score < min_heat_score:
        print(
            f"[{search_name}] 🚫 Score insuffisant — "
            f"{opportunity.heat_score}/{min_heat_score}."
        )
        record_stat(search_name, "filtered")
    else:
        status = "alerted"
        print(
            f"[{search_name}] 🔥 Opportunité : "
            f"{opportunity.heat_score}/100 — {niche.get('name')} — {raw.title}"
        )
        record_stat(search_name, "alerted")
        send_opportunity_alert_threadsafe(opportunity, search_name, niche.get("name"))

    _repository.update_analysis(
        raw,
        opportunity.analysis,
        opportunity.market,
        opportunity.margin,
        opportunity.heat_score,
        status,
    )
