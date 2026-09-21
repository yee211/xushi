import os
import threading

import httpx

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
    if is_httpx_post_patched():
        return httpx.post(url, **kwargs)
    with get_llm_semaphore():
        return get_llm_client().post(url, **kwargs)


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

