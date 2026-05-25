from .logger import logger

import os
import json
import threading

MAX_ID: int = 10_000
LEGACY_BUCKET = "__legacy__"


class ID:
    def __init__(self):
        self._id_path = os.path.join(
            os.getenv("LBC_DATA_DIR", os.path.join(os.getcwd(), "data")),
            "id.json",
        )
        self._lock = threading.Lock()
        self._ids: dict[str, list[str]] = self._get_ids()

    @property
    def ids(self) -> dict[str, list[str]]:
        return self._ids

    def _get_ids(self) -> dict[str, list[str]]:
        ids: dict[str, list[str]] = {}
        if os.path.exists(self._id_path):
            with open(self._id_path, "r", encoding="utf-8") as f:
                try:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        ids[LEGACY_BUCKET] = [str(id_) for id_ in loaded]
                    elif isinstance(loaded, dict):
                        ids = {
                            str(name): [str(id_) for id_ in values]
                            for name, values in loaded.items()
                            if isinstance(values, list)
                        }
                except json.JSONDecodeError:
                    os.remove(self._id_path)
                except Exception:
                    logger.exception(
                        "An error occurred while attempting to open the id.json file."
                    )
        return ids

    def contains(self, search_name: str, id_: str) -> bool:
        id_ = str(id_)
        return id_ in self._ids.get(search_name, []) or id_ in self._ids.get(
            LEGACY_BUCKET, []
        )

    def add(self, search_name: str, id_: str) -> bool:
        id_ = str(id_)
        with self._lock:
            ids = self._ids.setdefault(search_name, [])
            if id_ in ids:
                return False

            ids.append(id_)
            self._ids[search_name] = ids[-MAX_ID:]
            os.makedirs(os.path.dirname(self._id_path), exist_ok=True)
            with open(self._id_path, "w", encoding="utf-8") as f:
                json.dump(self._ids, f, indent=3, ensure_ascii=False)
            return True
