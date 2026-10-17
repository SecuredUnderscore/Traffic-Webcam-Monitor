from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from .. import db
from .serialize import iso

router = APIRouter(prefix="/api")


def event_dict(e: db.Event, names: dict) -> dict:
    return {
        "id": e.id, "ts": iso(e.ts), "camera_id": e.camera_id, "zone_id": e.zone_id, "rule_id": e.rule_id,
        "camera_name": names["cam"].get(e.camera_id), "zone_name": names["zone"].get(e.zone_id),
        "title": e.title, "message": e.message, "snapshot_id": e.snapshot_id,
        "prev_snapshot_id": e.prev_snapshot_id, "delivery": e.delivery, "acknowledged": e.acknowledged,
    }


def _names(s) -> dict:
    return {
        "cam": dict(s.execute(select(db.Camera.id, db.Camera.name)).all()),
        "zone": dict(s.execute(select(db.Zone.id, db.Zone.name)).all()),
    }


@router.get("/events")
def list_events(camera_id: int | None = None, limit: int = 100, before_id: int | None = None):
    with db.session() as s:
        q = select(db.Event).order_by(db.Event.id.desc()).limit(min(limit, 500))
        if camera_id:
            q = q.where(db.Event.camera_id == camera_id)
        if before_id:
            q = q.where(db.Event.id < before_id)
        names = _names(s)
        return [event_dict(e, names) for e in s.scalars(q)]


@router.get("/events/unread")
def unread_count():
    with db.session() as s:
        return {"count": s.query(db.Event).filter(db.Event.acknowledged.is_(False)).count()}


@router.post("/events/{event_id}/ack")
def ack(event_id: int):
    with db.session() as s:
        e = s.get(db.Event, event_id)
        if e is None:
            raise HTTPException(404, "Event not found")
        e.acknowledged = True
        s.commit()
    return {"ok": True}


@router.post("/events/ack-all")
def ack_all():
    with db.session() as s:
        s.query(db.Event).filter(db.Event.acknowledged.is_(False)).update({"acknowledged": True})
        s.commit()
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: int):
    with db.session() as s:
        e = s.get(db.Event, event_id)
        if e is None:
            raise HTTPException(404, "Event not found")
        s.delete(e)
        s.commit()
    return {"ok": True}
