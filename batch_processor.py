import asyncio
import argparse
import base64
import io
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, AsyncGenerator
from dataclasses import dataclass, asdict
import sys

import httpx
import pandas as pd

try:
    import playwright.async_api  # noqa: F401
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Warning: Playwright not installed. Using httpx fallback.")

from services.browser_service import (
    PLAYWRIGHT_AVAILABLE as BROWSER_AVAILABLE,
    BrowserSettings,
    MinimalBrowserService,
)
from llm_provider import create_provider

from database import is_whitelisted

logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        provider_name: str,
        provider_api_key: str,
        reference_image_path: Optional[str] = None,
        reference_image_bytes: Optional[bytes] = None,
    ):
        """
        Args:
            provider_name: 'gemini' or 'grok'
            provider_api_key: LLM API key
            reference_image_path: path to reference image (CLI mode)
            reference_image_bytes: reference image content in memory (web mode);
                preferred — avoids shared temp files and race conditions.
        """
        self.provider_name = provider_name
        self.provider_api_key = provider_api_key
        self.reference_image_path = reference_image_path
        self.reference_image_bytes = reference_image_bytes
        self.provider = None

    def _load_reference_image(self) -> bytes:
        if self.reference_image_bytes is not None:
            return self.reference_image_bytes
        if not self.reference_image_path:
            raise ValueError("Either reference_image_path or reference_image_bytes is required")
        with open(self.reference_image_path, 'rb') as f:
            return f.read()

    async def _fetch_screenshot_with_browser(self, url: str) -> Optional[bytes]:
        """Fetch screenshot using minimal browser service."""
        if not BROWSER_AVAILABLE:
            logger.info("Playwright not available. Using httpx fallback.")
            return await self._fetch_screenshot_with_httpx(url)

        try:
            settings = BrowserSettings()
            async with MinimalBrowserService(settings) as browser:
                await browser.navigate(url)
                await asyncio.sleep(2)  # wait for JS to load
                return await browser.take_screenshot()

        except Exception as e:
            logger.warning(f"Browser error for {url}: {e}")
            return await self._fetch_screenshot_with_httpx(url)

    async def _fetch_suspect_image(self, url: str) -> Optional[bytes]:
        """Fetch the actual product image (1.9).

        Prefers real product card photos extracted from the marketplace page
        (og:image / direct CDN links) over a full-page screenshot, which gives
        the LLM irrelevant context (site header, ads, footer).
        Falls back to the browser screenshot when extraction fails.
        """
        try:
            from services.marketplace_image_fetcher import parse_marketplace_image
            data = await parse_marketplace_image(url)
            return base64.b64decode(data["image_base64"])
        except Exception as e:
            logger.info(f"Direct product image fetch failed for {url} ({e}); falling back to screenshot")
            return await self._fetch_screenshot_with_browser(url)

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
            logger.warning(f"httpx error for {url}: {e}")
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
            logger.info(f"[{row_index}] {brand or 'No brand'} - fetching product image from {url}")

            if not self.provider:
                self.provider = create_provider(self.provider_name, self.provider_api_key)

            suspect_bytes = await self._fetch_suspect_image(url)

            if not suspect_bytes:
                logger.warning(f"[{row_index}] Failed to fetch image for {url}")
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

            logger.info(f"[{row_index}] {brand or 'No brand'} — analyzing...")

            # Block A.4: strict validation of every LLM answer (+1 corrective retry).
            from core.llm_gateway import validated_provider_call

            result = (await validated_provider_call(
                self.provider,
                reference_bytes,
                suspect_bytes,
                meta,
                provider_label=f"batch[{row_index}]",
            )).model_dump()

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
                logger.info(f"[{row_index}] {brand or 'No brand'} — WHITELISTED (seller: {seller})")
            else:
                icon = "✅" if verdict == "ОРИГИНАЛ" else "❌" if verdict == "ПОДДЕЛКА" else "⚠️"
                logger.info(f"[{row_index}] {brand or 'No brand'} — {verdict} ({confidence}%)")

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
            logger.exception(f"[{row_index}] Error processing {url}: {e}")
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
        logger.error("Error: 'url' column not found in Excel file")
        return

    processor = BatchProcessor(
        provider_name=provider_name,
        provider_api_key="",
        reference_image_path=reference_image_path,
    )

    results = asyncio.run(processor.process_batch(df))

    results_df = pd.DataFrame([asdict(r) for r in results])

    output_df = pd.concat([df, results_df], axis=1)

    output_df.to_excel(file_path, index=False)

    logger.info(f"✓ Processed {len(results)} rows, saved to {file_path}")


def main():
    parser = argparse.ArgumentParser(description="Batch product analyzer")
    parser.add_argument('--file', required=True, help='Input Excel file')
    parser.add_argument('--reference', required=True, help='Reference/original image path')
    parser.add_argument('--provider', default='gemini', choices=['gemini', 'grok'], help='LLM provider')

    args = parser.parse_args()

    if not BROWSER_AVAILABLE:
        logger.warning("Playwright not available. Falling back to httpx.")

    process_excel(args.file, args.reference, args.provider)


if __name__ == '__main__':
    main()
