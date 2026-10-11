import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import backups, orders
from .config import settings
from .media_files import media_dir
from .routers import admin, player, website

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("dooh")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.is_production and (problems := settings.production_problems()):
        # Refuse to start rather than run in public with a weak login.
        raise RuntimeError("Unsafe production settings: " + "; ".join(problems))
    stop = backups.start_scheduler() if settings.daily_backups else None
    orders.resume_queued()
    yield
    if stop:
        stop.set()


app = FastAPI(title="DOOH Platform API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


app.include_router(player.router)
app.include_router(admin.public)
app.include_router(admin.router)
app.include_router(website.router)
app.mount("/files", StaticFiles(directory=media_dir()), name="files")


@app.get("/api/health")
def health():
    return {"ok": True}


class DashboardFiles(StaticFiles):
    """The built dashboard. Unknown paths get index.html so client-side routes
    like /screens work on reload; index.html itself is never cached, so a
    deploy reaches browsers right away."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith(("api/", "files/")):
                raise
            response = await super().get_response("index.html", scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


if (settings.dashboard_dir / "index.html").is_file():
    app.mount("/", DashboardFiles(directory=settings.dashboard_dir, html=True), name="dashboard")
