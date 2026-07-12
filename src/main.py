import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .auth import require_http_api_key
from .api.routes import router
from .observability import configure_logging, log_event
from .storage.database import init_database

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Agent Meeting Assistant",
    description="A learning-first multi-agent meeting assistant built with FastAPI and LangGraph.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

app.include_router(router)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    started = time.perf_counter()
    if request.url.path.startswith("/api/"):
        try:
            require_http_api_key(request)
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "valid API key required")
            return JSONResponse({"detail": detail}, status_code=status_code)
    response = await call_next(request)
    if request.url.path.startswith(("/api/", "/health")):
        log_event(
            logger,
            "http_request",
            "http request completed",
            stage="http",
            status=str(response.status_code),
            duration_ms=(time.perf_counter() - started) * 1000,
        )
    return response


@app.get("/ui", include_in_schema=False)
async def web_ui() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.on_event("startup")
def startup() -> None:
    init_database()
