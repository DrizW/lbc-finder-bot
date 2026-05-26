from dataclasses import dataclass, field
from typing import Protocol

from model import Search


@dataclass
class DealAd:
    id: str
    subject: str
    price: float | int | None
    url: str
    source: str
    images: list[str] = field(default_factory=list)
    body: str = ""
    location: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


class Source(Protocol):
    name: str

    def search(self, search: Search) -> list[DealAd]:
        ...
