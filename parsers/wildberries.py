import re
import logging
import base64
import httpx
from PIL import Image
from io import BytesIO
from .base import MarketplaceParser, ParseResult

logger = logging.getLogger(__name__)


class WildberriesParser(MarketplaceParser):
    """Parser for Wildberries marketplace."""

    def __init__(self, url: str, browser_page=None):
        super().__init__(url, browser_page)
        self.api_url = "https://card.wb.ru/cards/v1/detail?appType=1&nm="

    def _extract_sku(self) -> str:
        """Extract SKU from WB URL."""
        match = re.search(r'/catalog/(\d+)/', self.url)
        return match.group(1) if match else ""

    async def _url_to_base64(self, url: str, client) -> str:
        """Convert image URL to base64."""
        try:
            response = await client.get(url, timeout=10.0)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                buffer = BytesIO()
                img.save(buffer, format='JPEG')
                return base64.b64encode(buffer.getvalue()).decode()
        except Exception as e:
            logger.warning(f"Error converting image {url} to base64: {e}")
        return None

    async def _parse_card_images(self, api_data: dict, client) -> list:
        """Parse card images from WB API using proper structure."""
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

            for i, file_name in enumerate(media_files[:15]):
                for nn in range(1, 21):
                    basket = f"{nn:02d}"
                    url = f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{article}/images/big/{file_name}.jpg"
                    b64 = await self._url_to_base64(url, client)
                    if b64:
                        images.append(b64)
                        break
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

        try:
            # Parse card images via API
            sku = self._extract_sku()
            if sku:
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
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
