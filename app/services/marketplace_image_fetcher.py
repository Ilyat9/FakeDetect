"""Unified marketplace image fetching.

Replaces the duplicated ``parse_gemini``/``parse_grok`` functions: plain HTML
scraping of direct image links / og:image has nothing to do with the LLM vendor.
"""

import base64
import logging
import re

import httpx

from app.services.security import safe_get, UnsafeURLError

logger = logging.getLogger(__name__)

IMAGE_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif)(\?.*)?$", re.IGNORECASE)
WB_CDN_RE = re.compile(r"wbbasket\.ru|wbstatic\.net", re.IGNORECASE)
OZON_CDN_RE = re.compile(r"static\.ozon|ozonusercontent\.com", re.IGNORECASE)

OG_IMAGE_META_RE = re.compile(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
OG_IMAGE_JSON_RE = re.compile(r'og:image["\']?\s*:\s*["\']([^"\']+)')

FIRST_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+\.jpe?g[^"\']*)["\']', re.IGNORECASE)


def _absolute(url: str) -> str:
    if url.startswith("//"):
        return f"https:{url}"
    return url


async def _download_as_base64(url: str, referer: str = "") -> dict:
    headers = {}
    if referer:
        headers["Referer"] = referer
    response = await safe_get(url, headers=headers)
    if response.status_code != 200:
        raise httpx.HTTPError(f"HTTP {response.status_code} for {url}")
    content_type = response.headers.get("content-type", "image/jpeg")
    return {
        "image_base64": base64.b64encode(response.content).decode(),
        "content_type": content_type,
    }


async def parse_marketplace_image(url: str) -> dict:
    """Extract a product image (as base64) from a marketplace/product/direct image URL.

    Raises HTTPException-free exceptions: ValueError for unsafe URLs and
    LookupError when no image could be extracted.
    """
    url = url.strip()

    # 1) Direct image link — just download it.
    if IMAGE_EXT_RE.search(url) or WB_CDN_RE.search(url) or OZON_CDN_RE.search(url):
        try:
            return await _download_as_base64(url)
        except (httpx.HTTPError, UnsafeURLError) as e:
            logger.warning(f"Failed to download direct image from {url}: {e}")
            raise LookupError("Could not fetch image from URL") from e

    html = None
    try:
        response = await safe_get(url)
        if response.status_code == 200:
            html = response.text
    except (httpx.HTTPError, UnsafeURLError) as e:
        logger.warning(f"Failed to fetch page {url}: {e}")

    if html:
        # 2) Try og:image meta tag first (works for WB/Ozon/Yandex).
        match = OG_IMAGE_META_RE.search(html) or OG_IMAGE_JSON_RE.search(html)
        if match:
            img_url = _absolute(match.group(1))
            try:
                return await _download_as_base64(img_url, referer=url)
            except (httpx.HTTPError, UnsafeURLError) as e:
                logger.warning(f"og:image download failed ({img_url}): {e}")

        # 3) Fallback: first <img src="...jpg"> on the page.
        match = FIRST_IMG_RE.search(html)
        if match:
            img_url = _absolute(match.group(1))
            try:
                return await _download_as_base64(img_url, referer=url)
            except (httpx.HTTPError, UnsafeURLError) as e:
                logger.warning(f"Fallback image download failed ({img_url}): {e}")

    raise LookupError("Could not extract image from URL")


# Backwards-compatible alias used by the batch processor.
fetch_product_image = parse_marketplace_image
