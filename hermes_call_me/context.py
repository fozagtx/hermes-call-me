"""Process-wide handle to the Hermes plugin context.

``register()`` stores the context so settings can be read with
``ctx.get_config`` later. Registration itself does not call out to the network.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_ctx = None


def set_context(ctx) -> None:
    global _ctx
    with _lock:
        _ctx = ctx


def get_context():
    with _lock:
        return _ctx
