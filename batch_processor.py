import asyncio
import argparse
import base64
import io
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncGenerator
from dataclasses import dataclass, asdict
import sys

import httpx

try:
    import playwright.async_api
    from playwright_stealth import stealth_async
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright not installed. Using httpx fallback.")

from llm_provider import create_provider

from database import is_whitelisted

@dataclass
class BrowserSettings:
    headless: bool = True
    enable_stealth: bool = True
    slow_mo: int = 0
    page_load_timeout: int = 60000
    action_timeout: int = 20000
    user_data_dir: str = "./browser_data"


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
        try:
            self.playwright = await playwright.async_api.async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.settings.headless,
                slow_mo=self.settings.slow_mo,
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self.page = await self.context.new_page()

            # Apply stealth patches if available
            if PLAYWRIGHT_AVAILABLE and self.settings.enable_stealth:
                await stealth_async(self.page)

            self.page.set_default_timeout(self.settings.action_timeout)
            self.page.set_default_navigation_timeout(self.settings.page_load_timeout)

        except Exception as e:
            raise RuntimeError(f"Failed to launch browser: {e}")

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
            print(f"Warning during browser cleanup: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    async def navigate(self, url: str):
        """Navigate to URL."""
        url = url.strip()

        # Ensure HTTP/HTTPS
        if not (url.lower().startswith('http://') or url.lower().startswith('https://')):
            url = f'https://{url}'

        await self.page.goto(url, wait_until="domcontentloaded")
        await self.page.wait_for_load_state("networkidle", timeout=10000)

    async def take_screenshot(self) -> bytes:
        """Take screenshot and return bytes directly."""
        return await self.page.screenshot(full_page=False)


@dataclass
class BatchResult:
    row_index: int
    url: str
    brand: str
    verdict: str
    confidence: float
    risk_level: str
    summary: str
    checked_at: str
    result_icon: str


class BatchProcessor:
    def __init__(self, reference_image_path: str, provider_name: str, provider_api_key: str):
        self.reference_image_path = reference_image_path
        self.provider_name = provider_name
        self.provider_api_key = provider_api_key
        self.provider = None

    def _load_reference_image(self) -> bytes:
        with open(self.reference_image_path, 'rb') as f:
            return f.read()

    async def _fetch_screenshot_with_browser(self, url: str) -> Optional[bytes]:
        """Fetch screenshot using minimal browser service."""
        if not PLAYWRIGHT_AVAILABLE:
            print("Playwright not available. Using httpx fallback.")
            return await self._fetch_screenshot_with_httpx(url)

        try:
            settings = BrowserSettings()
            async with MinimalBrowserService(settings) as browser:
                await browser.navigate(url)
                await asyncio.sleep(2)  # wait for JS to load
                return await browser.take_screenshot()

        except Exception as e:
            print(f"Browser error for {url}: {e}")
            return await self._fetch_screenshot_with_httpx(url)

    async def _fetch_screenshot_with_httpx(self, url: str) -> Optional[bytes]:
        """Fallback to httpx for screenshot fetching."""
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = await client.get(url, headers=headers, timeout=10.0)

                import re
                img_match = re.search(r'<img[^>]+src=["\']([^"\']+\.jpg[^"\']*)["\']', response.text, re.IGNORECASE)
                if img_match:
                    img_url = img_match.group(1)
                    if not img_url.startswith('http'):
                        img_url = f"https:{img_url}" if img_url.startswith('//') else img_url

                    img_response = await client.get(img_url, timeout=10.0)
                    return img_response.content

        except Exception as e:
            print(f"httpx error for {url}: {e}")
        return None

    async def process_row(self, row: Dict[str, Any], reference_bytes: bytes, row_index: int) -> Optional[BatchResult]:
        """Process a single row from Excel"""

        url = row.get('url', '')
        brand = row.get('brand', '')
        marketplace = row.get('marketplace', '')
        price_orig = row.get('price_original', 0)
        price_sus = row.get('price_suspect', 0)

        if not url:
            return None

        meta = {
            'brand': brand,
            'marketplace': marketplace,
            'price_original': price_orig,
            'price_suspect': price_sus
        }

        try:
            print(f"[{row_index}] {brand or 'No brand'} - navigating to {url}")

            if not self.provider:
                self.provider = create_provider(self.provider_name, self.provider_api_key)

            suspect_bytes = await self._fetch_screenshot_with_browser(url)

            if not suspect_bytes:
                print(f"[{row_index}] Failed to fetch image for {url}")
                return BatchResult(
                    row_index=row_index,
                    url=url,
                    brand=brand,
                    verdict="—",
                    confidence=0,
                    risk_level="unknown",
                    summary="Не удалось загрузить изображение",
                    checked_at=datetime.now().isoformat(),
                    result_icon="⚠️"
                )

            print(f"[{row_index}] {brand or 'No brand'} — analyzing...")

            result = await self.provider.analyze(reference_bytes, suspect_bytes, meta)

            verdict = result.get('verdict', '?')
            confidence = result.get('confidence', 0)
            risk_level = result.get('risk_level', 'unknown')
            summary = result.get('summary', '')

            # Check whitelist
            seller = row.get('seller', '')
            if seller and await is_whitelisted(seller, brand, marketplace):
                # Override verdict for whitelisted sellers
                verdict = 'ОРИГИНАЛ'
                confidence = 95
                summary = f'Продавец "{seller}" находится в белом списке авторизованных продавцов бренда {brand}.'
                risk_level = 'low'
                icon = '✅'
                print(f"[{row_index}] {brand or 'No brand'} — WHITELISTED (seller: {seller})")
            else:
                icon = "✅" if verdict == "ОРИГИНАЛ" else "❌" if verdict == "ПОДДЕЛКА" else "⚠️"
                print(f"[{row_index}] {brand or 'No brand'} — {verdict} ({confidence}%)")

            return BatchResult(
                row_index=row_index,
                url=url,
                brand=brand,
                verdict=verdict,
                confidence=confidence,
                risk_level=risk_level,
                summary=summary,
                checked_at=datetime.now().isoformat(),
                result_icon=icon
            )

        except Exception as e:
            print(f"[{row_index}] Error processing {url}: {e}")
            return BatchResult(
                row_index=row_index,
                url=url,
                brand=brand,
                verdict="Ошибка",
                confidence=0,
                risk_level="unknown",
                summary=str(e),
                checked_at=datetime.now().isoformat(),
                result_icon="❌"
            )

    async def process_batch(self, df: 'pd.DataFrame') -> List[BatchResult]:
        """Process all rows concurrently with semaphore"""
        reference_bytes = self._load_reference_image()

        semaphore = asyncio.Semaphore(3)
        tasks = []

        for idx, row in df.iterrows():
            async def process_with_semaphore(idx=idx, row=row):
                async with semaphore:
                    return await self.process_row(row, reference_bytes, idx)

            tasks.append(process_with_semaphore())

        results = await asyncio.gather(*tasks)

        return [r for r in results if r is not None]

    async def stream_results(
        self,
        urls: List[str],
        brand: str = "",
        marketplace: str = ""
    ) -> AsyncGenerator[BatchResult, None]:
        """
        Async generator that yields results one by one as they complete.
        Use this for large lists where you want to stream progress to the client.

        Usage:
            async for result in processor.stream_results(urls):
                print(result.verdict)
        """
        reference_bytes = self._load_reference_image()
        semaphore = asyncio.Semaphore(3)

        async def process_one(idx: int, url: str):
            row = {"url": url, "brand": brand, "marketplace": marketplace}
            async with semaphore:
                return await self.process_row(row, reference_bytes, idx)

        tasks = [process_one(i, url) for i, url in enumerate(urls)]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                yield result


def process_excel(file_path: str, reference_image_path: str, provider_name: str = 'gemini'):
    import pandas as pd

    df = pd.read_excel(file_path)

    if 'url' not in df.columns:
        print("Error: 'url' column not found in Excel file")
        return

    processor = BatchProcessor(reference_image_path, provider_name, "")

    results = asyncio.run(processor.process_batch(df))

    results_df = pd.DataFrame([asdict(r) for r in results])

    output_df = pd.concat([df, results_df], axis=1)

    output_df.to_excel(file_path, index=False)

    print(f"\n✓ Processed {len(results)} rows")
    print(f"✓ Saved to {file_path}")


def main():
    parser = argparse.ArgumentParser(description="Batch product analyzer")
    parser.add_argument('--file', required=True, help='Input Excel file')
    parser.add_argument('--reference', required=True, help='Reference/original image path')
    parser.add_argument('--provider', default='gemini', choices=['gemini', 'grok'], help='LLM provider')

    args = parser.parse_args()

    if not PLAYWRIGHT_AVAILABLE:
        print("Warning: Playwright not available. Falling back to httpx.")

    process_excel(args.file, args.reference, args.provider)


if __name__ == '__main__':
    main()
