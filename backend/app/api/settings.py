from __future__ import annotations

import os
import platform

import cv2
import numpy as np
from fastapi import APIRouter
from sqlalchemy import select

from .. import __version__, annotate, db, settings_store, storage
from ..detector import available_devices, list_models
from ..monitor import monitor
from ..notify import Alert, send_discord, send_pushover

router = APIRouter(prefix="/api")


@router.get("/settings")
def get_settings():
    return settings_store.get_all()


@router.put("/settings")
async def put_settings(body: dict):
    before = settings_store.get("storage_limit_mb")
    saved = settings_store.update(body)
    if saved["storage_limit_mb"] < before:
        await monitor.run_blocking(storage.enforce, True)
    return saved


@router.get("/storage")
async def get_storage():
    return await monitor.run_blocking(storage.usage)


@router.get("/meta")
def meta():
    cpu = platform.processor() or ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {
        "version": __version__,
        "models": [{"id": m.id, "builtin": m.builtin, "size_mb": round(m.path.stat().st_size / 1e6, 1)} for m in list_models()],
        "devices": available_devices(),
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
    }


def _sample_image() -> tuple[bytes, bytes | None]:
    """Latest snapshot from any camera, or a placeholder when there are none."""
    with db.session() as s:
        snaps = list(s.scalars(select(db.Snapshot.id).order_by(db.Snapshot.ts.desc()).limit(2)))
    if snaps:
        now = monitor.render_snapshot(snaps[0], banner="NOW")
        before = monitor.render_snapshot(snaps[1], banner="PREVIOUS SCAN") if len(snaps) > 1 else None
        if now:
            return now, before
    img = np.full((360, 640, 3), 40, np.uint8)
    cv2.putText(img, "Traffic Webcam Monitor test alert", (52, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    return annotate.jpeg(img), None


def _test_alert(cfg: dict) -> Alert:
    now, before = _sample_image()
    combined = now
    if before:
        a = cv2.imdecode(np.frombuffer(before, np.uint8), cv2.IMREAD_COLOR)
        b = cv2.imdecode(np.frombuffer(now, np.uint8), cv2.IMREAD_COLOR)
        combined = annotate.jpeg(annotate.side_by_side(a, b), 80)
    base = (cfg.get("app_base_url") or "").rstrip("/")
    return Alert(
        title="Traffic Webcam Monitor test notification",
        message="If you can see this (and the images), notifications are set up correctly.",
        fields=[("Vehicles", "12"), ("Density", "heavy"), ("Flow", "stopped")],
        now_image=now, before_image=before if cfg.get("send_before_image") else None, combined_image=combined,
        url=base or None,
    )


@router.post("/settings/test/{channel}")
async def test_channel(channel: str, body: dict | None = None):
    # Test with what's in the form, even if it hasn't been saved yet.
    cfg = {**settings_store.get_all(), **(body or {})}
    alert = await monitor.run_blocking(_test_alert, cfg)
    if channel == "discord":
        return {"result": await send_discord(monitor.client, cfg, alert)}
    if channel == "pushover":
        return {"result": await send_pushover(monitor.client, cfg, alert)}
    return {"result": f"error: unknown channel {channel}"}


@router.post("/maintenance/cleanup")
async def cleanup():
    return await monitor.run_blocking(monitor.cleanup)
