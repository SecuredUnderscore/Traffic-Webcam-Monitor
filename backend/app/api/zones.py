from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from .. import db, rules, settings_store
from ..analysis import DENSITY_LEVELS, MOTION_STATES
from ..monitor import monitor
from ..notify import NO_CHANNELS, deliver
from .serialize import observation_dict, rule_dict, zone_dict

router = APIRouter(prefix="/api")


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    direction: str = ""
    color: str = "#38bdf8"
    polygon: list[list[float]]
    enabled: bool = True
    metric: str = "count"
    thresholds: dict[str, float] = {}
    min_vehicles_for_motion: int = Field(2, ge=1, le=50)

    @field_validator("polygon")
    @classmethod
    def _poly(cls, v):
        if len(v) < 3:
            raise ValueError("A zone needs at least 3 points")
        return [[min(1.0, max(0.0, float(p[0]))), min(1.0, max(0.0, float(p[1])))] for p in v]

    @field_validator("metric")
    @classmethod
    def _metric(cls, v):
        if v not in ("count", "activity"):
            raise ValueError("metric must be count or activity")
        return v


class RuleIn(BaseModel):
    name: str = ""
    kind: str
    params: dict = {}
    cooldown_min: int = Field(30, ge=0, le=10080)
    enabled: bool = True
    channels: list[str] = ["discord", "pushover"]

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in rules.RULE_KINDS:
            raise ValueError(f"kind must be one of {rules.RULE_KINDS}")
        return v


def _validate_params(body: RuleIn) -> None:
    p = body.params
    if body.kind in ("density_change", "motion_change"):
        allowed = set(DENSITY_LEVELS if body.kind == "density_change" else MOTION_STATES)
        for key in ("from", "to"):
            vals = p.get(key) or []
            if not vals or not set(vals) <= allowed:
                raise HTTPException(422, f"'{key}' must be a non-empty subset of {sorted(allowed)}")
        p["min_prior"] = max(1, int(p.get("min_prior", 1)))
        p["confirm"] = max(1, int(p.get("confirm", 1)))
    else:
        if p.get("op") not in ("above", "below"):
            raise HTTPException(422, "op must be 'above' or 'below'")
        p["value"] = float(p.get("value", 0))
        p["scans"] = max(1, int(p.get("scans", 1)))


@router.post("/cameras/{cam_id}/zones")
def create_zone(cam_id: int, body: ZoneIn):
    with db.session() as s:
        if s.get(db.Camera, cam_id) is None:
            raise HTTPException(404, "Camera not found")
        z = db.Zone(camera_id=cam_id, **body.model_dump())
        s.add(z)
        s.commit()
        return zone_dict(z)


@router.put("/zones/{zone_id}")
def update_zone(zone_id: int, body: ZoneIn):
    with db.session() as s:
        z = s.get(db.Zone, zone_id)
        if z is None:
            raise HTTPException(404, "Zone not found")
        for k, v in body.model_dump().items():
            setattr(z, k, v)
        s.commit()
        return zone_dict(z)


@router.delete("/zones/{zone_id}")
def delete_zone(zone_id: int):
    with db.session() as s:
        z = s.get(db.Zone, zone_id)
        if z is None:
            raise HTTPException(404, "Zone not found")
        s.delete(z)
        s.commit()
    return {"ok": True}


@router.get("/zones/{zone_id}/history")
def zone_history(zone_id: int, limit: int = 96):
    with db.session() as s:
        rows = list(s.scalars(
            select(db.Observation).where(db.Observation.zone_id == zone_id).order_by(db.Observation.ts.desc()).limit(min(limit, 2000))
        ))[::-1]
        return [observation_dict(o) for o in rows]


@router.post("/zones/{zone_id}/rules")
def create_rule(zone_id: int, body: RuleIn):
    _validate_params(body)
    with db.session() as s:
        if s.get(db.Zone, zone_id) is None:
            raise HTTPException(404, "Zone not found")
        r = db.Rule(zone_id=zone_id, **body.model_dump())
        s.add(r)
        s.commit()
        return rule_dict(r)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn):
    _validate_params(body)
    with db.session() as s:
        r = s.get(db.Rule, rule_id)
        if r is None:
            raise HTTPException(404, "Rule not found")
        for k, v in body.model_dump().items():
            setattr(r, k, v)
        s.commit()
        return rule_dict(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    with db.session() as s:
        r = s.get(db.Rule, rule_id)
        if r is None:
            raise HTTPException(404, "Rule not found")
        s.delete(r)
        s.commit()
    return {"ok": True}


@router.post("/rules/{rule_id}/test")
async def test_rule(rule_id: int):
    """Send this rule's alert using the camera's latest two scans, without saving an event."""
    with db.session() as s:
        r = s.get(db.Rule, rule_id)
        if r is None:
            raise HTTPException(404, "Rule not found")
        z = r.zone
        cam = z.camera
        snaps = list(s.scalars(
            select(db.Snapshot.id).where(db.Snapshot.camera_id == cam.id).order_by(db.Snapshot.ts.desc()).limit(2)
        ))
        ev = db.Event(
            camera_id=cam.id, zone_id=z.id, rule_id=r.id,
            title=f"[TEST] {cam.name} · {z.name}: {r.name or r.kind}",
            message="This is a test alert. Real alerts show the state change that triggered them.",
            snapshot_id=snaps[0] if snaps else None, prev_snapshot_id=snaps[1] if len(snaps) > 1 else None,
        )
        channels = r.channels
    cfg = settings_store.get_all()
    alert = await monitor.run_blocking(monitor.build_alert, ev, cfg)
    return {"delivery": await deliver(monitor.client, cfg, alert, channels) or {"note": NO_CHANNELS}}
