import json
import re
import base64
from abc import ABC, abstractmethod
from typing import Dict, Any
from enum import Enum

class ProviderType(str, Enum):
    GEMINI = "gemini"
    GROK = "grok"


# Block A.8: every verdict stored in DB references the exact prompt version
# used to produce it (see also prompt_hash computed by core/llm_gateway).
PROMPT_VERSION = "2026-08-blockA-v1"


def build_analysis_prompt(meta: Dict[str, Any]) -> str:
    """Single source of truth for the vision-analysis prompt."""
    brand = meta.get('brand', 'не указан')
    marketplace = meta.get('marketplace', 'не указан')
    price_orig = meta.get('price_original', 0)
    price_sus = meta.get('price_suspect', 0)

    price_info = ""
    if price_orig > 0 and price_sus > 0:
        ratio = price_sus / price_orig * 100
        price_info = f"\nЦена оригинала: {price_orig}₽, подозрительного: {price_sus}₽ ({ratio:.0f}% от оригинала)."

    correction = meta.get("_correction")
    correction_block = ""
    if isinstance(correction, dict) and correction.get("previous_output"):
        correction_block = (
            f"\nВНИМАНИЕ: твой предыдущий ответ был невалидным:\n{correction['previous_output']}\n"
            f"{correction.get('instruction', '')}\n"
        )

    return f"""{correction_block}Ты эксперт по выявлению контрафактных товаров на маркетплейсах.
Бренд/товар: {brand}.
Маркетплейс: {marketplace}.{price_info}

Первое изображение — ОРИГИНАЛ (эталон).
Второе изображение — ТОВАР С МАРКЕТПЛЕЙСА (для проверки).

Проведи детальное визуальное сравнение и выяви признаки подделки.

ВЕРДИКТ ПО ДОВЕРИЮ (confidence):
- 80-100%: ОРИГИНАЛ
- 50-79%: ПОДОЗРИТЕЛЬНО
- 0-49%: ПОДДЕЛКА

Важно: использование стокового фото само по себе НЕ делает товар подделкой — это лишь повод для проверки. Если в карточке нет живых фото, это не является признаком подделки (таких товаров большинство на маркетплейсах).

Верни ТОЛЬКО валидный JSON (без markdown блоков) строго в таком формате:
{{
  "verdict": "ОРИГИНАЛ" или "ПОДДЕЛКА" или "ПОДОЗРИТЕЛЬНО",
  "confidence": число от 0 до 100,
  "summary": "краткий вывод в 1-2 предложения",
  "risk_level": "low" или "medium" или "high",
  "indicators": [
    {{
      "factor": "название признака",
      "score": число от 1 до 10,
      "status": "ok" или "warn" или "fail",
      "detail": "пояснение"
    }},
    ...
  ],
  "recommendation": "рекомендация для бизнеса"
}}

Анализируй: логотип, шрифты, качество печати, цвета, упаковку, швы/отделку, пропорции, артикулы, штрих-коды (если видны), общее качество изображения.
Минимум 5 показателей в indicators.
Оцени каждый признак по шкале 1-10: 10=полное совпадение, 1=сильное отличие.
Доверие (confidence) — интегральная оценка совпадения изображения с оригиналом."""


class VisionProvider(ABC):
    @abstractmethod
    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        pass

    async def ping(self) -> bool:
        """Cheap liveness probe for /health (Block A.5)."""
        raise NotImplementedError


class GeminiProvider(VisionProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        self.client = genai.GenerativeModel(
            "gemini-2.5-flash",
            generation_config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
        )

    async def ping(self) -> bool:
        """Cheap REST liveness probe (model list), no tokens consumed."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    params={"key": self.api_key},
                )
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False


    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        from PIL import Image
        import io

        orig_img = Image.open(io.BytesIO(original_bytes))
        if orig_img.mode in ('RGBA', 'LA', 'P'):
            orig_img = orig_img.convert('RGB')
        sus_img = Image.open(io.BytesIO(suspect_bytes))
        if sus_img.mode in ('RGBA', 'LA', 'P'):
            sus_img = sus_img.convert('RGB')

        response = await self.client.generate_content_async(
            [build_analysis_prompt(meta), orig_img, sus_img]
        )

        raw = response.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        result = json.loads(raw)
        usage = getattr(response, "usage_metadata", None)
        total = getattr(usage, "total_token_count", None) if usage else None
        if total:
            result["_usage"] = {"total_tokens": int(total)}
        return result


class GrokProvider(VisionProvider):
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI

        self.api_key = api_key
        self.client = AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=api_key
        )
        self.model = "grok-2-vision-1212"

    async def ping(self) -> bool:
        """Cheap REST liveness probe (model list), no tokens consumed."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.x.ai/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        from PIL import Image
        import io

        orig_img = Image.open(io.BytesIO(original_bytes))
        if orig_img.mode in ('RGBA', 'LA', 'P'):
            orig_img = orig_img.convert('RGB')
        sus_img = Image.open(io.BytesIO(suspect_bytes))
        if sus_img.mode in ('RGBA', 'LA', 'P'):
            sus_img = sus_img.convert('RGB')

        prompt = build_analysis_prompt(meta)

        base64_orig = self._image_to_base64(orig_img)
        base64_sus = self._image_to_base64(sus_img)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_orig}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_sus}"}}
                ]}
            ]
        )

        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        result = json.loads(raw)
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None) if usage else None
        if total:
            result["_usage"] = {"total_tokens": int(total)}
        return result


    def _image_to_base64(self, image):
        import io
        buffer = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        image.save(buffer, format="JPEG")
        return base64.b64encode(buffer.getvalue()).decode()

def create_provider(provider_name: str, api_key: str) -> VisionProvider:
    provider_type = ProviderType(provider_name.lower())
    if provider_type == ProviderType.GROK:
        return GrokProvider(api_key)
    else:
        return GeminiProvider(api_key)
