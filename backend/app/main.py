from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .media_files import media_dir
from .routers import admin, player

app = FastAPI(title="DOOH Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(player.router)
app.include_router(admin.public)
app.include_router(admin.router)
app.mount("/files", StaticFiles(directory=media_dir()), name="files")


@app.get("/api/health")
def health():
    return {"ok": True}
