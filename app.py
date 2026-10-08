"""Vercel Flask function entry point and local WSGI compatibility export."""

from backend.app import app

__all__ = ["app"]
