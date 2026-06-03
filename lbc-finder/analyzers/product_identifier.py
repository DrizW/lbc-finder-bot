from database.models import ListingAnalysis, RawListing
from .text import contains_phrase, joined_text, normalize


PRODUCT_WORDS = ["poussette", "cosy", "nacelle", "trio", "pack naissance", "bébé"]
ACCESSORIES = [
    "cosy",
    "nacelle",
    "base isofix",
    "adaptateurs",
    "housse pluie",
    "sac de transport",
    "chancelière",
    "habillage pluie",
]
IMPORTANT_ACCESSORIES = ["cosy", "nacelle"]


def identify_product(listing: RawListing, niche: dict) -> ListingAnalysis:
    text = joined_text(listing.title, listing.description, listing.category)
    normalized = normalize(text)
    detected_brand = None
    detected_model = None

    for product in niche.get("target_products", []):
        brand = product.get("brand")
        if brand and contains_phrase(normalized, brand):
            detected_brand = brand
        for model in product.get("models", []):
            if contains_phrase(normalized, model):
                detected_brand = brand
                detected_model = model
                break
        if detected_model:
            break

    product_hits = [word for word in PRODUCT_WORDS if contains_phrase(normalized, word)]
    detected_product_type = "poussette" if product_hits else None
    accessories = [
        accessory for accessory in ACCESSORIES if contains_phrase(normalized, accessory)
    ]
    missing = [
        accessory for accessory in IMPORTANT_ACCESSORIES if accessory not in accessories
    ]

    confidence = 0.2
    if detected_product_type:
        confidence += 0.2
    if detected_brand:
        confidence += 0.25
    if detected_model:
        confidence += 0.25
    if accessories:
        confidence += min(0.1, len(accessories) * 0.03)

    return ListingAnalysis(
        detected_product_type=detected_product_type,
        detected_brand=detected_brand,
        detected_model=detected_model,
        detected_accessories=accessories,
        missing_accessories=missing,
        identification_confidence=round(min(confidence, 0.98), 2),
        resale_difficulty="moyenne",
        recommended_action="contacter rapidement" if confidence >= 0.75 else "vérifier",
    )
