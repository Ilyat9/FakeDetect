"""Email digest delivery over plain SMTP (Block C, C-C4).

Provider-agnostic on purpose: any SMTP host works (Mailgun, SendGrid SMTP
relay, Yandex, a corporate mail server, ...) — configured entirely through
SMTP_* env vars, never a specific vendor SDK. Uses stdlib smtplib in a thread
executor; no extra dependency for something this simple.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List

from app.core.config import get_secret, settings

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "templates", "emails",
)


def render_digest_html(brand: str, fakes: List[Dict[str, Any]], suspicious: List[Dict[str, Any]]) -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=True,
    )
    template = env.get_template("digest.html.j2")
    return template.render(brand=brand, fakes=fakes, suspicious=suspicious)


def _send_sync(to_email: str, subject: str, html_body: str, text_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        password = get_secret(settings.smtp_password)
        if settings.smtp_user and password:
            smtp.login(settings.smtp_user, password)
        smtp.sendmail(settings.smtp_from_email, [to_email], msg.as_string())


async def send_digest_email(
    to_email: str, subject: str, html_body: str, text_body: str
) -> bool:
    """Send one digest email. Returns False (logged) on any failure — the
    caller (discovery_engine.maybe_send_digest) treats this the same way it
    already treats a failed Telegram send: best-effort, never blocks the scan.
    """
    import asyncio

    try:
        await asyncio.to_thread(_send_sync, to_email, subject, html_body, text_body)
        logger.info(f"Digest email sent to {to_email}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to send digest email to {to_email}: {e}")
        return False
