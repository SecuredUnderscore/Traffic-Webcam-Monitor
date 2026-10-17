"""Suggests traffic zones from where vehicles have appeared across past scans.

Each detected vehicle stamps its road footprint into a heatmap; dense
regions become candidate zones. Divided highways separate into one zone per
carriageway. When vehicles are too small to detect, pixels that keep
changing between scans are used instead. At night, the colour of vehicle
lights hints at direction: red taillights = heading away from the camera,
white headlights = heading toward it.
"""

from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from .analysis import DIFF_THRESHOLD, _light_hint, to_work, view_similarity, VIEW_SHIFT_THRESHOLD
from .detector import Detection

PALETTE = ["#38bdf8", "#f472b6", "#a3e635", "#fb923c", "#c084fc", "#facc15"]


def _polygon(contour: np.ndarray, w: int, h: int, max_pts: int = 12) -> list[list[float]]:
    peri = cv2.arcLength(contour, True)
    eps = 0.01 * peri
    approx = cv2.approxPolyDP(contour, eps, True)
    while len(approx) > max_pts:
        eps *= 1.4
        approx = cv2.approxPolyDP(contour, eps, True)
    return [[round(float(p[0][0]) / w, 4), round(float(p[0][1]) / h, 4)] for p in approx]


def _is_static(inside: list[tuple[int, Detection, float]]) -> bool:
    """True when a region's detections never move across scans: a parked car or a
    sign the detector mistakes for a vehicle, not a traffic lane."""
    frames = {fi for fi, _, _ in inside}
    if len(frames) < 3:
        return False
    boxes = [(d.x1 * sc, d.y1 * sc, d.x2 * sc, d.y2 * sc) for _, d, sc in inside]
    ref = boxes[0]
    def iou(a, b):
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        inter = ix * iy
        union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
        return inter / union if union > 0 else 0.0
    return all(iou(ref, b) > 0.5 for b in boxes[1:])


def suggest(frames: list[tuple[np.ndarray, list[Detection]]]) -> dict:
    """frames: oldest-first (image, detections). Returns {"zones": [...], "method": str, "frames": n}."""
    if not frames:
        return {"zones": [], "method": "none", "frames": 0}
    _, ref_gray, _ = to_work(frames[-1][0])
    h, w = ref_gray.shape

    # Only use frames that share the latest frame's view.
    usable = []
    for img, dets in frames:
        small, gray, scale = to_work(img)
        if gray.shape == ref_gray.shape and view_similarity(gray, ref_gray) >= VIEW_SHIFT_THRESHOLD:
            usable.append((small, gray, scale, dets))

    heat = np.zeros((h, w), np.float32)
    widths = []
    placed: list[tuple[int, Detection, float, tuple[int, int]]] = []  # (frame, det, scale, ground point)
    for fi, (_, _, scale, dets) in enumerate(usable):
        for d in dets:
            bw, bh = (d.x2 - d.x1) * scale, (d.y2 - d.y1) * scale
            cx, cy = (d.x1 + d.x2) / 2 * scale, d.y2 * scale - bh * 0.3
            # Footprints scale with the vehicle, so big near-camera cars still join up into lanes.
            stamp = np.zeros((h, w), np.uint8)
            cv2.ellipse(stamp, (int(cx), int(cy)), (max(2, int(bw * 0.9)), max(2, int(bh * 0.6))), 0, 0, 360, 1, -1)
            heat += stamp
            widths.append(bw)
            placed.append((fi, d, scale, (int(np.clip(cx, 0, w - 1)), int(np.clip(cy, 0, h - 1)))))
    n_dets = len(placed)

    method = "detections"
    if n_dets >= 3:
        base = (heat > 0).astype(np.uint8)
        k = int(np.clip(np.median(widths) * 0.8, 5, 30))
    else:
        # Fall back to pixels that change between consecutive scans.
        method = "pixel-change"
        if len(usable) < 3:
            return {"zones": [], "method": "insufficient-data", "frames": len(usable)}
        freq = np.zeros((h, w), np.float32)
        for (_, a, _, _), (_, b, _, _) in zip(usable, usable[1:]):
            freq += (np.abs(a.astype(np.float32) - b.astype(np.float32)) > DIFF_THRESHOLD)
        pairs = len(usable) - 1
        base = (freq >= max(2, pairs * 0.3)).astype(np.uint8)
        base = cv2.morphologyEx(base, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        k = 9

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    closed = cv2.morphologyEx(base, cv2.MORPH_CLOSE, kernel)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(closed, 8)

    dark = [(small, gray) for small, gray, _, _ in usable if gray.mean() <= 70]
    zones = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < h * w * 0.004:
            continue
        comp = (labels == i)
        support = 0
        if method == "detections":
            inside = [(fi, d, sc) for fi, d, sc, (gx, gy) in placed if comp[gy, gx]]
            support = len(inside)
            if support < 2 and n_dets > 6:
                continue
            if _is_static(inside):
                continue
        contours, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        hints = Counter(h_ for small, gray in dark if (h_ := _light_hint(small, comp, float(gray.mean()))))
        hint = hints.most_common(1)[0][0] if hints else None
        zones.append({
            "polygon": _polygon(contour, w, h),
            "area": float(stats[i, cv2.CC_STAT_AREA] / (h * w)),
            "cx": float(centroids[i][0] / w),
            "direction_hint": hint,
            "support": support,
        })

    zones.sort(key=lambda z: z["cx"])
    for idx, z in enumerate(zones):
        hint = {"away": "Away from camera", "toward": "Toward camera"}.get(z["direction_hint"] or "")
        side = "left" if z["cx"] < 0.4 else "right" if z["cx"] > 0.6 else "center"
        z["name"] = hint or f"Lanes {idx + 1} ({side})"
        z["color"] = PALETTE[idx % len(PALETTE)]
    return {"zones": zones, "method": method, "frames": len(usable), "detections": n_dets}
