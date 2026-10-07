"""Compatibility entry point for Render services still using ``app:app``."""

from backend.app import app

__all__ = ["app"]
