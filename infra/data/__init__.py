"""Data foundation for AITC.

The data layer owns runtime data receiving, caching, persistence, and query
interfaces used by agents and legacy orchestration code.
"""

from .api import DataRepository, get_default_repository

__all__ = ["DataRepository", "get_default_repository"]
