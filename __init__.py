"""Hermes entry point. The plugin lives in the ``hermes_call_me`` package."""

from __future__ import annotations

try:
    from .hermes_call_me.plugin import register
except ImportError:
    from hermes_call_me.plugin import register

__all__ = ["register"]
