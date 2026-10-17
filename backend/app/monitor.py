"""Polls cameras, runs detection + analysis on new frames, fires alerts."""

from __future__ import annotations

import asyncio
import logging
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import httpx
import numpy as np
from sqlalchemy import select

from . import annotate, db, rules, settings_store
from .analysis import HISTORY, CameraMemory, ZoneSpec, analyze, to_work
from .detector import Detection, pool, run_detection
from .fetcher import fetch
from .notify import NO_CHANNELS, Alert, deliver

log = logging.getLogger(__name__)

DENSITY_ORDER = {"empty": 0, "light": 1, "moderate": 2, "heavy": 3}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def zone_specs(zones: list[db.Zone]) -> list[ZoneSpec]:
    return [ZoneSpec(z.id, z.polygon, z.metric, z.thresholds or {}, z.min_vehicles_for_motion) for z in zones if z.enabled]


def dets_from_json(items: list[dict]) -> list[Detection]:
    return [Detection(d["x1"], d["y1"], d["x2"], d["y2"], d.get("score", 1.0), d.get("label", "car")) for d in items or []]


def load_image(path: str) -> np.ndarray | None:
    return cv2.imread(path, cv2.IMREAD_COLOR)


def detector_config(cam: db.Camera, cfg: dict) -> tuple[str, str, float, int]:
    model = cam.model_id or cfg["detector_model"]
    conf = cam.conf if cam.conf is not None else cfg["detector_conf"]
    grid = cam.tile_grid if cam.tile_grid is not None else cfg["detector_tile_grid"]
    return model, cfg["detector_device"], float(conf), int(grid)


def detect(img: np.ndarray, model_id: str, device: str, conf: float, grid: int) -> tuple[list[Detection], float, str]:
    model = pool.get(model_id, device)
    dets, ms = run_detection(model, img, conf, grid)
    return dets, ms, model.info.id


def build_memory(snapshots: list[db.Snapshot]) -> CameraMemory:
    """Rebuild a camera's memory from stored frames (oldest-first)."""
    mem = CameraMemory()
    for s in snapshots[-HISTORY:]:
        img = load_image(s.path)
        if img is None:
            continue
        _, gray, scale = to_work(img)
        mem.remember(gray, dets_from_json(s.detections), scale, s.view_shift)
    return mem


class Monitor:
    def __init__(self):
        self.tasks: dict[int, asyncio.Task] = {}
        self.memories: dict[int, CameraMemory] = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self.next_check: dict[int, datetime] = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="detect")
        self.client: httpx.AsyncClient | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._housekeeper: asyncio.Task | None = None

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.client = httpx.AsyncClient()
        with db.session() as s:
            ids = [c.id for c in s.scalars(select(db.Camera).where(db.Camera.enabled))]
        for cid in ids:
            self.schedule(cid, initial_delay=random.uniform(1, 8))
        self._housekeeper = asyncio.create_task(self._housekeeping())

    async def stop(self) -> None:
        for t in list(self.tasks.values()) + ([self._housekeeper] if self._housekeeper else []):
            t.cancel()
        if self.client:
            await self.client.aclose()
        self.executor.shutdown(wait=False, cancel_futures=True)

    async def run_blocking(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)

    # Scheduling

    def _on_loop(self, fn, *args) -> None:
        """Run fn on the event loop; API handlers may call in from worker threads."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            fn(*args)
        elif self.loop is not None:
            self.loop.call_soon_threadsafe(fn, *args)

    def schedule(self, cam_id: int, initial_delay: float = 0.5) -> None:
        self._on_loop(self._schedule, cam_id, initial_delay)

    def unschedule(self, cam_id: int) -> None:
        self._on_loop(self._unschedule, cam_id)

    def _schedule(self, cam_id: int, initial_delay: float) -> None:
        self._unschedule(cam_id)
        self.tasks[cam_id] = asyncio.create_task(self._loop(cam_id, initial_delay))

    def _unschedule(self, cam_id: int) -> None:
        task = self.tasks.pop(cam_id, None)
        if task:
            task.cancel()
        self.next_check.pop(cam_id, None)

    def forget(self, cam_id: int) -> None:
        self.unschedule(cam_id)
        self.memories.pop(cam_id, None)
        self.locks.pop(cam_id, None)

    async def _loop(self, cam_id: int, initial_delay: float) -> None:
        self.next_check[cam_id] = utcnow() + timedelta(seconds=initial_delay)
        await asyncio.sleep(initial_delay)
        while True:
            try:
                await self.check(cam_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("camera %s check failed", cam_id)
            with db.session() as s:
                cam = s.get(db.Camera, cam_id)
                if cam is None or not cam.enabled:
                    return
                interval = max(15, cam.interval_sec)
            self.next_check[cam_id] = utcnow() + timedelta(seconds=interval)
            await asyncio.sleep(interval)

    # Checking

    def _memory(self, cam_id: int) -> CameraMemory:
        if cam_id not in self.memories:
            with db.session() as s:
                snaps = list(s.scalars(
                    select(db.Snapshot).where(db.Snapshot.camera_id == cam_id).order_by(db.Snapshot.ts.desc()).limit(HISTORY)
                ))[::-1]
            self.memories[cam_id] = build_memory(snaps)
        return self.memories[cam_id]

    async def check(self, cam_id: int) -> dict:
        lock = self.locks.setdefault(cam_id, asyncio.Lock())
        async with lock:
            with db.session() as s:
                cam = s.get(db.Camera, cam_id)
                if cam is None:
                    return {"status": "error", "error": "camera not found"}
                res = await fetch(self.client, cam.url, cam.headers, cam.cache_bust, cam.etag, cam.last_modified, cam.last_hash)
                cam.last_checked_at = utcnow()
                if res.status == "error":
                    cam.consecutive_errors += 1
                    cam.last_error = res.error
                    s.commit()
                    return {"status": "error", "error": res.error}
                cam.consecutive_errors = 0
                cam.last_error = None
                cam.etag, cam.last_modified = res.etag, res.last_modified
                if res.status == "unchanged":
                    s.commit()
                    return {"status": "unchanged"}
                cam.last_hash = res.sha
                cam.last_new_image_at = utcnow()
                s.commit()

            snapshot_id, fired = await self.run_blocking(self._process, cam_id, res.image, res.data, res.sha)
            for event_id in fired:
                await self._notify(event_id)
            return {"status": "new", "snapshot_id": snapshot_id, "events": fired}

    def _process(self, cam_id: int, img: np.ndarray, data: bytes, sha: str) -> tuple[int, list[int]]:
        """Runs in a worker thread: detect, analyze, store, evaluate rules."""
        cfg = settings_store.get_all()
        with db.session() as s:
            cam = s.get(db.Camera, cam_id)
            model_id, device, conf, grid = detector_config(cam, cfg)
            dets, ms, used_model = detect(img, model_id, device, conf, grid)
            memory = self._memory(cam_id)
            zones = [z for z in cam.zones if z.enabled]
            fa = analyze(img, dets, zone_specs(zones), memory)

            now = utcnow()
            folder = db.SNAPSHOT_DIR / str(cam_id)
            folder.mkdir(parents=True, exist_ok=True)
            snap = db.Snapshot(
                camera_id=cam_id, ts=now, path="", sha=sha, width=img.shape[1], height=img.shape[0],
                detections=[d.to_dict() for d in dets], inference_ms=round(ms, 1), model_id=used_model,
                view_score=fa.view_score, view_shift=fa.view_shift, brightness=round(fa.brightness, 1),
            )
            s.add(snap)
            s.flush()
            path = folder / f"{snap.id}.jpg"
            path.write_bytes(data)
            snap.path = str(path)
            prev_snapshot_id = cam.last_snapshot_id
            cam.last_snapshot_id = snap.id

            for r in fa.zones:
                s.add(db.Observation(
                    snapshot_id=snap.id, zone_id=r.zone_id, ts=now, count=r.count, occupancy=round(r.occupancy, 2),
                    activity=r.activity, change=r.change, stationary=r.stationary,
                    density=r.density, motion=r.motion, light_hint=r.light_hint,
                ))
            s.flush()

            fired: list[int] = []
            if fa.view_shift:
                log.info("camera %s view changed (score %.2f); skipping rules", cam_id, fa.view_score or 0)
            else:
                fired = self._evaluate_rules(s, cam, zones, fa, snap.id, prev_snapshot_id, now)
            s.commit()
            return snap.id, fired

    def _evaluate_rules(self, s, cam: db.Camera, zones: list[db.Zone], fa, snap_id: int,
                        prev_snapshot_id: int | None, now: datetime) -> list[int]:
        fired = []
        results = {r.zone_id: r for r in fa.zones}
        for z in zones:
            if z.id not in results:
                continue
            active = [r for r in z.rules if r.enabled]
            if not active:
                continue
            need = max(rules.history_needed(r.kind, r.params) for r in active)
            rows = list(s.scalars(
                select(db.Observation).where(db.Observation.zone_id == z.id).order_by(db.Observation.ts.desc()).limit(need)
            ))[::-1]
            history = [rules.Obs(o.count, o.activity, o.density, o.motion) for o in rows]
            for rule in active:
                if rules.in_cooldown(rule.last_fired_at, rule.cooldown_min, now):
                    continue
                trig = rules.evaluate(rule.kind, rule.params, history)
                if not trig:
                    continue
                zr = results[z.id]
                label = f"{z.name}" + (f" ({z.direction})" if z.direction and z.direction not in z.name else "")
                ev = db.Event(
                    ts=now, camera_id=cam.id, zone_id=z.id, rule_id=rule.id,
                    title=f"{cam.name} · {label}: {trig.title}",
                    message=(rule.name + " — " if rule.name else "") + trig.detail,
                    snapshot_id=snap_id, prev_snapshot_id=prev_snapshot_id,
                    delivery={"pending": rule.channels},
                )
                s.add(ev)
                s.flush()
                rule.last_fired_at = now
                fired.append(ev.id)
                log.info("rule %s fired on zone %s: %s (count=%s)", rule.id, z.id, trig.title, zr.count)
        return fired

    # Alerts

    def render_snapshot(self, snapshot_id: int, highlight_zone: int | None = None, banner: str | None = None) -> bytes | None:
        """Annotated JPEG of a stored snapshot, using the observations recorded for it."""
        with db.session() as s:
            snap = s.get(db.Snapshot, snapshot_id)
            if snap is None:
                return None
            img = load_image(snap.path)
            if img is None:
                return None
            cam = s.get(db.Camera, snap.camera_id)
            obs = list(s.scalars(select(db.Observation).where(db.Observation.snapshot_id == snapshot_id)))
            zone_ids = {o.zone_id for o in obs}
            zones = [{"id": z.id, "name": z.name, "color": z.color, "polygon": z.polygon}
                     for z in (cam.zones if cam else []) if z.id in zone_ids or (z.enabled and not obs)]
            results = {}
            for o in obs:
                results[o.zone_id] = {"count": o.count, "density": o.density, "motion": o.motion, "detections": []}
            # Re-derive which detections belong to which zone for colouring.
            dets = dets_from_json(snap.detections)
            specs = [ZoneSpec(z["id"], z["polygon"]) for z in zones]
            if specs:
                tmp = analyze(img, dets, specs, CameraMemory(), commit=False)
                for zr in tmp.zones:
                    if zr.zone_id in results:
                        results[zr.zone_id]["detections"] = zr.detections
            out = annotate.render(img, zones, results, snap.detections, banner=banner, highlight_zone=highlight_zone)
            return annotate.jpeg(out)

    def _alert_images(self, ev: db.Event, send_before: bool) -> tuple[bytes | None, bytes | None, bytes | None]:
        now_img = self.render_snapshot(ev.snapshot_id, ev.zone_id, "NOW") if ev.snapshot_id else None
        before_img = None
        combined = now_img
        if send_before and ev.prev_snapshot_id:
            before_img = self.render_snapshot(ev.prev_snapshot_id, ev.zone_id, "PREVIOUS SCAN")
            if before_img and now_img:
                a = cv2.imdecode(np.frombuffer(before_img, np.uint8), cv2.IMREAD_COLOR)
                b = cv2.imdecode(np.frombuffer(now_img, np.uint8), cv2.IMREAD_COLOR)
                combined = annotate.jpeg(annotate.side_by_side(a, b), 80)
        return now_img, before_img, combined

    def build_alert(self, ev: db.Event, cfg: dict) -> Alert:
        with db.session() as s:
            zone = s.get(db.Zone, ev.zone_id) if ev.zone_id else None
            obs = s.scalars(select(db.Observation).where(
                db.Observation.snapshot_id == ev.snapshot_id, db.Observation.zone_id == ev.zone_id)).first() if zone else None
            prev = s.get(db.Snapshot, ev.prev_snapshot_id) if ev.prev_snapshot_id else None
            cur = s.get(db.Snapshot, ev.snapshot_id) if ev.snapshot_id else None
        fields = []
        if obs:
            fields += [("Vehicles", str(obs.count)), ("Density", obs.density), ("Flow", obs.motion)]
            if obs.activity is not None:
                fields.append(("Activity", f"{obs.activity:.1f}%"))
        if prev and cur:
            mins = (cur.ts - prev.ts).total_seconds() / 60
            fields.append(("Since previous scan", f"{mins:.0f} min"))
        now_img, before_img, combined = self._alert_images(ev, bool(cfg.get("send_before_image")))
        base = (cfg.get("app_base_url") or "").rstrip("/")
        return Alert(
            title=ev.title, message=ev.message, color=zone.color if zone else "#38bdf8", fields=fields,
            now_image=now_img, before_image=before_img, combined_image=combined,
            url=f"{base}/events?event={ev.id}" if base else None, ts=ev.ts,
        )

    async def _notify(self, event_id: int) -> None:
        cfg = settings_store.get_all()
        with db.session() as s:
            ev = s.get(db.Event, event_id)
            rule = s.get(db.Rule, ev.rule_id) if ev.rule_id else None
            channels = rule.channels if rule else ["discord", "pushover"]
        alert = await self.run_blocking(self.build_alert, ev, cfg)
        delivery = await deliver(self.client, cfg, alert, channels)
        with db.session() as s:
            ev = s.get(db.Event, event_id)
            ev.delivery = delivery or {"note": NO_CHANNELS}
            s.commit()

    # Housekeeping

    async def _housekeeping(self) -> None:
        while True:
            try:
                await self.run_blocking(self.cleanup)
            except Exception:
                log.exception("housekeeping failed")
            await asyncio.sleep(3600)

    def cleanup(self) -> dict:
        cfg = settings_store.get_all()
        now = utcnow()
        removed_files = 0
        with db.session() as s:
            ev_cut = now - timedelta(days=int(cfg["event_retention_days"]))
            n_events = s.query(db.Event).filter(db.Event.ts < ev_cut).delete()
            keep = set()
            for a, b in s.query(db.Event.snapshot_id, db.Event.prev_snapshot_id):
                keep.update(x for x in (a, b) if x)
            keep.update(x for (x,) in s.query(db.Camera.last_snapshot_id) if x)
            cut = now - timedelta(hours=int(cfg["retention_hours"]))
            old = s.scalars(select(db.Snapshot).where(db.Snapshot.ts < cut))
            ids = []
            for snap in old:
                if snap.id in keep:
                    continue
                try:
                    Path(snap.path).unlink(missing_ok=True)
                    removed_files += 1
                except OSError:
                    pass
                ids.append(snap.id)
            for i in range(0, len(ids), 500):
                s.query(db.Snapshot).filter(db.Snapshot.id.in_(ids[i:i + 500])).delete(synchronize_session=False)
            s.commit()
        return {"events_deleted": n_events, "snapshots_deleted": len(ids), "files_deleted": removed_files}

    # Status helpers

    def camera_status(self, cam: db.Camera) -> str:
        if not cam.enabled:
            return "paused"
        if cam.consecutive_errors >= 3:
            return "error"
        if cam.last_new_image_at is None:
            return "pending" if cam.consecutive_errors == 0 else "error"
        stale_after = max(timedelta(minutes=30), timedelta(seconds=cam.interval_sec * 4))
        if utcnow() - cam.last_new_image_at > stale_after:
            return "stale"
        return "ok"


monitor = Monitor()
