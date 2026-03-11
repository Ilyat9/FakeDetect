from dataclasses import dataclass, field
from typing import List, Optional
from abc import ABC, abstractmethod


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
        url_lower = url.lower()
        if 'wildberries.ru' in url_lower:
            return 'WB'
        elif 'ozon.ru' in url_lower:
            return 'Ozon'
        elif 'market.yandex.ru' in url_lower or 'yandex.net' in url_lower:
            return 'YANDEX'
        return 'UNKNOWN'
