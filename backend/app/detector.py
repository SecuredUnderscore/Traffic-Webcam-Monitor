"""Vehicle detection with YOLO models exported to ONNX.

Traffic cameras are often tiny (335x244 is common) and vehicles far from the
camera are only a few pixels tall, so an optional tiled mode runs the model on
overlapping crops (each upscaled to the model's input size) as well as on the
full frame, then merges the results.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

log = logging.getLogger(__name__)

MODELS_DIR = Path(os.environ.get("TW_MODELS_DIR", "/app/models"))
EXTRA_MODELS_DIR = Path(os.environ.get("TW_DATA_DIR", "/data")) / "models"

# COCO class ids that count as vehicles.
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    label: str

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def to_dict(self) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in asdict(self).items()}


@dataclass
class ModelInfo:
    id: str
    path: Path
    input_size: int
    builtin: bool


def list_models() -> list[ModelInfo]:
    models: list[ModelInfo] = []
    manifest = MODELS_DIR / "manifest.json"
    if manifest.exists():
        for m in json.loads(manifest.read_text()):
            p = MODELS_DIR / m["file"]
            if p.exists():
                models.append(ModelInfo(m["id"], p, int(m.get("input_size", 640)), True))
    # Users can drop extra Ultralytics-format ONNX exports into /data/models.
    if EXTRA_MODELS_DIR.exists():
        known = {m.id for m in models}
        for p in sorted(EXTRA_MODELS_DIR.glob("*.onnx")):
            if p.stem not in known:
                models.append(ModelInfo(p.stem, p, 640, False))
    return models


def available_devices() -> list[str]:
    providers = ort.get_available_providers()
    devices = ["cpu"]
    if "CUDAExecutionProvider" in providers:
        devices.append("cuda")
    return devices


class OnnxYolo:
    def __init__(self, info: ModelInfo, device: str = "cpu", threads: int = 0):
        self.info = info
        self.device = device
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        providers = ["CPUExecutionProvider"]
        if device == "cuda" and "CUDAExecutionProvider" in ort.get_available_providers():
            providers.insert(0, "CUDAExecutionProvider")
        self.session = ort.InferenceSession(str(info.path), sess_options=opts, providers=providers)
        self.active_provider = self.session.get_providers()[0]
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        self.size = int(shape[2]) if isinstance(shape[2], int) else info.input_size
        self._lock = threading.Lock()

    def _letterbox(self, img: np.ndarray) -> tuple[np.ndarray, float, int, int]:
        h, w = img.shape[:2]
        scale = min(self.size / w, self.size / h)
        nw, nh = round(w * scale), round(h * scale)
        interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        resized = cv2.resize(img, (nw, nh), interpolation=interp)
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        px, py = (self.size - nw) // 2, (self.size - nh) // 2
        canvas[py:py + nh, px:px + nw] = resized
        return canvas, scale, px, py

    def infer(self, img_bgr: np.ndarray, conf: float) -> list[Detection]:
        canvas, scale, px, py = self._letterbox(img_bgr)
        blob = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self._lock:
            out = self.session.run(None, {self.input_name: blob})[0]
        return self._decode(out, conf, scale, px, py)

    def _decode(self, out: np.ndarray, conf: float, scale: float, px: int, py: int) -> list[Detection]:
        out = out[0]
        ids = list(VEHICLE_CLASSES)
        if out.shape[-1] == 6:
            # End-to-end export: rows of x1, y1, x2, y2, score, class.
            rows = [r for r in out if r[4] >= conf and int(r[5]) in VEHICLE_CLASSES]
            boxes = [(r[0], r[1], r[2], r[3]) for r in rows]
            scores = [float(r[4]) for r in rows]
            labels = [VEHICLE_CLASSES[int(r[5])] for r in rows]
            keep = list(range(len(rows)))
        else:
            # Raw export: (4 + num_classes, anchors) of cx, cy, w, h, class scores.
            pred = out.T
            cls_scores = pred[:, [4 + i for i in ids]]
            best = cls_scores.argmax(1)
            score = cls_scores.max(1)
            mask = score >= conf
            if not mask.any():
                return []
            pred, best, score = pred[mask], best[mask], score[mask]
            cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
            xywh = np.stack([cx - w / 2, cy - h / 2, w, h], 1)
            # Class-agnostic NMS so a vehicle isn't counted as both car and truck.
            keep = cv2.dnn.NMSBoxes(xywh.tolist(), score.tolist(), conf, 0.5)
            keep = np.array(keep).reshape(-1).tolist()
            boxes = [(x, y, x + bw, y + bh) for x, y, bw, bh in xywh]
            scores = score.tolist()
            labels = [VEHICLE_CLASSES[ids[b]] for b in best]
        dets = []
        for i in keep:
            x1, y1, x2, y2 = boxes[i]
            dets.append(Detection(
                float((x1 - px) / scale), float((y1 - py) / scale),
                float((x2 - px) / scale), float((y2 - py) / scale),
                float(scores[i]), labels[i],
            ))
        return dets


def _tiles(w: int, h: int, grid: int = 2, overlap: float = 0.25) -> list[tuple[int, int, int, int]]:
    tw = int(w / (grid - (grid - 1) * overlap))
    th = int(h / (grid - (grid - 1) * overlap))
    xs = np.linspace(0, w - tw, grid).astype(int)
    ys = np.linspace(0, h - th, grid).astype(int)
    return [(x, y, x + tw, y + th) for y in ys for x in xs]


def _merge(dets: list[Detection], iou_thr: float = 0.45) -> list[Detection]:
    """NMS plus suppression of fragments mostly contained in a larger box."""
    dets = sorted(dets, key=lambda d: d.score, reverse=True)
    kept: list[Detection] = []
    for d in dets:
        dup = False
        for k in kept:
            ix = max(0.0, min(d.x2, k.x2) - max(d.x1, k.x1))
            iy = max(0.0, min(d.y2, k.y2) - max(d.y1, k.y1))
            inter = ix * iy
            if inter <= 0:
                continue
            union = d.area + k.area - inter
            if inter / union > iou_thr or inter / max(1e-6, min(d.area, k.area)) > 0.75:
                dup = True
                break
        if not dup:
            kept.append(d)
    return kept


def run_detection(model: OnnxYolo, img_bgr: np.ndarray, conf: float, tile_grid: int = 0) -> tuple[list[Detection], float]:
    """tile_grid 0/1 = full frame only; N = full frame plus an NxN grid of overlapping tiles."""
    t0 = time.perf_counter()
    dets = model.infer(img_bgr, conf)
    if tile_grid >= 2:
        h, w = img_bgr.shape[:2]
        for x1, y1, x2, y2 in _tiles(w, h, tile_grid):
            for d in model.infer(img_bgr[y1:y2, x1:x2], conf):
                # Drop boxes clipped by an interior tile edge; the full-frame or neighbouring tile pass covers them.
                edge = 2
                if (d.x1 < edge and x1 > 0) or (d.y1 < edge and y1 > 0) or \
                   (d.x2 > (x2 - x1) - edge and x2 < w) or (d.y2 > (y2 - y1) - edge and y2 < h):
                    continue
                dets.append(Detection(d.x1 + x1, d.y1 + y1, d.x2 + x1, d.y2 + y1, d.score, d.label))
        dets = _merge(dets)
    return dets, (time.perf_counter() - t0) * 1000


class DetectorPool:
    """Caches loaded ONNX sessions keyed by (model, device)."""

    def __init__(self):
        self._cache: dict[tuple[str, str], OnnxYolo] = {}
        self._lock = threading.Lock()

    def get(self, model_id: str, device: str = "cpu") -> OnnxYolo:
        with self._lock:
            if (model_id, device) not in self._cache:
                infos = {m.id: m for m in list_models()}
                if not infos:
                    raise RuntimeError(f"No detector models found in {MODELS_DIR}")
                if model_id not in infos:
                    fallback = next(iter(infos))
                    log.warning("model %s not found, falling back to %s", model_id, fallback)
                    model_id = fallback
                if (model_id, device) not in self._cache:
                    log.info("loading model %s on %s", model_id, device)
                    self._cache[(model_id, device)] = OnnxYolo(infos[model_id], device)
            return self._cache[(model_id, device)]


pool = DetectorPool()
