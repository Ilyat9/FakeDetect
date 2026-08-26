import logging
from .base import MarketplaceParser, ParseResult, detect_marketplace, SUPPORTED_MARKETPLACES
from .wildberries import WildberriesParser
from .ozon import OzonParser
from .yandex import YandexParser

logger = logging.getLogger(__name__)

_MARKETPLACE_PARSER_CLASSES = {
    "WB": WildberriesParser,
    "Ozon": OzonParser,
    "YANDEX": YandexParser,
}


async def get_parser(url: str, browser_page=None) -> MarketplaceParser:
    """
    Get appropriate parser for the marketplace URL.

    Args:
        url: Marketplace URL
        browser_page: Optional Playwright page for dynamic content

    Returns:
        MarketplaceParser instance

    Raises:
        ValueError: for unsupported marketplaces (4.5: single source of truth
            in parsers.base.SUPPORTED_MARKETPLACES).
    """
    marketplace = detect_marketplace(url)
    parser_class = _MARKETPLACE_PARSER_CLASSES.get(marketplace)
    if not parser_class:
        logger.warning(f"Unknown marketplace URL: {url}")
        supported = ", ".join(SUPPORTED_MARKETPLACES.keys())
        raise ValueError(
            f"Unsupported marketplace: {url}. Supported domains: {supported}"
        )
    return parser_class(url, browser_page)
