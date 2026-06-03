from database.models import ListingAnalysis, MarginEstimate, MarketStats, RawListing


def heat_label(score: int) -> str:
    if score < 40:
        return "PAS INTÉRESSANT"
    if score < 60:
        return "MOYEN"
    if score < 75:
        return "CORRECT"
    if score < 85:
        return "BONNE OPPORTUNITÉ"
    return "OFFRE TRÈS CHAUDE"


def calculate_heat_score(
    listing: RawListing,
    analysis: ListingAnalysis,
    market: MarketStats,
    margin: MarginEstimate,
) -> tuple[int, list[str]]:
    score = 20
    reasons = []

    if listing.price is not None and market.median:
        if listing.price <= market.median * 0.5:
            score += 30
            reasons.append("Prix très inférieur au marché")
        elif listing.price <= market.median * 0.7:
            score += 18
            reasons.append("Prix inférieur au marché")

    realistic_margin = margin.estimated_margin_realistic
    if realistic_margin is not None:
        if realistic_margin > 150:
            score += 25
            reasons.append("Marge réaliste supérieure à 150 €")
        elif realistic_margin > 80:
            score += 15
            reasons.append("Marge réaliste supérieure à 80 €")

    if analysis.detected_accessories:
        score += min(10, len(analysis.detected_accessories) * 4)
        reasons.append("Accessoires inclus")

    if analysis.identification_confidence >= 0.8:
        score += 12
        reasons.append("Produit identifié avec confiance")
    elif analysis.identification_confidence < 0.5:
        score -= 15
        reasons.append("Identification peu fiable")

    if market.comparable_count < 3:
        score -= 8
        reasons.append("Peu de comparables en base")

    if analysis.risk_flags:
        score -= min(20, len(analysis.risk_flags) * 6)
        reasons.append("Risques à vérifier")

    return max(0, min(100, int(score))), reasons
