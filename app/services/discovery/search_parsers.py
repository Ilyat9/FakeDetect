"""Discovery search parsers (Block C.2). See package docstring."""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from app.services.security import safe_get

logger = logging.getLogger(__name__)

WB_SEARCH_API = "https://search.wb.ru/exactmatch/ru/common/v5/search"

PRODUCT_LINK_RE = re.compile(
    r'href="(https?://(?:www\.)?(?:ozon\.ru|market\.yandex\.ru)/product/[^"#?]+)', re.IGNORECASE
)


async def search_marketplace(
    marketplace: str,
    keyword: str,
    limit: int,
    browser_page: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Dispatch a keyword search to the right marketplace parser."""
    marketplace = marketplace.strip().lower()
    if marketplace in ("wb", "wildberries"):
        return await search_wildberries(keyword, limit)
    if marketplace == "ozon":
        return await search_via_html(
            f"https://www.ozon.ru/search/?text={keyword}", "ozon.ru", limit, browser_page
        )
    if marketplace in ("yandex", "ym"):
        return await search_via_html(
            f"https://market.yandex.ru/search?text={keyword}",
            "market.yandex.ru", limit, browser_page,
        )
    logger.warning(f"Discovery: unsupported marketplace '{marketplace}', skipped")
    return []


async def search_wildberries(keyword: str, limit: int) -> List[Dict[str, Any]]:
    """WB public search API — returns catalog JSON without JS rendering."""
    url = (
        f"{WB_SEARCH_API}?appType=1&curr=rub&dest=-1257786"
        f"&query={keyword}&resultset=catalog&page=1&sort=popular"
    )
    try:
        response = await safe_get(url)
        if response.status_code != 200:
            logger.warning(f"WB search API returned {response.status_code} for '{keyword}'")
            return []
        data = response.json()
    except Exception as e:  # noqa: BLE001
        logger.error(f"WB search failed for '{keyword}': {e}")
        return []

    listings = []
    for product in (data.get("data") or {}).get("products", [])[: limit + 5]:
        sku = str(product.get("id") or "")
        if not sku or sku == "None":
            continue
        listings.append({
            "url": f"https://www.wildberries.ru/catalog/{sku}/detail.aspx",
            "sku": sku,
            "title": product.get("name"),
            "price": (product.get("salePriceU") or 0) / 100.0 or None,
            "seller": product.get("supplier") or product.get("brand"),
            "thumbnail_url": None,
        })
    return listings[:limit]


async def search_via_html(
    search_url: str,
    link_domain: str,
    limit: int,
    browser_page: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Generic HTML search-result parsing for JS-heavy marketplaces.

    Prefers a Playwright page; degrades gracefully to httpx (partial results).
    """
    html = None
    if browser_page is not None:
        try:
            await browser_page.goto(search_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)  # allow client-side rendering
            html = await browser_page.content()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Browser search failed ({search_url}): {e}; httpx fallback")
            html = None

    if not html:
        try:
            response = await safe_get(search_url)
            html = response.text if response.status_code == 200 else None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"httpx search fallback failed ({search_url}): {e}")

    if not html:
        return []

    seen: set = set()
    listings: List[Dict[str, Any]] = []
    for match in PRODUCT_LINK_RE.finditer(html):
        url = match.group(1).split("?")[0].rstrip("/")
        if url in seen or link_domain not in url:
            continue
        seen.add(url)
        sku = url.rstrip("/").rsplit("-", 1)[-1]
        listings.append({
            "url": url,
            "sku": sku or None,
            "title": None,
            "price": None,
            "seller": None,
            "thumbnail_url": None,
        })
        if len(listings) >= limit:
            break
    return listings
