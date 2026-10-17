"""Detector Lab: compare models, tiling and devices on a real camera frame."""

from __future__ import annotations

import base64
import statistics

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..detector import available_devices, list_models, pool, run_detection
from ..fetcher import decode_image, fetch
from ..monitor import load_image, monitor

router = APIRouter(prefix="/api/lab")


class LabIn(BaseModel):
    snapshot_id: int | None = None
    url: str | None = None
    models: list[str] = []
    grids: list[int] = [0, 2]
    devices: list[str] = ["cpu"]
    conf: float = Field(0.25, ge=0.01, le=0.95)
    runs: int = Field(3, ge=1, le=20)


def _bench(img, body: LabIn) -> list[dict]:
    models = body.models or [m.id for m in list_models()]
    devices = [d for d in body.devices if d in available_devices()] or ["cpu"]
    out = []
    for device in devices:
        for model_id in models:
            try:
                model = pool.get(model_id, device)
            except Exception as e:  # noqa: BLE001
                out.append({"model": model_id, "device": device, "error": str(e)})
                continue
            for grid in body.grids:
                run_detection(model, img, body.conf, grid)  # warm-up
                times, dets = [], []
                for _ in range(body.runs):
                    dets, ms = run_detection(model, img, body.conf, grid)
                    times.append(ms)
                out.append({
                    "model": model.info.id, "device": device, "provider": model.active_provider, "grid": grid,
                    "ms_median": round(statistics.median(times), 1), "ms_min": round(min(times), 1),
                    "count": len(dets), "mean_score": round(statistics.mean(d.score for d in dets), 3) if dets else None,
                    "detections": [d.to_dict() for d in dets],
                })
    return out


@router.post("/run")
async def run(body: LabIn):
    image_ref: dict
    if body.snapshot_id:
        with db.session() as s:
            snap = s.get(db.Snapshot, body.snapshot_id)
            if snap is None:
                raise HTTPException(404, "Snapshot not found")
            path = snap.path
        img = load_image(path)
        image_ref = {"snapshot_id": body.snapshot_id}
    elif body.url:
        res = await fetch(monitor.client, body.url)
        if res.status == "error":
            raise HTTPException(502, res.error)
        img = decode_image(res.data)
        image_ref = {"data_url": "data:image/jpeg;base64," + base64.b64encode(res.data).decode()}
    else:
        raise HTTPException(422, "Provide snapshot_id or url")
    if img is None:
        raise HTTPException(410, "Image could not be loaded")
    results = await monitor.run_blocking(_bench, img, body)
    h, w = img.shape[:2]
    return {"image": {**image_ref, "width": w, "height": h}, "results": results}
