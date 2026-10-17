from __future__ import annotations

import base64
import shutil

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import autozones, db
from ..analysis import ZoneSpec, analyze
from ..fetcher import fetch
from ..monitor import build_memory, dets_from_json, detect, detector_config, load_image, monitor
from .. import settings_store
from .serialize import camera_dict, observation_dict, snapshot_dict

router = APIRouter(prefix="/api")


class CameraIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8)
    interval_sec: int = Field(300, ge=15, le=86400)
    enabled: bool = True
    headers: dict[str, str] = {}
    cache_bust: bool = False
    notes: str = ""
    model_id: str | None = None
    tile_grid: int | None = Field(None, ge=0, le=4)
    conf: float | None = Field(None, ge=0.01, le=0.95)


class ProbeIn(BaseModel):
    url: str
    headers: dict[str, str] = {}
    cache_bust: bool = False


class PreviewZone(BaseModel):
    id: int = 0
    polygon: list[list[float]]
    metric: str = "count"
    thresholds: dict = {}
    min_vehicles_for_motion: int = 2


class PreviewIn(BaseModel):
    zones: list[PreviewZone]


def _get_cam(s, cam_id: int) -> db.Camera:
    cam = s.get(db.Camera, cam_id)
    if cam is None:
        raise HTTPException(404, "Camera not found")
    return cam


@router.get("/cameras")
def list_cameras():
    with db.session() as s:
        return [camera_dict(s, c) for c in s.scalars(select(db.Camera).order_by(db.Camera.id))]


@router.get("/cameras/{cam_id}")
def get_camera(cam_id: int):
    with db.session() as s:
        return camera_dict(s, _get_cam(s, cam_id))


@router.post("/cameras")
def create_camera(body: CameraIn):
    with db.session() as s:
        cam = db.Camera(**body.model_dump())
        s.add(cam)
        s.commit()
        cam_id = cam.id
    if body.enabled:
        monitor.schedule(cam_id)
    with db.session() as s:
        return camera_dict(s, _get_cam(s, cam_id))


@router.put("/cameras/{cam_id}")
def update_camera(cam_id: int, body: CameraIn):
    with db.session() as s:
        cam = _get_cam(s, cam_id)
        url_changed = cam.url != body.url
        for k, v in body.model_dump().items():
            setattr(cam, k, v)
        if url_changed:
            cam.etag = cam.last_modified = cam.last_hash = None
        s.commit()
    if url_changed:
        monitor.memories.pop(cam_id, None)
    if body.enabled:
        monitor.schedule(cam_id)
    else:
        monitor.unschedule(cam_id)
    with db.session() as s:
        return camera_dict(s, _get_cam(s, cam_id))


@router.delete("/cameras/{cam_id}")
def delete_camera(cam_id: int):
    monitor.forget(cam_id)
    with db.session() as s:
        cam = _get_cam(s, cam_id)
        s.delete(cam)
        s.commit()
    shutil.rmtree(db.SNAPSHOT_DIR / str(cam_id), ignore_errors=True)
    return {"ok": True}


@router.post("/cameras/probe")
async def probe(body: ProbeIn):
    res = await fetch(monitor.client, body.url, body.headers, body.cache_bust)
    if res.status == "error":
        return {"ok": False, "error": res.error}
    h, w = res.image.shape[:2]
    return {
        "ok": True, "width": w, "height": h, "bytes": len(res.data),
        "etag": res.etag, "last_modified": res.last_modified,
        "image": "data:image/jpeg;base64," + base64.b64encode(res.data).decode(),
    }


@router.post("/cameras/{cam_id}/check")
async def check_now(cam_id: int):
    with db.session() as s:
        _get_cam(s, cam_id)
    result = await monitor.check(cam_id)
    with db.session() as s:
        return {"result": result, "camera": camera_dict(s, _get_cam(s, cam_id))}


@router.get("/cameras/{cam_id}/snapshots")
def list_snapshots(cam_id: int, limit: int = 48):
    with db.session() as s:
        snaps = list(s.scalars(
            select(db.Snapshot).where(db.Snapshot.camera_id == cam_id).order_by(db.Snapshot.ts.desc()).limit(min(limit, 500))
        ))
        ids = [x.id for x in snaps]
        obs: dict[int, list] = {}
        if ids:
            for o in s.scalars(select(db.Observation).where(db.Observation.snapshot_id.in_(ids))):
                obs.setdefault(o.snapshot_id, []).append(observation_dict(o))
        return [{**snapshot_dict(x), "observations": obs.get(x.id, [])} for x in snaps]


def _preview(cam_id: int, zones: list[PreviewZone]) -> dict:
    with db.session() as s:
        snaps = list(s.scalars(
            select(db.Snapshot).where(db.Snapshot.camera_id == cam_id).order_by(db.Snapshot.ts.desc()).limit(16)
        ))[::-1]
    if not snaps:
        raise HTTPException(409, "No image yet. Run a check first.")
    latest = snaps[-1]
    img = load_image(latest.path)
    if img is None:
        raise HTTPException(410, "Latest image file is missing")
    # Memory as it was just before the latest frame, so motion/activity match the live pipeline.
    memory = build_memory(snaps[:-1])
    specs = [ZoneSpec(z.id or -(i + 1), z.polygon, z.metric, z.thresholds, z.min_vehicles_for_motion)
             for i, z in enumerate(zones)]
    fa = analyze(img, dets_from_json(latest.detections), specs, memory, commit=False)
    return {"snapshot_id": latest.id, "view_shift": fa.view_shift, "zones": [r.to_dict() for r in fa.zones]}


@router.post("/cameras/{cam_id}/preview")
async def preview(cam_id: int, body: PreviewIn):
    return await monitor.run_blocking(_preview, cam_id, body.zones)


def _suggest(cam_id: int) -> dict:
    with db.session() as s:
        cam = _get_cam(s, cam_id)
        snaps = list(s.scalars(
            select(db.Snapshot).where(db.Snapshot.camera_id == cam_id).order_by(db.Snapshot.ts.desc()).limit(40)
        ))[::-1]
        model_id, device, conf, grid = detector_config(cam, settings_store.get_all())
    if not snaps:
        raise HTTPException(409, "No image yet. Run a check first.")
    frames = []
    for snap in snaps:
        img = load_image(snap.path)
        if img is not None:
            frames.append((img, dets_from_json(snap.detections)))
    if not frames:
        raise HTTPException(410, "Image files are missing")
    # With little history, squeeze more vehicles out of the latest frame.
    if sum(len(d) for _, d in frames) < 12:
        dets, _, _ = detect(frames[-1][0], model_id, device, max(0.15, conf - 0.1), max(3, grid))
        frames[-1] = (frames[-1][0], dets)
    return autozones.suggest(frames)


@router.post("/cameras/{cam_id}/suggest-zones")
async def suggest_zones(cam_id: int):
    return await monitor.run_blocking(_suggest, cam_id)


@router.get("/snapshots/{snap_id}")
def get_snapshot(snap_id: int):
    with db.session() as s:
        snap = s.get(db.Snapshot, snap_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        obs = [observation_dict(o) for o in s.scalars(select(db.Observation).where(db.Observation.snapshot_id == snap_id))]
        return {**snapshot_dict(snap, with_detections=True), "observations": obs}


@router.get("/snapshots/{snap_id}/image")
def snapshot_image(snap_id: int, v: str | None = None):
    with db.session() as s:
        snap = s.get(db.Snapshot, snap_id)
        if snap is None:
            raise HTTPException(404, "Snapshot not found")
        path, sha = snap.path, snap.sha
    # Only a URL pinned to this exact image content (?v=<sha prefix>) may be cached forever.
    pinned = v is not None and len(v) >= 8 and sha.startswith(v)
    cache = "public, max-age=31536000, immutable" if pinned else "no-cache"
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": cache})


@router.get("/snapshots/{snap_id}/annotated")
async def snapshot_annotated(snap_id: int, zone: int | None = None):
    data = await monitor.run_blocking(monitor.render_snapshot, snap_id, zone, None)
    if data is None:
        raise HTTPException(404, "Snapshot not found")
    return Response(data, media_type="image/jpeg")
