from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .storage.database import init_database


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


@app.get("/ui", include_in_schema=False)
async def web_ui() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.on_event("startup")
def startup() -> None:
    init_database()
