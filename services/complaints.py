"""Complaint text generation (Block D.2).

Renders a ready-to-copy complaint for a specific marketplace from Jinja2
templates in ``templates/complaints/``. Marketplaces have no public API for
brand-complaint submission — the goal is to turn an hour of manual form
filling into 30 seconds of copy-paste, not to fake automation.
"""

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "complaints",
)

SUPPORTED_MARKETPLACES = ("WB", "Ozon", "Yandex")

_TEMPLATE_ALIASES = {
    "wb": "wb", "wildberries": "wb",
    "ozon": "ozon",
    "yandex": "yandex", "ym": "yandex", "market.yandex.ru": "yandex",
}


def resolve_template_marketplace(marketplace: str) -> str:
    """Return the template key actually used ('wb'|'ozon'|'yandex'|'generic')."""
    normalized = _TEMPLATE_ALIASES.get((marketplace or "").strip().lower())
    if normalized and os.path.exists(
        os.path.join(TEMPLATES_DIR, f"{normalized}.txt.j2")
    ):
        return normalized
    return "generic"


def render_complaint(marketplace: str, context: Dict[str, Any]) -> str:
    """Render complaint text for a marketplace ('WB' | 'Ozon' | 'Yandex')."""
    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    template_name = f"{resolve_template_marketplace(marketplace)}.txt.j2"

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template(template_name)
    return template.render(**context).strip() + "\n"
