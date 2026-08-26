"""Shared headless-browser service based on Playwright.

Used by both the batch processor (screenshots) and /analyze-deep
(parsing Ozon/Yandex/WB reviews that require JS rendering).
"""

import asyncio
import logging

try:
    import playwright.async_api
    from playwright_stealth import stealth_async
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class BrowserSettings:
    def __init__(
        self,
        headless: bool = True,
        enable_stealth: bool = True,
        slow_mo: int = 0,
        page_load_timeout: int = 60000,
        action_timeout: int = 20000,
    ):
        self.headless = headless
        self.enable_stealth = enable_stealth
        self.slow_mo = slow_mo
        self.page_load_timeout = page_load_timeout
        self.action_timeout = action_timeout


class MinimalBrowserService:
    """Minimal browser service with essential screenshot capabilities."""

    def __init__(self, settings: BrowserSettings):
        self.settings = settings
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Launch browser with stealth mode."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright playwright-stealth "
                "&& playwright install chromium"
            )
        try:
            self.playwright = await playwright.async_api.async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.settings.headless,
                slow_mo=self.settings.slow_mo,
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=BROWSER_USER_AGENT,
            )
            self.page = await self.context.new_page()

            if self.settings.enable_stealth:
                await stealth_async(self.page)

            self.page.set_default_timeout(self.settings.action_timeout)
            self.page.set_default_navigation_timeout(self.settings.page_load_timeout)

        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            raise RuntimeError(f"Failed to launch browser: {e}") from e

    async def close(self):
        """Gracefully shutdown browser."""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Warning during browser cleanup: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    async def navigate(self, url: str):
        """Navigate to URL."""
        url = url.strip()
        if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
            url = f"https://{url}"

        await self.page.goto(url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # networkidle is best-effort; don't fail navigation on it

    async def take_screenshot(self, full_page: bool = False) -> bytes:
        """Take screenshot and return bytes directly."""
        return await self.page.screenshot(full_page=full_page)
