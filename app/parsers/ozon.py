import re
import logging
import base64
import httpx
from PIL import Image
from io import BytesIO
from .base import MarketplaceParser, ParseResult

logger = logging.getLogger(__name__)


class OzonParser(MarketplaceParser):
    """Parser for Ozon marketplace."""

    @staticmethod
    async def _url_to_base64(url: str) -> str:
        """Convert image URL to base64."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, timeout=15.0)
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

    async def _parse_card_images(self, browser_page) -> list:
        """Parse card images from Ozon using Playwright."""
        images = []

        try:
            if not browser_page:
                logger.warning("Browser page not provided for card images")
                return images

            await browser_page.goto(self.url, wait_until='networkidle', timeout=15000)

            # Wait for gallery widget
            try:
                await browser_page.wait_for_selector('[data-widget="webGallery"]', timeout=10000)
            except:
                logger.warning("Gallery widget not found")

            # Collect main card images
            gallery_images = await browser_page.query_selector_all('[data-widget="webGallery"] img')
            for img in gallery_images[:15]:
                try:
                    img_url = await img.get_attribute('src')
                    if img_url:
                        b64 = await self._url_to_base64(img_url)
                        if b64:
                            images.append(b64)
                except Exception as e:
                    logger.warning(f"Error getting card image: {e}")

        except Exception as e:
            logger.error(f"Error parsing Ozon card images: {e}")

        return images

    async def _parse_review_images(self, browser_page) -> list:
        """Parse review images from Ozon using Playwright."""
        images = []

        try:
            if not browser_page:
                logger.warning("Browser page not provided for review images")
                return images

            await browser_page.goto(self.url, wait_until='networkidle', timeout=15000)

            # Find and scroll to reviews section
            try:
                reviews_section = await browser_page.query_selector('[data-widget="webReviews"]')
                if reviews_section:
                    await reviews_section.scroll_into_view_if_needed()

                # Scroll reviews to load more
                for i in range(3):
                    await browser_page.evaluate('window.scrollBy(0, 800)')
                    await browser_page.wait_for_timeout(1500)

                    # Click "Show more" if exists
                    try:
                        show_more = await browser_page.query_selector('button[data-slot="show-more-button"]')
                        if show_more:
                            await show_more.click()
                            await browser_page.wait_for_timeout(1000)
                    except:
                        pass

            except Exception as e:
                logger.warning(f"Could not parse review section: {e}")

            # Collect review images
            review_images = await browser_page.query_selector_all('[data-widget="webReviews"] img')
            for img in review_images[:15]:
                try:
                    img_url = await img.get_attribute('src')
                    if img_url:
                        b64 = await self._url_to_base64(img_url)
                        if b64:
                            images.append(b64)
                except Exception as e:
                    logger.warning(f"Error getting review image: {e}")

        except Exception as e:
            logger.error(f"Error in Ozon review parser: {e}")

        return images

    async def get_all_images(self) -> ParseResult:
        """Extract all images from Ozon URL."""
        result = ParseResult(marketplace=self.marketplace)

        try:
            # Parse card images
            result.card_images = await self._parse_card_images(self.browser_page)

            # Parse review images
            result.review_images = await self._parse_review_images(self.browser_page)

        except Exception as e:
            result.error = f"Error parsing Ozon images: {e}"
            logger.error(f"Error in Ozon parser: {e}")

        return result
