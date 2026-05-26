import base64
import json
import os
import time
import urllib.parse
import urllib.request

from model import Search
from .base import DealAd
from searcher.logger import logger


class EbaySource:
    name = "ebay"
    _token: str | None = None
    _token_expires_at: float = 0

    def _credentials(self) -> tuple[str | None, str | None]:
        return os.getenv("EBAY_CLIENT_ID"), os.getenv("EBAY_CLIENT_SECRET")

    def _marketplace(self) -> str:
        return os.getenv("EBAY_MARKETPLACE_ID", "EBAY_FR")

    def _get_token(self) -> str | None:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        client_id, client_secret = self._credentials()
        if not client_id or not client_secret:
            logger.warning("[ebay] Identifiants API absents, source ignorée.")
            return None

        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode("utf-8")
        ).decode("ascii")
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            "https://api.ebay.com/identity/v1/oauth2/token",
            data=body,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception("[ebay] Impossible d'obtenir un token API.")
            return None

        self._token = payload.get("access_token")
        self._token_expires_at = time.time() + int(payload.get("expires_in", 0))
        return self._token

    def search(self, search: Search) -> list[DealAd]:
        token = self._get_token()
        if not token:
            return []

        query = search.parameters._kwargs.get("text", "")
        max_price = None
        price = search.parameters._kwargs.get("price")
        if isinstance(price, list) and len(price) > 1:
            max_price = price[1]

        filters = ["buyingOptions:{FIXED_PRICE}"]
        if max_price:
            filters.append(f"price:[..{max_price}]")

        params = {
            "q": query,
            "limit": "20",
            "sort": "newlyListed",
            "filter": ",".join(filters),
        }
        url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(
            params
        )
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self._marketplace(),
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.exception("[ebay] Erreur lors de la recherche.")
            return []

        ads = []
        for item in payload.get("itemSummaries", []):
            item_id = str(item.get("itemId", ""))
            title = item.get("title") or "Annonce eBay"
            price_value = item.get("price", {}).get("value")
            try:
                parsed_price = float(price_value) if price_value is not None else None
            except (TypeError, ValueError):
                parsed_price = None

            image_url = item.get("image", {}).get("imageUrl")
            seller = item.get("seller", {}).get("username", "")
            ads.append(
                DealAd(
                    id=f"ebay:{item_id}",
                    subject=title,
                    price=parsed_price,
                    url=item.get("itemWebUrl", ""),
                    source=self.name,
                    images=[image_url] if image_url else [],
                    body=title,
                    location=item.get("itemLocation", {}).get("postalCode", ""),
                    attributes={"seller": seller, "source": self.name},
                )
            )
        return ads
