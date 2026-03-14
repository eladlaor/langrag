"""
Observability API Package

Provides endpoints for system observability:
- Metrics: Prometheus metrics for monitoring
- Runs: Historical data access, queries, and analytics

All routers are re-exported here for easy importing in main.py
"""

from .metrics import router as metrics_router
from .runs import router as runs_router

__all__ = ["metrics_router", "runs_router"]
