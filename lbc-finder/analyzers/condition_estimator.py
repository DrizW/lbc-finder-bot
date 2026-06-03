from .text import contains_phrase, joined_text, normalize


CONDITION_RULES = [
    ("cassé", ["cassé", "à réparer", "frein défectueux", "roue abîmée"]),
    ("incomplet", ["incomplet", "manque une pièce", "manque"]),
    ("abîmé", ["abîmé", "tache", "taches", "à nettoyer"]),
    ("état correct", ["état correct", "quelques rayures"]),
    ("bon état", ["bon état"]),
    ("très bon état", ["très bon état"]),
    ("comme neuf", ["comme neuf", "jamais utilisé", "neuf"]),
]

RISK_RULES = {
    "manque": "vérifier pièces manquantes",
    "cassé": "vérifier casse",
    "abîmé": "vérifier usure",
    "tache": "vérifier textile",
    "à réparer": "réparation probable",
    "incomplet": "vérifier accessoires",
    "sans facture": "vérifier preuve d'achat",
    "pas testé": "tester avant achat",
    "problème de pliage": "vérifier pliage",
    "roue abîmée": "vérifier roues",
    "frein défectueux": "vérifier frein",
    "frein à vérifier": "vérifier frein",
}


def estimate_condition(title: str, description: str) -> tuple[str | None, list[str]]:
    text = normalize(joined_text(title, description))
    condition = None
    for label, phrases in CONDITION_RULES:
        if any(contains_phrase(text, phrase) for phrase in phrases):
            condition = label
            break

    risks = [
        risk for phrase, risk in RISK_RULES.items() if contains_phrase(text, phrase)
    ]
    return condition, sorted(set(risks))
