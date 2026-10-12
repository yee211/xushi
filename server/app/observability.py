import json
import logging
import re
import time
import uuid

from fastapi import Request

logger = logging.getLogger("classschedule")


class RedactHttpSecrets(logging.Filter):
    def filter(self, record):
        # Apply to transport records before any configured handler sees them.
        message = record.getMessage()
        message = re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*', r'\1?[REDACTED]', message)
        record.msg, record.args = message, ()
        return True


class RedactingFormatter(logging.Formatter):
    def __init__(self, original):
        super().__init__()
        self.original = original

    def format(self, record):
        value = self.original.format(record)
        return re.sub(r'(https?://[^\s?"<>]+)\?[^\s"<>]*', r'\1?[REDACTED]', value)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        for handler in logging.getLogger(name).handlers:
            if not any(isinstance(item, RedactHttpSecrets) for item in handler.filters):
                handler.addFilter(RedactHttpSecrets())
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter("%(message)s")))
    # httpcore's debug records can contain raw headers; retain warnings only.
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
