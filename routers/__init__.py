"""API routers aggregation."""

from .analysis import router as analysis_router
from .batch import router as batch_router
from .data import router as data_router

__all__ = ["analysis_router", "batch_router", "data_router"]

