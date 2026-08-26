import re
import logging
import base64
import httpx
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
from .base import MarketplaceParser, ParseResult

logger = logging.getLogger(__name__)


class YandexParser(MarketplaceParser):
    """Parser for Yandex Market."""

    async def _url_to_base64(self, url: str) -> str:
        """Convert image URL to base64."""
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=15.0)
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

    async def _parse_card_images(self, browser_page=None) -> list:
        """Parse card images using httpx + BeautifulSoup, fallback to Playwright."""
        images = []

        try:
            # Try httpx first
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    response = await client.get(self.url, headers=headers, timeout=15.0)
                    response.raise_for_status()

                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'lxml')

                        # Try to find images with data-baobab-name="image"
                        img_elements = soup.find_all('img', attrs={'data-baobab-name': 'image'})
                        for img in img_elements[:10]:
                            try:
                                src = img.get('src', '')
                                if src:
                                    # Make absolute URL
                                    if not src.startswith('http'):
                                        src = 'https:' + src
                                    b64 = await self._url_to_base64(src)
                                    if b64:
                                        images.append(b64)
                            except Exception as e:
                                logger.warning(f"Error parsing card image: {e}")

                        if images:
                            logger.info(f"Found {len(images)} images via httpx")
                            return images

            except Exception as e:
                logger.warning(f"httpx parsing failed, falling back to Playwright: {e}")

            # Fallback to Playwright
            if browser_page:
                try:
                    await browser_page.goto(self.url, wait_until='networkidle', timeout=15000)

                    # Wait for image element
                    try:
                        await browser_page.wait_for_selector('[data-baobab-name="image"]', timeout=10000)
                    except:
                        pass

                    # Collect images
                    img_elements = await browser_page.query_selector_all('[data-baobab-name="image"] img')
                    for img in img_elements[:15]:
                        try:
                            src = await img.get_attribute('src')
                            if src:
                                if not src.startswith('http'):
                                    src = 'https:' + src
                                b64 = await self._url_to_base64(src)
                                if b64:
                                    images.append(b64)
                        except Exception as e:
                            logger.warning(f"Error getting image from Playwright: {e}")
                except Exception as e:
                    logger.error(f"Error in Playwright fallback: {e}")

        except Exception as e:
            logger.error(f"Error in Yandex card parser: {e}")

        return images

    async def _parse_review_images(self, browser_page) -> list:
        """Parse review images from Yandex Market."""
        images = []

        try:
            if not browser_page:
                logger.warning("Browser page not provided for review images")
                return images

            # Navigate to reviews page
            reviews_url = self.url.replace('/catalog/', '/catalog/?reviewId=')
            await browser_page.goto(reviews_url, wait_until='networkidle', timeout=15000)

            # Scroll to load reviews
            for i in range(5):
                await browser_page.evaluate('window.scrollBy(0, 600)')
                await browser_page.wait_for_timeout(1000)

                # Click "Show more" if exists
                try:
                    show_more = await browser_page.query_selector('.Review-show-more-button, button[data-slot="show-more-button"]')
                    if show_more:
                        await show_more.click()
                        await browser_page.wait_for_timeout(800)
                except:
                    pass

            # Collect review images
            try:
                review_images = await browser_page.query_selector_all('.Review-photo img')
                for img in review_images[:15]:
                    try:
                        src = await img.get_attribute('src')
                        if src:
                            if not src.startswith('http'):
                                src = 'https:' + src
                            b64 = await self._url_to_base64(src)
                            if b64:
                                images.append(b64)
                    except Exception as e:
                        logger.warning(f"Error getting review image: {e}")
            except Exception as e:
                logger.warning(f"Could not find review images: {e}")

        except Exception as e:
            logger.error(f"Error in Yandex review parser: {e}")

        return images

    async def get_all_images(self) -> ParseResult:
        """Extract all images from Yandex Market URL."""
        result = ParseResult(marketplace=self.marketplace)

        try:
            # Parse card images
            result.card_images = await self._parse_card_images(self.browser_page)

            # Parse review images
            result.review_images = await self._parse_review_images(self.browser_page)

        except Exception as e:
            result.error = f"Error parsing Yandex images: {e}"
            logger.error(f"Error in Yandex parser: {e}")

        return result
