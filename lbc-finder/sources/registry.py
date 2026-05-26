from .ebay import EbaySource
from .leboncoin import LeboncoinSource


def get_source(name: str, request_verify: bool = True):
    normalized = name.strip().lower()
    if normalized in {"leboncoin", "lbc"}:
        return LeboncoinSource(request_verify=request_verify)
    if normalized == "ebay":
        return EbaySource()
    return None
