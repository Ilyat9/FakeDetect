import json
import re
import base64
from abc import ABC, abstractmethod
from typing import Dict, Any
from enum import Enum

class ProviderType(str, Enum):
    GEMINI = "gemini"
    GROK = "grok"

class VisionProvider(ABC):
    @abstractmethod
    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        pass

class GeminiProvider(VisionProvider):
    def __init__(self, api_key: str):
        import google.generativeai as genai
        genai.configure(api_key=api_key)

        self.client = genai.GenerativeModel(
            "gemini-2.5-flash",
            generation_config={
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }
        )

    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        from PIL import Image
        import io

        orig_img = Image.open(io.BytesIO(original_bytes))
        if orig_img.mode in ('RGBA', 'LA', 'P'):
            orig_img = orig_img.convert('RGB')
        sus_img = Image.open(io.BytesIO(suspect_bytes))
        if sus_img.mode in ('RGBA', 'LA', 'P'):
            sus_img = sus_img.convert('RGB')

        brand = meta.get('brand', 'не указан')
        marketplace = meta.get('marketplace', 'не указан')
        price_orig = meta.get('price_original', 0)
        price_sus = meta.get('price_suspect', 0)

        price_info = ""
        if price_orig > 0 and price_sus > 0:
            ratio = price_sus / price_orig * 100
            price_info = f"\nЦена оригинала: {price_orig}₽, подозрительного: {price_sus}₽ ({ratio:.0f}% от оригинала)."

        prompt = f"""Ты эксперт по выявлению контрафактных товаров на маркетплейсах.
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

        response = await self.client.generate_content_async([prompt, orig_img, sus_img])

        raw = response.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        return json.loads(raw)

class GrokProvider(VisionProvider):
    def __init__(self, api_key: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(
            base_url="https://api.x.ai/v1",
            api_key=api_key
        )
        self.model = "grok-2-vision-1212"

    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
        from PIL import Image
        import io

        orig_img = Image.open(io.BytesIO(original_bytes))
        if orig_img.mode in ('RGBA', 'LA', 'P'):
            orig_img = orig_img.convert('RGB')
        sus_img = Image.open(io.BytesIO(suspect_bytes))
        if sus_img.mode in ('RGBA', 'LA', 'P'):
            sus_img = sus_img.convert('RGB')

        brand = meta.get('brand', 'не указан')
        marketplace = meta.get('marketplace', 'не указан')
        price_orig = meta.get('price_original', 0)
        price_sus = meta.get('price_suspect', 0)

        price_info = ""
        if price_orig > 0 and price_sus > 0:
            ratio = price_sus / price_orig * 100
            price_info = f"\nЦена оригинала: {price_orig}₽, подозрительного: {price_sus}₽ ({ratio:.0f}% от оригинала)."

        prompt = f"""Ты эксперт по выявлению контрафактных товаров на маркетплейсах.
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
        return json.loads(raw)

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
