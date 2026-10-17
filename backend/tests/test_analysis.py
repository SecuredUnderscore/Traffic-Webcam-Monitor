import cv2
import numpy as np

from app.analysis import CameraMemory, ZoneSpec, analyze
from app.detector import Detection

W, H = 400, 300
LEFT = ZoneSpec(1, [[0.0, 0.3], [0.5, 0.3], [0.5, 1.0], [0.0, 1.0]])
RIGHT = ZoneSpec(2, [[0.5, 0.3], [1.0, 0.3], [1.0, 1.0], [0.5, 1.0]])


def road(seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 90, np.uint8)
    img[: int(H * 0.3)] = (200, 160, 120)  # sky
    cv2.line(img, (W // 2, int(H * 0.3)), (W // 2, H), (230, 230, 230), 2)
    # Static scenery: lane dashes, a sign gantry, roadside poles.
    for y in range(int(H * 0.35), H, 30):
        cv2.line(img, (W // 4, y), (W // 4, y + 12), (220, 220, 220), 2)
        cv2.line(img, (3 * W // 4, y), (3 * W // 4, y + 12), (220, 220, 220), 2)
    cv2.rectangle(img, (20, 40), (380, 60), (60, 120, 60), -1)
    for x in (10, 390):
        cv2.line(img, (x, 40), (x, 140), (40, 40, 40), 3)
    img = np.clip(img.astype(int) + rng.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)
    return img


def with_cars(img, boxes, seed=0):
    rng = np.random.default_rng(seed)
    out = img.copy()
    dets = []
    for (x, y, w, h) in boxes:
        # Cars contrast with the grey road: dark or bright paint.
        color = tuple(int(c) for c in (rng.integers(0, 40, 3) if rng.random() < 0.5 else rng.integers(190, 255, 3)))
        cv2.rectangle(out, (x, y), (x + w, y + h), color, -1)
        cv2.rectangle(out, (x + 3, y + 3), (x + w // 2, y + h // 2), (20, 20, 20), -1)
        dets.append(Detection(x, y, x + w, y + h, 0.9, "car"))
    return out, dets


QUEUE = [(30, 120, 40, 25), (90, 160, 40, 25), (40, 210, 45, 28), (120, 240, 45, 28)]


def test_counts_use_ground_point_per_zone():
    img, dets = with_cars(road(), QUEUE + [(260, 150, 40, 25)])
    fa = analyze(img, dets, [LEFT, RIGHT], CameraMemory())
    by = {z.zone_id: z for z in fa.zones}
    assert by[1].count == 4 and by[2].count == 1
    assert by[1].density == "moderate" and by[2].density == "light"


def test_same_vehicles_in_same_place_means_stopped():
    mem = CameraMemory()
    base = road()
    img, dets = with_cars(base, QUEUE, seed=1)
    analyze(img, dets, [LEFT], mem)
    img2, dets2 = with_cars(road(seed=5), QUEUE, seed=1)  # same cars, new sensor noise
    z = analyze(img2, dets2, [LEFT], mem).zones[0]
    assert z.stationary == 1.0
    assert z.motion == "stopped"


def test_different_vehicles_means_moving():
    mem = CameraMemory()
    img, dets = with_cars(road(), QUEUE, seed=1)
    analyze(img, dets, [LEFT], mem)
    moved = [(x + 60 if x < 100 else x - 70, y + 15, w, h) for (x, y, w, h) in QUEUE]
    img2, dets2 = with_cars(road(seed=2), moved, seed=9)
    z = analyze(img2, dets2, [LEFT], mem).zones[0]
    assert z.stationary is not None and z.stationary < 0.3
    assert z.motion == "moving"


def test_empty_zone_has_no_motion():
    img = road()
    z = analyze(img, [], [LEFT], CameraMemory()).zones[0]
    assert z.density == "empty" and z.motion == "none"


def test_activity_detects_vehicles_without_detections():
    """Vehicles too small to detect still register as activity against the learned background."""
    mem = CameraMemory()
    for i in range(5):
        analyze(road(seed=i), [], [LEFT], mem)
    img, _ = with_cars(road(seed=7), QUEUE, seed=3)
    z = analyze(img, [], [ZoneSpec(1, LEFT.polygon, metric="activity")], mem).zones[0]
    assert z.activity is not None and z.activity > 5
    assert z.density != "empty"


def test_view_shift_detected_when_camera_moves():
    mem = CameraMemory()
    analyze(road(), [], [LEFT], mem)
    other = np.full((H, W, 3), 60, np.uint8)
    for i in range(0, W, 25):
        cv2.line(other, (i, 0), (W - i, H), (220, 220, 220), 2)
    fa = analyze(other, [], [LEFT], mem)
    assert fa.view_shift
    same = analyze(other, [], [LEFT], mem)
    assert not same.view_shift
