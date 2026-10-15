import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import health, research, reports, studies
from app.core.config import get_settings
from app.core.max_body_size import MaxBodySizeMiddleware
from app.core.security_headers import SecurityHeadersMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("clinical-evidence-intelligence")

settings = get_settings()

app = FastAPI(
    title="Clinical Evidence Intelligence API",
    description="AI-assisted evidence research — not a diagnostic or treatment tool.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MaxBodySizeMiddleware)

app.include_router(health.router)
app.include_router(research.router)
app.include_router(studies.router)
app.include_router(reports.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Never leak internals (stack traces, DB errors, API keys) to the client.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred. Please try again."},
    )
