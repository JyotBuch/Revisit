"""Optional Langfuse client — returns None when LANGFUSE_PUBLIC_KEY / SECRET_KEY
are absent so callers can guard with a simple `if lf is None: return`.

Local self-hosted Langfuse: set LANGFUSE_HOST=http://localhost:3000
Cloud:                       leave LANGFUSE_HOST unset (defaults to cloud.langfuse.com)
"""
import logging
import os
from typing import Optional

logger = logging.getLogger("revisit.langfuse")

_client = None
_initialized = False


def get_langfuse():
    """Return the singleton Langfuse client, or None if not configured."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    if not pk or not sk:
        return None

    try:
        from langfuse import Langfuse  # type: ignore
        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        # v4 SDK: host= and base_url= are both accepted
        _client = Langfuse(public_key=pk, secret_key=sk, host=host)
        logger.info("langfuse_initialized host=%s", host)
    except Exception as exc:
        logger.warning("langfuse_init_failed error=%s", exc)

    return _client


def reset() -> None:
    """Reset the singleton — only used in tests."""
    global _client, _initialized
    _client = None
    _initialized = False
