"""Process-wide handle to the Hermes plugin context.

``register()`` stores the context. The webhook thread reads it later to try
``inject_message``. Registration itself does not call out to the network.
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
