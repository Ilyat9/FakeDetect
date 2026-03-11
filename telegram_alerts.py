import httpx
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def send_telegram_alert(
    bot_token: str,
    chat_id: str,
    verdict: str,
    confidence: int,
    brand: str,
    url: str,
    summary: str,
    image_bytes: Optional[bytes] = None
) -> bool:
    """Send alert to Telegram when fake is detected."""
    if not bot_token or not chat_id:
        return False

    icon = "🚨" if verdict == "ПОДДЕЛКА" else "⚠️" if verdict == "ПОДОЗРИТЕЛЬНО" else "✅"

    text = (
        f"{icon} *FakeDetect Alert*\n\n"
        f"*Вердикт:* {verdict} ({confidence}%)\n"
        f"*Бренд:* {brand or 'не указан'}\n"
        f"*Итог:* {summary}\n"
    )
    if url:
        text += f"*Ссылка:* {url}\n"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if image_bytes:
                # Send photo with caption
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": text, "parse_mode": "Markdown"},
                    files={"photo": ("suspect.jpg", image_bytes, "image/jpeg")}
                )
            else:
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
                )

            if response.status_code == 200:
                logger.info(f"Telegram alert sent: {verdict} ({confidence}%)")
                return True
            else:
                logger.error(f"Telegram error: {response.status_code} {response.text}")
                return False

    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False
