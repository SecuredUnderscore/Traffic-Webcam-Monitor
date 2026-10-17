from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import cameras, events, lab, settings, zones
from .monitor import monitor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

STATIC_DIR = Path(os.environ.get("TW_STATIC_DIR", Path(__file__).resolve().parent.parent / "static"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    await monitor.start()
    yield
    await monitor.stop()


app = FastAPI(title="TrafficWatch", lifespan=lifespan)
for r in (cameras.router, zones.router, events.router, settings.router, lab.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
