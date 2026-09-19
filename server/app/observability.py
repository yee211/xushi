import json
import logging
import time
import uuid

from fastapi import Request

logger = logging.getLogger("classschedule")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


async def request_metrics_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        logger.info(json.dumps({
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }, ensure_ascii=False))
