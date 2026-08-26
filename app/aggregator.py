import asyncio
import logging
import base64
from PIL import Image
from io import BytesIO
from typing import List, Dict, Any
from dataclasses import dataclass, field

from app.llm_provider import create_provider

logger = logging.getLogger(__name__)


@dataclass
class ImageAnalysisResult:
    """Result of analyzing a single image."""
    image_type: str  # 'card' or 'review'
    index: int
    verdict: str
    confidence: int
    summary: str
    risk_level: str
    indicators: List[Dict[str, Any]]


@dataclass
class AggregatedResult:
    """Aggregated analysis result."""
    final_verdict: str
    final_confidence: int
    final_risk_level: str
    card_results: List[ImageAnalysisResult]
    review_results: List[ImageAnalysisResult]
    red_flags: List[str]
    summary: str
    total_images: int
    suspicious_count: int


SUSPICIOUS_RATIO_THRESHOLD = 0.30   # >30% suspicious images -> overall 'ПОДОЗРИТЕЛЬНО'
FAKE_IN_REVIEWS_CONFIDENCE = 90     # any fake found in customer reviews is a strong signal


class ImageAggregator:
    """Aggregates image analysis from multiple sources."""

    def __init__(self, provider_name: str = "gemini", api_key: str = ""):
        self.provider_name = provider_name
        self.api_key = api_key
        self.provider = None

    async def analyze_all(
        self,
        parse_result,
        reference_bytes: bytes,
        meta: Dict[str, Any]
    ) -> AggregatedResult:
        """
        Analyze all images from the parse result.

        Args:
            parse_result: ParseResult from parser
            reference_bytes: Reference image (original product)
            meta: Additional metadata (brand, marketplace, etc.)

        Returns:
            AggregatedResult with analysis results
        """
        all_results = []
        semaphore = asyncio.Semaphore(3)

        # Lazy provider creation
        if not self.provider:
            self.provider = create_provider(self.provider_name, self.api_key)

        async def analyze_single(image_bytes: bytes, image_type: str, index: int):
            """Analyze a single image with rate limiting."""
            async with semaphore:
                try:
                    # Block A.4: strict validation + single corrective retry.
                    from app.core.llm_gateway import validated_provider_call

                    result_obj = await validated_provider_call(
                        self.provider,
                        reference_bytes,
                        image_bytes,
                        meta,
                        provider_label=f"{image_type}#{index}",
                    )
                    data = result_obj.model_dump()
                    return ImageAnalysisResult(
                        image_type=image_type,
                        index=index,
                        verdict=data.get('verdict', 'UNKNOWN'),
                        confidence=data.get('confidence', 0),
                        summary=data.get('summary', ''),
                        risk_level=data.get('risk_level', 'low'),
                        indicators=data.get('indicators', [])
                    )
                except Exception as e:
                    logger.error(f"Error analyzing image {index} ({image_type}): {e}")
                    return ImageAnalysisResult(
                        image_type=image_type,
                        index=index,
                        verdict='UNKNOWN',
                        confidence=0,
                        summary=f'Error: {str(e)}',
                        risk_level='low',
                        indicators=[]
                    )


        # Analyze card images
        tasks = []
        for idx, card_img in enumerate(parse_result.card_images):
            try:
                # Decode base64
                img_bytes = base64.b64decode(card_img)
                # Convert to RGB
                img = Image.open(BytesIO(img_bytes))
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                img_buffer = BytesIO()
                img.save(img_buffer, format='JPEG')
                img_bytes = img_buffer.getvalue()

                tasks.append(analyze_single(img_bytes, 'card', idx))
            except Exception as e:
                logger.warning(f"Error preparing card image {idx}: {e}")

        # Analyze review images
        for idx, review_img in enumerate(parse_result.review_images):
            try:
                # Decode base64
                img_bytes = base64.b64decode(review_img)
                # Convert to RGB
                img = Image.open(BytesIO(img_bytes))
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                img_buffer = BytesIO()
                img.save(img_buffer, format='JPEG')
                img_bytes = img_buffer.getvalue()

                tasks.append(analyze_single(img_bytes, 'review', idx))
            except Exception as e:
                logger.warning(f"Error preparing review image {idx}: {e}")

        # Run all analyses
        logger.info(f"Analyzing {len(tasks)} images...")
        analysis_results = await asyncio.gather(*tasks)

        # Filter out UNKNOWN verdicts
        valid_results = [r for r in analysis_results if r.verdict != 'UNKNOWN']
        logger.info(f"Valid results: {len(valid_results)}")

        # Categorize results
        card_results = [r for r in valid_results if r.image_type == 'card']
        review_results = [r for r in valid_results if r.image_type == 'review']

        # Determine final verdict
        final_verdict, final_confidence, final_risk_level, summary = self._determine_verdict(
            card_results,
            review_results
        )

        # Count suspicious images
        suspicious_count = sum(1 for r in valid_results if r.verdict in ('ПОДДЕЛКА', 'ПОДОЗРИТЕЛЬНО'))

        # Build red flags
        red_flags = self._build_red_flags(card_results, review_results)

        return AggregatedResult(
            final_verdict=final_verdict,
            final_confidence=final_confidence,
            final_risk_level=final_risk_level,
            card_results=card_results,
            review_results=review_results,
            red_flags=red_flags,
            summary=summary,
            total_images=len(tasks),
            suspicious_count=suspicious_count
        )

    def _determine_verdict(
        self,
        card_results: List[ImageAnalysisResult],
        review_results: List[ImageAnalysisResult]
    ) -> tuple:
        """
        Determine final verdict based on all results.

        Rules:
        - Any 'ПОДДЕЛКА' in reviews → 'ПОДДЕЛКА'
        - >30% 'ПОДОЗРИТЕЛЬНО' → 'ПОДОЗРИТЕЛЬНО'
        - All 'ОРИГИНАЛ' → 'ОРИГИНАЛ'
        """
        all_results = card_results + review_results
        total = len(all_results)

        if total == 0:
            return 'UNKNOWN', 0, 'low', 'No valid images to analyze'

        # Count verdicts
        fakes = sum(1 for r in all_results if r.verdict == 'ПОДДЕЛКА')
        suspicious = sum(1 for r in all_results if r.verdict == 'ПОДОЗРИТЕЛЬНО')
        originals = sum(1 for r in all_results if r.verdict == 'ОРИГИНАЛ')

        # Calculate average confidence
        avg_confidence = int(sum(r.confidence for r in all_results) / total)

        # Rule 1: Any fake in reviews → Fake
        fake_reviews = [r for r in review_results if r.verdict == 'ПОДДЕЛКА']
        if fake_reviews:
            return ('ПОДДЕЛКА', FAKE_IN_REVIEWS_CONFIDENCE, 'high',
                    f'Found {len(fake_reviews)} fake product(s) in reviews')

        # Rule 2: >SUSPICIOUS_RATIO_THRESHOLD suspicious → Suspicious
        suspicious_ratio = suspicious / total
        if suspicious_ratio > SUSPICIOUS_RATIO_THRESHOLD:
            return 'ПОДОЗРИТЕЛЬНО', avg_confidence, 'medium', \
                   f'{suspicious} out of {total} images ({suspicious_ratio*100:.0f}%) are suspicious'

        # Rule 3: All originals → Original
        if originals == total:
            return 'ОРИГИНАЛ', avg_confidence, 'low', f'All {total} images are original'

        # Default: mix of originals and suspicious
        if fakes > 0:
            return 'ПОДДЕЛКА', avg_confidence, 'high', \
                   f'Found {fakes} fake product(s) out of {total}'
        else:
            return 'ПОДОЗРИТЕЛЬНО', avg_confidence, 'medium', \
                   f'{suspicious} out of {total} images are suspicious'

    def _build_red_flags(
        self,
        card_results: List[ImageAnalysisResult],
        review_results: List[ImageAnalysisResult]
    ) -> List[str]:
        """Build list of red flags based on analysis."""
        red_flags = []

        # Check card images for red flags
        for result in card_results:
            if result.verdict == 'ПОДДЕЛКА':
                red_flags.append(f"Карточка #{result.index}: {result.summary}")

        # Check review images for red flags
        for result in review_results:
            if result.verdict == 'ПОДДЕЛКА':
                red_flags.append(f"Отзыв #{result.index}: {result.summary}")
            elif result.verdict == 'ПОДОЗРИТЕЛЬНО':
                red_flags.append(f"Отзыв #{result.index}: {result.summary}")

        return red_flags
