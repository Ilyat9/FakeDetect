import re
import asyncio
import logging
import base64
import httpx
from PIL import Image
from io import BytesIO
from .base import MarketplaceParser, ParseResult

logger = logging.getLogger(__name__)

# Known WB CDN basket-server ranges by `vol` (article // 100000).
# WB changes this mapping occasionally — update this table in a single PR when it does.
WB_VOL_BASKET_RANGES = (
    (143, "01"), (287, "02"), (431, "03"), (719, "04"), (1007, "05"),
    (1061, "06"), (1115, "07"), (1163, "08"), (1199, "09"), (1239, "10"),
    (1263, "11"), (1291, "12"), (1319, "13"), (1335, "14"), (1347, "15"),
    (1359, "16"), (1371, "17"), (1387, "18"), (1399, "19"), (1411, "20"),
)
WB_FALLBACK_BASKET = "21"
WB_PROBE_BASKETS = tuple(f"{i:02d}" for i in range(1, 25))
MAX_CARD_IMAGES = 15

# In-process cache: vol -> basket number that worked last time.
_basket_cache: dict = {}


def basket_for_vol(vol: int) -> str:
    """Compute the WB basket server for a volume using the known range table."""
    for max_vol, basket in WB_VOL_BASKET_RANGES:
        if vol <= max_vol:
            return basket
    return WB_FALLBACK_BASKET


class WildberriesParser(MarketplaceParser):
    """Parser for Wildberries marketplace."""

    def __init__(self, url: str, browser_page=None):
        super().__init__(url, browser_page)
        self.api_url = "https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm="

    def _extract_sku(self) -> str:
        """Extract SKU from WB URL."""
        match = re.search(r'/catalog/(\d+)/', self.url)
        if not match:
            match = re.search(r'(\d{6,})', self.url)
        return match.group(1) if match else ""

    @staticmethod
    def _image_to_base64(content: bytes) -> str:
        img = Image.open(BytesIO(content))
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        buffer = BytesIO()
        img.save(buffer, format='JPEG')
        return base64.b64encode(buffer.getvalue()).decode()

    async def _url_to_base64(self, url: str, client) -> str:
        """Convert image URL to base64."""
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                return self._image_to_base64(response.content)
        except Exception as e:
            logger.warning(f"Error converting image {url} to base64: {e}")
        return None

    async def _fetch_image_with_basket(self, article: str, vol: int, part: int,
                                       file_name: str, client) -> str:
        """Fetch one product image trying the cached/known basket first,
        then probing remaining baskets in parallel with early exit."""
        known = _basket_cache.get(vol) or basket_for_vol(vol)

        def image_url(basket: str) -> str:
            return (f"https://basket-{basket}.wbbasket.ru/"
                    f"vol{vol}/part{part}/{article}/images/big/{file_name}.jpg")

        b64 = await self._url_to_base64(image_url(known), client)
        if b64:
            _basket_cache[vol] = known
            return b64

        # Probe the other baskets concurrently; first success wins.
        candidates = [b for b in WB_PROBE_BASKETS if b != known]

        async def probe(basket: str):
            return basket, await self._url_to_base64(image_url(basket), client)

        tasks = [asyncio.create_task(probe(b)) for b in candidates]
        try:
            for coro in asyncio.as_completed(tasks):
                basket, b64 = await coro
                if b64:
                    _basket_cache[vol] = basket
                    return b64
        finally:
            for t in tasks:
                t.cancel()

        return None

    async def _parse_card_images(self, api_data: dict, client) -> list:
        """Parse card images from WB API."""
        images = []

        try:
            products = api_data.get('data', {}).get('products', [])
            if not products:
                return images
            product = products[0]

            article = str(product.get('id', ''))
            vol = int(article) // 100000
            part = int(article) // 1000
            media_files = product.get('mediaFiles', [])

            for file_name in media_files[:MAX_CARD_IMAGES]:
                b64 = await self._fetch_image_with_basket(article, vol, part, file_name, client)
                if b64:
                    images.append(b64)
        except Exception as e:
            logger.error(f"Error parsing WB card images: {e}")

        return images

    async def _parse_review_images(self, browser_page) -> list:
        """Parse review images using Playwright."""
        images = []

        try:
            if not browser_page:
                logger.warning("Browser page not provided for review images")
                return images

            # Navigate to reviews
            await browser_page.goto(self.url, wait_until='networkidle', timeout=10000)

            # Try to find and click reviews tab
            try:
                # Wait for reviews tab to appear
                await browser_page.wait_for_selector('.tabs-section', timeout=5000)

                # Try to click reviews
                reviews_tab = await browser_page.query_selector('.tabs-section a[data-tab="reviews"]')
                if reviews_tab:
                    await reviews_tab.click()
                    await browser_page.wait_for_selector('.photosReviews__list', timeout=10000)

                # Scroll 5 times
                for _ in range(5):
                    await browser_page.evaluate('window.scrollBy(0, 500)')
                    await browser_page.wait_for_timeout(500)

                # Collect review images
                review_images = await browser_page.query_selector_all('.photosReviews__list img')
                for img in review_images[:15]:
                    try:
                        img_url = await img.get_attribute('src')
                        if img_url:
                            # Download and convert to base64
                            async with httpx.AsyncClient(timeout=10.0) as http_client:
                                response = await http_client.get(img_url, timeout=10.0)
                                if response.status_code == 200:
                                    pil_img = Image.open(BytesIO(response.content))
                                    if pil_img.mode in ('RGBA', 'LA', 'P'):
                                        pil_img = pil_img.convert('RGB')
                                    buffer = BytesIO()
                                    pil_img.save(buffer, format='JPEG')
                                    images.append(base64.b64encode(buffer.getvalue()).decode())
                    except Exception as e:
                        logger.warning(f"Error getting review image src: {e}")
            except Exception as e:
                logger.warning(f"Could not parse review images: {e}")

        except Exception as e:
            logger.error(f"Error in _parse_review_images: {e}")

        return images[:15]  # Limit to 15 images

    async def get_all_images(self) -> ParseResult:
        """Extract all images from WB URL."""
        result = ParseResult(marketplace=self.marketplace)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Origin": "https://www.wildberries.ru",
            "Referer": "https://www.wildberries.ru/",
        }

        try:
            # Parse card images via API
            sku = self._extract_sku()
            if sku:
                try:
                    async with httpx.AsyncClient(
                        timeout=15.0, headers=headers, follow_redirects=True
                    ) as client:
                        api_response = await client.get(f"{self.api_url}{sku}")
                        if api_response.status_code == 429:
                            retry_after = float(api_response.headers.get("retry-after", 2))
                            logger.warning(f"WB API rate-limited, retrying in {retry_after}s")
                            await asyncio.sleep(min(retry_after, 10))
                            api_response = await client.get(f"{self.api_url}{sku}")
                        if api_response.status_code == 200:
                            result.card_images = await self._parse_card_images(api_response.json(), client)

                except Exception as e:
                    logger.error(f"Error fetching WB API: {e}")

            # Parse review images
            result.review_images = await self._parse_review_images(self.browser_page)

        except Exception as e:
            result.error = f"Error parsing WB images: {e}"
            logger.error(f"Error in WB parser: {e}")

        return result
