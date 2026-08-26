#!/usr/bin/env python3
"""One-off: rewrite backend imports after moving sources into app/ package."""
from pathlib import Path
import re

ROOTS = ["app", "tests", "evals", "scripts", "server.py"]

# (pattern, replacement) — applied to whole line; leading whitespace preserved.
RULES = [
    (r"^(\s*)from database import", r"\1from app.database import"),
    (r"^(\s*)import database$", r"\1from app import database"),
    # Generic dotted paths: from core.X / services.X.Y / routers.X / forensics.X.Y ...
    (r"^(\s*)from (core|services|routers|parsers|models|forensics)\.([\w.]+) import",
     r"\1from app.\2.\3 import"),
    (r"^(\s*)from (services|parsers) import", r"\1from app.\2 import"),
    (r"^(\s*)from routers import", r"\1from app.routers import"),
    (r"^(\s*)from models import", r"\1from app.models import"),
    (r"^(\s*)from forensics import", r"\1from app.forensics import"),
    (r"^(\s*)from aggregator import", r"\1from app.aggregator import"),
    (r"^(\s*)from llm_provider import", r"\1from app.llm_provider import"),
    (r"^(\s*)from batch_processor import", r"\1from app.batch_processor import"),
    (r"^(\s*)import observability$", r"\1from app import observability"),
    (r"^(\s*)import telegram_alerts$", r"\1from app import telegram_alerts"),
    (r"^(\s*)from main import", r"\1from app.main import"),
    (r"^(\s*)from telegram_alerts import", r"\1from app.telegram_alerts import"),
    (r"^(\s*)import core\.(\w+) as (\w+)", r"\1from app.core import \2 as \3"),
    (r"^(\s*)import batch_processor as (\w+)", r"\1from app import batch_processor as \2"),
]

changed = 0
for root in ROOTS:
    p = Path(root)
    files = [p] if p.is_file() else list(p.rglob("*.py"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        new_lines = []
        modified = False
        for line in text.splitlines(keepends=True):
            stripped = line.rstrip("\r\n")
            eol = line[len(stripped):]
            new = stripped
            for pattern, repl in RULES:
                new = re.sub(pattern, repl, new)
                if new != stripped:
                    modified = True
                    break
            new_lines.append(new + eol)
        if modified:
            f.write_text("".join(new_lines), encoding="utf-8")
            changed += 1

print(f"files rewritten: {changed}")
