import logging
from .base import MarketplaceParser, ParseResult
from .wildberries import WildberriesParser
from .ozon import OzonParser
from .yandex import YandexParser

logger = logging.getLogger(__name__)


async def get_parser(url: str, browser_page=None) -> MarketplaceParser:
    """
    Get appropriate parser for the marketplace URL.

    Args:
        url: Marketplace URL
        browser_page: Optional Playwright page for dynamic content

    Returns:
        MarketplaceParser instance
    """
    marketplace = url.lower()

    if 'wildberries.ru' in marketplace:
        return WildberriesParser(url, browser_page)
    elif 'ozon.ru' in marketplace:
        return OzonParser(url, browser_page)
    elif 'market.yandex.ru' in marketplace or 'yandex.net' in marketplace:
        return YandexParser(url, browser_page)
    else:
        logger.warning(f"Unknown marketplace URL: {url}")
        raise ValueError(f"Unsupported marketplace: {url}")
