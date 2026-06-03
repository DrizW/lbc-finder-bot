import re
import unicodedata


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return text.lower()


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize(text)
    normalized_phrase = normalize(phrase)
    if " " in normalized_phrase:
        return normalized_phrase in normalized_text
    return bool(re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_text))


def joined_text(*parts: object) -> str:
    return " ".join(str(part or "") for part in parts)
