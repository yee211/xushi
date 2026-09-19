"""Persistent, pooled HTTP client for upstream LLM and external API calls."""
import threading

import httpx

_original_httpx_post = httpx.post
_client: httpx.Client | None = None
_client_lock = threading.Lock()


def is_httpx_post_patched() -> bool:
    """Return True if httpx.post has been patched (e.g., in unit tests)."""
    return httpx.post is not _original_httpx_post


def get_llm_client() -> httpx.Client:
    """Return a thread-safe singleton httpx.Client with connection pooling."""
    global _client
    if _client is None or _client.is_closed:
        with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.Client(
                    limits=httpx.Limits(
                        max_keepalive_connections=20,
                        max_connections=50,
                        keepalive_expiry=30.0,
                    ),
                    follow_redirects=True,
                )
    return _client


def close_llm_client() -> None:
    """Close the underlying pool (useful during test cleanup or server shutdown)."""
    global _client
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            finally:
                _client = None
