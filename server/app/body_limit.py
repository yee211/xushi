"""Bound request bodies before FastAPI parses JSON or spools file uploads."""
from tempfile import SpooledTemporaryFile

from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app, max_upload_bytes, max_json_bytes=2_100_000):
        self.app = app
        self.max_upload_bytes = max_upload_bytes
        self.max_json_bytes = max_json_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        multipart = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limit = self.max_upload_bytes + 512 * 1024 if multipart else self.max_json_bytes
        rejected = JSONResponse({"detail": "请求内容过大"}, status_code=413)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = 0
        if length > limit:
            return await rejected(scope, receive, send)
        # Spool with bounded memory, checking streamed/chunked bodies as well as declared sizes.
        with SpooledTemporaryFile(max_size=64 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > limit:
                    return await rejected(scope, receive, send)
                body.write(chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            finished = False

            async def replay():
                nonlocal finished
                if finished:
                    return await receive()
                chunk = body.read(64 * 1024)
                more = body.tell() < total
                finished = not more
                return {"type": "http.request", "body": chunk, "more_body": more}

            await self.app(scope, replay, send)
