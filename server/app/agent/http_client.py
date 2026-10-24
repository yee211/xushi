import os
import threading
from urllib.parse import urlsplit

import httpx

from .budget import remaining
from .telemetry import record_llm_call

_original_httpx_post = httpx.post
_client: httpx.Client | None = None
_client_lock = threading.Lock()
_llm_semaphore: threading.Semaphore | None = None
_semaphore_lock = threading.Lock()


def get_llm_semaphore() -> threading.Semaphore:
    """返回用于控制外部大模型请求并发度的全局信号量，平滑削峰。"""
    global _llm_semaphore
    if _llm_semaphore is None:
        with _semaphore_lock:
            if _llm_semaphore is None:
                max_concurrency = max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "8")))
                _llm_semaphore = threading.Semaphore(max_concurrency)
    return _llm_semaphore


def is_httpx_post_patched() -> bool:
    """Return True if httpx.post has been patched (e.g., in unit tests)."""
    return httpx.post is not _original_httpx_post


def post_llm(url: str, **kwargs) -> httpx.Response:
    """统一受限的外部大模型 POST 请求：
    1. 单元测试 mock patch 时直接调用 httpx.post；
    2. 真实运行时通过全局信号量限流削峰，复用连接池 client。
    """
    if urlsplit(url).hostname == "api.deepseek.com" and isinstance(kwargs.get("json"), dict):
        payload = dict(kwargs["json"])
        enabled = bool(payload.pop("enable_thinking", False))
        payload.setdefault("thinking", {"type": "enabled" if enabled else "disabled"})
        kwargs["json"] = payload
    timeout = float(kwargs.get("timeout") or 15)
    kwargs["timeout"] = remaining(timeout)
    if is_httpx_post_patched():
        response = httpx.post(url, **kwargs)
    else:
        semaphore = get_llm_semaphore()
        if not semaphore.acquire(timeout=remaining(timeout)):
            raise httpx.TimeoutException("Agent model queue timed out")
        try:
            kwargs["timeout"] = remaining(timeout)
            response = get_llm_client().post(url, **kwargs)
        finally:
            semaphore.release()
    record_llm_call(response)
    return response


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

