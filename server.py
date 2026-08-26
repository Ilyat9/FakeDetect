"""Backwards-compatible entry point.

Run the application with either::

    uvicorn server:app --reload     # legacy alias
    uvicorn main:app --reload       # canonical
"""

from app.core.config import settings  # noqa: F401  (re-exported for backwards compat)
from app.main import app  # noqa: F401

