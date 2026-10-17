from __future__ import annotations

from sqlalchemy import select

from .. import db
from ..monitor import monitor


def iso(dt):
    return dt.isoformat() if dt else None


def rule_dict(r: db.Rule) -> dict:
    return {
        "id": r.id, "zone_id": r.zone_id, "name": r.name, "kind": r.kind, "params": r.params,
        "cooldown_min": r.cooldown_min, "enabled": r.enabled, "channels": r.channels,
        "last_fired_at": iso(r.last_fired_at),
    }


def observation_dict(o: db.Observation | None) -> dict | None:
    if o is None:
        return None
    return {
        "snapshot_id": o.snapshot_id, "zone_id": o.zone_id, "ts": iso(o.ts), "count": o.count,
        "occupancy": o.occupancy, "activity": o.activity, "change": o.change, "stationary": o.stationary,
        "density": o.density, "motion": o.motion, "light_hint": o.light_hint,
    }


def zone_dict(z: db.Zone, latest: db.Observation | None = None) -> dict:
    return {
        "id": z.id, "camera_id": z.camera_id, "name": z.name, "direction": z.direction, "color": z.color,
        "polygon": z.polygon, "enabled": z.enabled, "metric": z.metric, "thresholds": z.thresholds or {},
        "min_vehicles_for_motion": z.min_vehicles_for_motion,
        "rules": [rule_dict(r) for r in z.rules],
        "latest": observation_dict(latest),
    }


def snapshot_dict(snap: db.Snapshot | None, with_detections: bool = False) -> dict | None:
    if snap is None:
        return None
    d = {
        "id": snap.id, "camera_id": snap.camera_id, "ts": iso(snap.ts), "width": snap.width, "height": snap.height,
        "vehicle_count": len(snap.detections or []), "inference_ms": snap.inference_ms, "model_id": snap.model_id,
        "view_score": snap.view_score, "view_shift": snap.view_shift, "brightness": snap.brightness,
    }
    if with_detections:
        d["detections"] = snap.detections
    return d


def camera_dict(s, cam: db.Camera) -> dict:
    latest = s.get(db.Snapshot, cam.last_snapshot_id) if cam.last_snapshot_id else None
    obs = {}
    if latest:
        obs = {o.zone_id: o for o in s.scalars(select(db.Observation).where(db.Observation.snapshot_id == latest.id))}
    return {
        "id": cam.id, "name": cam.name, "url": cam.url, "interval_sec": cam.interval_sec, "enabled": cam.enabled,
        "headers": cam.headers or {}, "cache_bust": cam.cache_bust, "notes": cam.notes,
        "model_id": cam.model_id, "tile_grid": cam.tile_grid, "conf": cam.conf,
        "status": monitor.camera_status(cam), "last_checked_at": iso(cam.last_checked_at),
        "last_new_image_at": iso(cam.last_new_image_at), "last_error": cam.last_error,
        "next_check_at": iso(monitor.next_check.get(cam.id)),
        "latest": snapshot_dict(latest, with_detections=True),
        "zones": [zone_dict(z, obs.get(z.id)) for z in cam.zones],
    }
