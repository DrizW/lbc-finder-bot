from model import Search
from lbc import Client, Sort
from .id import ID
from .logger import logger

import time
import threading


class Searcher:
    def __init__(
        self,
        searches: list[Search] | Search | None = None,
        request_verify: bool = True,
        handler_max_attempts: int = 3,
        handler_initial_backoff: float = 2.0,
    ):
        if searches is None:
            searches = []
        self._searches: list[Search] = (
            searches if isinstance(searches, list) else [searches]
        )
        self._request_verify = request_verify
        self._handler_max_attempts = handler_max_attempts
        self._handler_initial_backoff = handler_initial_backoff
        self._id = ID()
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _handle_with_retry(self, search: Search, ad) -> bool:
        for attempt in range(1, self._handler_max_attempts + 1):
            try:
                search.handler(ad, search.name)
                return True
            except Exception:
                if attempt == self._handler_max_attempts:
                    logger.exception(
                        f"[{search.name}] Handler failed for ad {ad.id} after {attempt} attempts."
                    )
                    return False

                delay = self._handler_initial_backoff * (2 ** (attempt - 1))
                logger.warning(
                    f"[{search.name}] Handler failed for ad {ad.id}. "
                    f"Retrying in {delay:.0f}s ({attempt}/{self._handler_max_attempts})."
                )
                time.sleep(delay)
        return False

    def _search(self, search: Search, stop_event: threading.Event) -> None:
        client = Client(proxy=search.proxy, request_verify=self._request_verify)
        while not stop_event.is_set():
            before = time.time()
            try:
                response = client.search(**search.parameters._kwargs, sort=Sort.NEWEST)
                logger.debug(
                    f"[{search.name}] {response.total} annonce(s) trouvée(s)."
                )
                ads = [ad for ad in response.ads if not self._id.contains(ad.id)]
                if ads:
                    logger.info(
                        f"[{search.name}] {len(ads)} nouvelle(s) annonce(s) !"
                    )

                notified = 0
                for ad in ads:
                    if self._handle_with_retry(search, ad) and self._id.add(ad.id):
                        notified += 1

                if ads and notified != len(ads):
                    logger.warning(
                        f"[{search.name}] {len(ads) - notified} annonce(s) non marquée(s), elles seront retraitées."
                    )
            except Exception:
                logger.exception(f"[{search.name}] Erreur lors de la recherche.")

            elapsed = time.time() - before
            wait = max(0, search.delay - elapsed)
            # Sleep in small chunks so the stop_event is checked regularly
            stop_event.wait(timeout=wait)

    def add_search_thread(self, search: Search) -> bool:
        """Adds (or replaces) a search thread at runtime without restarting."""
        with self._lock:
            # Stop existing thread for this niche if it exists
            self.remove_search_thread(search.name)

            stop_event = threading.Event()
            t = threading.Thread(
                target=self._search,
                args=(search, stop_event),
                name=search.name,
                daemon=True,
            )
            self._stop_events[search.name] = stop_event
            self._threads[search.name] = t
            t.start()
            logger.info(f"[{search.name}] Thread de recherche démarré.")
            return True

    def remove_search_thread(self, name: str) -> bool:
        """Stops the search thread for a given niche name."""
        with self._lock:
            if name in self._stop_events:
                self._stop_events[name].set()
                del self._stop_events[name]
            if name in self._threads:
                del self._threads[name]
                logger.info(f"[{name}] Thread de recherche arrêté.")
                return True
        return False

    def start(self) -> bool:
        if not self._searches:
            logger.warning(
                "Aucune niche configurée au démarrage. "
                "Utilisez /addsearch dans Discord pour en ajouter."
            )
            return True  # Not an error — Discord commands will add them

        for search in self._searches:
            self.add_search_thread(search)
            time.sleep(2)  # Stagger thread starts to avoid request spam
        return True
