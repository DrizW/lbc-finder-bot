from database.models import RawListing
from .text import contains_phrase, joined_text


def _matches_any(text: str, phrases: list[str]) -> int:
    return sum(1 for phrase in phrases if contains_phrase(text, phrase))


def match_niche(listing: RawListing, niches: list[dict]) -> tuple[dict | None, int]:
    text = joined_text(listing.title, listing.description, listing.category)
    best_niche = None
    best_score = 0

    for niche in niches:
        if not niche.get("enabled", True):
            continue

        if listing.price is not None:
            min_price = niche.get("min_price")
            max_price = niche.get("max_price")
            if min_price is not None and listing.price < min_price:
                continue
            if max_price is not None and listing.price > max_price:
                continue

        if _matches_any(text, niche.get("negative_keywords", [])):
            continue

        score = 0
        for family in niche.get("product_families", []):
            if _matches_any(text, family.get("synonyms", [])):
                score += 20
        score += min(20, _matches_any(text, niche.get("positive_keywords", [])) * 5)

        for product in niche.get("target_products", []):
            brand = product.get("brand")
            if brand and contains_phrase(text, brand):
                score += 25
            if _matches_any(text, product.get("models", [])):
                score += 25

        score += min(10, int(niche.get("liquidity_score", 0)))

        if score > best_score:
            best_score = score
            best_niche = niche

    if best_score < 20:
        return None, best_score
    return best_niche, best_score
