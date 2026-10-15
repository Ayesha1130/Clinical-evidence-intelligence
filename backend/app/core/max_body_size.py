"""
Rejects request bodies over a configured size before they're read into
memory. This is a cheap, real protection against a client (accidentally
or otherwise) sending an oversized payload to an endpoint like
POST /api/research that only ever expects a short question string.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

DEFAULT_MAX_BODY_BYTES = 1_000_000  # 1 MB — generous for any JSON body this API accepts


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body exceeds the {self._max_body_bytes} byte limit."},
                    )
            except ValueError:
                pass
        return await call_next(request)
