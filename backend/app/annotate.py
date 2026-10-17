"""Renders zones, detections and states onto frames for alerts and the UI."""

from __future__ import annotations

import cv2
import numpy as np

MIN_WIDTH = 800

DENSITY_COLORS = {"empty": "#64748b", "light": "#22c55e", "moderate": "#eab308", "heavy": "#ef4444", "unknown": "#94a3b8"}


def hex_to_bgr(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) != 6:
        return (248, 189, 56)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return (b, g, r)


def _label(img: np.ndarray, text: str, org: tuple[int, int], color: tuple[int, int, int], scale: float) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    th = max(1, round(scale * 2))
    (tw, tht), base = cv2.getTextSize(text, font, scale, th)
    x, y = org
    x = int(np.clip(x, 0, img.shape[1] - tw - 8))
    y = int(np.clip(y, tht + 8, img.shape[0] - 2))
    cv2.rectangle(img, (x, y - tht - 8), (x + tw + 8, y + base - 2), (20, 20, 20), -1)
    cv2.rectangle(img, (x, y - tht - 8), (x + 4, y + base - 2), color, -1)
    cv2.putText(img, text, (x + 6, y - 4), font, scale, (255, 255, 255), th, cv2.LINE_AA)


def render(
    img_bgr: np.ndarray,
    zones: list[dict],
    results: dict[int, dict],
    detections: list[dict],
    banner: str | None = None,
    highlight_zone: int | None = None,
) -> np.ndarray:
    """zones: [{id, name, color, polygon}], results: zone_id -> observation dict."""
    h, w = img_bgr.shape[:2]
    k = max(1.0, MIN_WIDTH / w)
    img = cv2.resize(img_bgr, (round(w * k), round(h * k)), interpolation=cv2.INTER_CUBIC) if k > 1 else img_bgr.copy()
    H, W = img.shape[:2]
    scale = 0.5 * max(1.0, W / 900)

    overlay = img.copy()
    for z in zones:
        pts = np.array([[p[0] * W, p[1] * H] for p in z["polygon"]], dtype=np.int32)
        if len(pts) < 3:
            continue
        cv2.fillPoly(overlay, [pts], hex_to_bgr(z.get("color", "#38bdf8")))
    img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)

    zone_of = {}
    for z in zones:
        for i in (results.get(z["id"]) or {}).get("detections", []):
            zone_of[i] = z
    for i, d in enumerate(detections):
        z = zone_of.get(i)
        color = hex_to_bgr(z["color"]) if z else (160, 160, 160)
        p1 = (int(d["x1"] * k), int(d["y1"] * k))
        p2 = (int(d["x2"] * k), int(d["y2"] * k))
        cv2.rectangle(img, p1, p2, color, 2 if z else 1, cv2.LINE_AA)

    for z in zones:
        pts = np.array([[p[0] * W, p[1] * H] for p in z["polygon"]], dtype=np.int32)
        if len(pts) < 3:
            continue
        color = hex_to_bgr(z.get("color", "#38bdf8"))
        thick = 4 if z["id"] == highlight_zone else 2
        cv2.polylines(img, [pts], True, color, thick, cv2.LINE_AA)
        r = results.get(z["id"])
        text = z["name"]
        if r:
            parts = [f"{r['count']} veh", r["density"]]
            if r.get("motion") not in (None, "none", "unknown"):
                parts.append(r["motion"])
            text += " | " + " ".join(parts)
        top = pts[np.argmin(pts[:, 1])]
        _label(img, text, (int(top[0]) - 20, int(top[1]) - 6), color, scale)

    if banner:
        bar = np.full((round(34 * max(1.0, scale * 2)), W, 3), 24, dtype=np.uint8)
        cv2.putText(bar, banner, (10, bar.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, scale * 1.3, (255, 255, 255),
                    max(1, round(scale * 2.5)), cv2.LINE_AA)
        img = np.vstack([bar, img])
    return img


def side_by_side(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    h = max(before.shape[0], after.shape[0])

    def fit(im: np.ndarray) -> np.ndarray:
        return cv2.resize(im, (round(im.shape[1] * h / im.shape[0]), h))

    gap = np.full((h, 8, 3), 255, dtype=np.uint8)
    return np.hstack([fit(before), gap, fit(after)])


def jpeg(img: np.ndarray, quality: int = 85) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""
