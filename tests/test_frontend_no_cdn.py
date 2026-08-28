"""E-C3 regression: the React frontend (frontend/) must stay CDN-free — no
external <script src>, stylesheet, or font host — so it keeps working fully
offline and under frontend/nginx.conf's strict `default-src 'self'` CSP.

Does not cover legacy/index.html, which is intentionally frozen (still loads
Chart.js + Google Fonts from a CDN) — see E-C3 in docs/COMPROMISES.md.
"""

import re
from pathlib import Path

FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"

CDN_PATTERN = re.compile(
    r"""(?:https?:)?//(?:cdn\.[a-z0-9.-]+|[a-z0-9.-]*\.jsdelivr\.net|"""
    r"""unpkg\.com|cdnjs\.cloudflare\.com|fonts\.googleapis\.com|"""
    r"""fonts\.gstatic\.com)""",
    re.IGNORECASE,
)

SCAN_EXTENSIONS = {".html", ".ts", ".tsx", ".js", ".jsx", ".css"}
SKIP_DIRS = {"node_modules", "dist", "storybook-static", ".storybook"}


def _frontend_source_files():
    for path in FRONTEND_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCAN_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def test_frontend_has_no_cdn_references():
    offenders = []
    for path in _frontend_source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if CDN_PATTERN.search(text):
            offenders.append(str(path.relative_to(FRONTEND_ROOT)))

    assert not offenders, (
        "frontend/ must stay CDN-free (see E-C3 in docs/COMPROMISES.md); "
        f"found CDN references in: {offenders}"
    )
