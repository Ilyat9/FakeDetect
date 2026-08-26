from dataclasses import dataclass, field
from typing import List, Optional
from abc import ABC, abstractmethod


# Single source of truth for supported marketplaces (used by both
# MarketplaceParser._get_marketplace and parsers.factory.get_parser).
SUPPORTED_MARKETPLACES = {
    "wildberries.ru": "WB",
    "ozon.ru": "Ozon",
    "market.yandex.ru": "YANDEX",
    "yandex.net": "YANDEX",
}


def detect_marketplace(url: str) -> str:
    """Detect marketplace name from URL. Returns 'UNKNOWN' for unsupported hosts."""
    url_lower = url.lower()
    for domain, marketplace in SUPPORTED_MARKETPLACES.items():
        if domain in url_lower:
            return marketplace
    return "UNKNOWN"


@dataclass
class ParseResult:
    """Result of parsing a marketplace URL."""
    card_images: List[str] = field(default_factory=list)  # Base64 images from product card
    review_images: List[str] = field(default_factory=list)  # Base64 images from reviews
    qa_images: List[str] = field(default_factory=list)  # Base64 images from Q&A
    seller: Optional[str] = None
    price: Optional[float] = None
    title: Optional[str] = None
    marketplace: str = ""
    error: Optional[str] = None


class MarketplaceParser(ABC):
    """Abstract base class for marketplace parsers."""

    def __init__(self, url: str, browser_page=None):
        self.url = url
        self.browser_page = browser_page
        self.marketplace = self._get_marketplace(url)

    @abstractmethod
    async def get_all_images(self) -> ParseResult:
        """Extract all images from the marketplace URL."""
        pass

    @staticmethod
    def _get_marketplace(url: str) -> str:
        """Detect marketplace from URL."""
        from .base import detect_marketplace
        return detect_marketplace(url)
