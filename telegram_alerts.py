"""Telegram alerts with safe HTML formatting.

Uses parse_mode="HTML" + html.escape() for every user-controlled / LLM-generated
value: raw Markdown mode returned HTTP 400 whenever brand/summary/url contained
special characters (_ * [ ] ( ) ~ ` > # + - = | { } . !).
"""

import html
import httpx
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def format_alert_text(
    verdict: str,
    confidence: int,
    brand: str,
    url: str,
    summary: str,
) -> str:
    """Build the alert message body with all dynamic values HTML-escaped."""
    icon = "🚨" if verdict == "ПОДДЕЛКА" else "⚠️" if verdict == "ПОДОЗРИТЕЛЬНО" else "✅"

    text = (
        f"{icon} <b>FakeDetect Alert</b>\n\n"
        f"<b>Вердикт:</b> {html.escape(str(verdict))} ({int(confidence)}%)\n"
        f"<b>Бренд:</b> {html.escape(brand or 'не указан')}\n"
        f"<b>Итог:</b> {html.escape(summary or '')}\n"
    )
    if url:
        escaped_url = html.escape(url, quote=True)
        text += f'<b>Ссылка:</b> <a href="{escaped_url}">{escaped_url}</a>\n'
    return text


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

    text = format_alert_text(verdict, confidence, brand, url, summary)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if image_bytes:
                # Send photo with caption
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                    files={"photo": ("suspect.jpg", image_bytes, "image/jpeg")}
                )
            else:
                response = await client.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
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
