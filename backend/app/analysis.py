"""Turns a camera frame + detections into per-zone traffic state.

Cameras only refresh every 5-20 minutes, so there is no video to track
vehicles through. Instead each zone is described by signals that work on
isolated frames, compared against what the camera remembers from earlier
frames:

count       vehicles whose ground point falls inside the zone
occupancy   % of the zone covered by vehicle boxes
activity    % of the zone that differs from the learned empty road (median of
            recent frames). Works even when vehicles are too small to detect.
change      % of the zone that differs from the previous frame
stationary  share of vehicles still in the same spot, looking the same, as
            in the previous frame minutes ago. A high value means stopped
            traffic; moving traffic never lines up across a multi-minute gap.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from .detector import Detection

WORK_W = 400
HISTORY = 15
DIFF_THRESHOLD = 28
VIEW_SHIFT_THRESHOLD = 0.7  # same view scores >= 0.8 on real cams, different views <= 0.63

DENSITY_LEVELS = ["empty", "light", "moderate", "heavy"]
MOTION_STATES = ["none", "stopped", "slow", "moving"]

DEFAULT_THRESHOLDS = {
    "count": {"empty": 0, "light": 3, "moderate": 8},
    "activity": {"empty": 1.5, "light": 6, "moderate": 15},
}


@dataclass
class ZoneSpec:
    id: int
    polygon: list[list[float]]
    metric: str = "count"
    thresholds: dict = field(default_factory=dict)
    min_vehicles_for_motion: int = 2


@dataclass
class ZoneResult:
    zone_id: int
    count: int
    occupancy: float
    activity: float | None
    change: float | None
    stationary: float | None
    density: str
    motion: str
    light_hint: str | None
    detections: list[int]

    def to_dict(self) -> dict:
        r = lambda v: None if v is None else round(v, 2)  # noqa: E731
        return {
            "zone_id": self.zone_id, "count": self.count, "occupancy": r(self.occupancy),
            "activity": r(self.activity), "change": r(self.change), "stationary": r(self.stationary),
            "density": self.density, "motion": self.motion, "light_hint": self.light_hint,
            "detections": self.detections,
        }


@dataclass
class FrameAnalysis:
    zones: list[ZoneResult]
    view_score: float | None
    view_shift: bool
    brightness: float


class CameraMemory:
    """What a camera remembers between scans."""

    def __init__(self):
        self.history: deque[np.ndarray] = deque(maxlen=HISTORY)
        self.prev_gray: np.ndarray | None = None
        self.prev_dets: list[Detection] = []
        self.prev_scale: float = 1.0

    def remember(self, gray: np.ndarray, dets: list[Detection], scale: float, view_shift: bool) -> None:
        if view_shift:
            self.history.clear()
        self.history.append(gray)
        self.prev_gray = gray
        self.prev_dets = dets
        self.prev_scale = scale


def to_work(img_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    h, w = img_bgr.shape[:2]
    scale = WORK_W / w
    small = cv2.resize(img_bgr, (WORK_W, max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    return small, gray, scale


def zone_mask(polygon: list[list[float]], shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    pts = np.array([[p[0] * w, p[1] * h] for p in polygon], dtype=np.int32)
    mask = np.zeros((h, w), dtype=np.uint8)
    if len(pts) >= 3:
        cv2.fillPoly(mask, [pts], 1)
    return mask.astype(bool)


def view_similarity(a: np.ndarray, b: np.ndarray, ignore: np.ndarray | None = None) -> float:
    """Edge overlap between two frames; drops sharply when a PTZ camera is moved.

    ignore masks out regions (vehicles) whose edges are expected to change.
    """
    if a.shape != b.shape:
        return 0.0
    ea = cv2.Canny(a, 60, 150)
    eb = cv2.Canny(b, 60, 150)
    if ignore is not None:
        ea[ignore] = 0
        eb[ignore] = 0
    k = np.ones((5, 5), np.uint8)
    da, db = cv2.dilate(ea, k) > 0, cv2.dilate(eb, k) > 0
    na, nb = (ea > 0).sum(), (eb > 0).sum()
    if na < 50 or nb < 50:
        # Featureless frames (fog, night) — can't judge, assume unchanged.
        return 1.0
    return float(((eb > 0) & da).sum() / nb + ((ea > 0) & db).sum() / na) / 2


def _normalize_to(src: np.ndarray, ref: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Shift src's brightness to match ref inside mask (clouds, auto-exposure).

    Uses the median difference so vehicles covering part of the zone don't skew it.
    """
    s = src.astype(np.float32)
    if mask.sum() < 10:
        return s
    offset = float(np.median(ref[mask].astype(np.float32) - s[mask]))
    return s + offset


def _diff_mask(cur: np.ndarray, ref: np.ndarray, mask: np.ndarray) -> np.ndarray:
    diff = np.abs(_normalize_to(cur, ref, mask) - ref.astype(np.float32)) > DIFF_THRESHOLD
    diff = cv2.morphologyEx(diff.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) > 0
    return diff & mask


def _iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def _patch(gray: np.ndarray, d: Detection, scale: float) -> np.ndarray | None:
    h, w = gray.shape
    x1, y1 = max(0, int(d.x1 * scale)), max(0, int(d.y1 * scale))
    x2, y2 = min(w, int(np.ceil(d.x2 * scale))), min(h, int(np.ceil(d.y2 * scale)))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return cv2.resize(gray[y1:y2, x1:x2], (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32)


def _same_look(a: np.ndarray | None, b: np.ndarray | None) -> bool:
    if a is None or b is None:
        return False
    a, b = a - a.mean(), b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-3:
        # Flat patches: compare raw intensity instead.
        return abs(float(a.mean() - b.mean())) < 10
    ncc = float((a * b).sum() / denom)
    return ncc > 0.6


def density_level(value: float | None, thresholds: dict) -> str:
    if value is None:
        return "unknown"
    if value <= thresholds["empty"]:
        return "empty"
    if value <= thresholds["light"]:
        return "light"
    if value <= thresholds["moderate"]:
        return "moderate"
    return "heavy"


def motion_state(stationary: float | None, density: str) -> str:
    if density == "empty":
        return "none"
    if stationary is None:
        return "unknown"
    if stationary >= 0.6:
        return "stopped"
    if stationary >= 0.3:
        return "slow"
    return "moving"


def _light_hint(small_bgr: np.ndarray, mask: np.ndarray, brightness: float) -> str | None:
    """At night, red taillights mean traffic heading away, white headlights toward."""
    if brightness > 70:
        return None
    hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
    hch, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    bright = (v > 190) & mask
    red = bright & ((hch <= 10) | (hch >= 165)) & (s > 90)
    white = bright & (s < 60)
    n = int(red.sum() + white.sum())
    if n < max(6, mask.sum() * 0.002):
        return None
    frac = red.sum() / n
    if frac > 0.6:
        return "away"
    if frac < 0.25:
        return "toward"
    return None


def analyze(
    img_bgr: np.ndarray,
    dets: list[Detection],
    zones: list[ZoneSpec],
    memory: CameraMemory,
    commit: bool = True,
) -> FrameAnalysis:
    small, gray, scale = to_work(img_bgr)
    brightness = float(gray.mean())

    prev = memory.prev_gray if memory.prev_gray is not None and memory.prev_gray.shape == gray.shape else None
    view_score = None
    if prev is not None:
        vehicles = np.zeros(gray.shape, dtype=np.uint8)
        for d, sc in [(d, scale) for d in dets] + [(d, memory.prev_scale) for d in memory.prev_dets]:
            cv2.rectangle(vehicles, (int(d.x1 * sc) - 2, int(d.y1 * sc) - 2), (int(d.x2 * sc) + 2, int(d.y2 * sc) + 2), 1, -1)
        view_score = view_similarity(prev, gray, vehicles > 0)
    view_shift = view_score is not None and view_score < VIEW_SHIFT_THRESHOLD
    if view_shift:
        prev = None

    history = [g for g in memory.history if g.shape == gray.shape] if not view_shift else []
    background = np.median(np.stack(history), axis=0).astype(np.uint8) if len(history) >= 3 else None

    cur_patches = [_patch(gray, d, scale) for d in dets]
    prev_dets = memory.prev_dets if prev is not None else []

    results: list[ZoneResult] = []
    for z in zones:
        mask = zone_mask(z.polygon, gray.shape)
        area = int(mask.sum())
        if area == 0:
            continue
        thresholds = {**DEFAULT_THRESHOLDS.get(z.metric, DEFAULT_THRESHOLDS["count"]), **(z.thresholds or {})}

        # Vehicles count toward a zone by where they touch the road, not their whole box.
        idx = []
        for i, d in enumerate(dets):
            gx = int(np.clip((d.x1 + d.x2) / 2 * scale, 0, gray.shape[1] - 1))
            gy = int(np.clip((d.y2 - 0.1 * (d.y2 - d.y1)) * scale, 0, gray.shape[0] - 1))
            if mask[gy, gx]:
                idx.append(i)
        count = len(idx)

        boxes = np.zeros(gray.shape, dtype=np.uint8)
        for i in idx:
            d = dets[i]
            cv2.rectangle(boxes, (int(d.x1 * scale), int(d.y1 * scale)), (int(d.x2 * scale), int(d.y2 * scale)), 1, -1)
        occupancy = float(((boxes > 0) & mask).sum() / area * 100)

        fg = _diff_mask(gray, background, mask) if background is not None else None
        activity = float(fg.sum() / area * 100) if fg is not None else None
        changed = _diff_mask(gray, prev, mask) if prev is not None else None
        change = float(changed.sum() / area * 100) if changed is not None else None

        stationary = None
        if prev is not None and count >= z.min_vehicles_for_motion:
            still = 0
            for i in idx:
                best, best_iou = None, 0.6
                for p in prev_dets:
                    iou = _iou(dets[i], p)
                    if iou >= best_iou:
                        best, best_iou = p, iou
                if best is not None and _same_look(cur_patches[i], _patch(prev, best, memory.prev_scale)):
                    still += 1
            stationary = still / count
        elif z.metric == "activity" and fg is not None and changed is not None:
            # Vehicles too small to detect: of the pixels that look like traffic now,
            # how many are identical to the previous frame? Too noisy for count zones,
            # where a single detection would otherwise decide the flow.
            fg_px = int(fg.sum())
            if fg_px >= max(8, area * max(0.005, thresholds["empty"] / 100)):
                stationary = float((fg & ~changed).sum() / fg_px)

        value = count if z.metric == "count" else activity
        density = density_level(value, thresholds)
        results.append(ZoneResult(
            zone_id=z.id, count=count, occupancy=occupancy, activity=activity, change=change,
            stationary=stationary, density=density, motion=motion_state(stationary, density),
            light_hint=_light_hint(small, mask, brightness), detections=idx,
        ))

    if commit:
        memory.remember(gray, dets, scale, view_shift)
    return FrameAnalysis(results, view_score, view_shift, brightness)

