"""End-to-end: camera -> zones -> rule -> scans -> event -> Discord delivery."""

import os
import tempfile
from pathlib import Path

DATA = tempfile.mkdtemp(prefix="tw-test-")
os.environ["TW_DATA_DIR"] = DATA
os.environ.setdefault("TW_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "models"))

import cv2  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import monitor as monitor_mod  # noqa: E402
from app.detector import Detection, list_models  # noqa: E402
from app.main import app  # noqa: E402
from tests.test_analysis import QUEUE, road, with_cars  # noqa: E402

FRAMES: list[bytes] = []
DETS: list[list[Detection]] = []
SENT: list[httpx.Request] = []


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "cam.test":
        return httpx.Response(200, content=FRAMES[0], headers={"content-type": "image/jpeg"})
    if request.url.host == "discord.test":
        SENT.append(request)
        return httpx.Response(204)
    return httpx.Response(404)


def queue_frame(seed: int, cars: bool) -> None:
    img, dets = with_cars(road(seed), QUEUE, seed=1) if cars else (road(seed), [])
    FRAMES[:] = [cv2.imencode(".jpg", img)[1].tobytes()]
    DETS[:] = [dets]


@pytest.fixture(scope="module")
def client():
    monitor_mod.detect = lambda img, *a: (DETS[0], 1.0, "fake")
    with TestClient(app) as c:
        monitor_mod.monitor.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        yield c


def test_full_flow(client):
    cam = client.post("/api/cameras", json={"name": "Test cam", "url": "http://cam.test/a.jpg", "enabled": False}).json()
    zone = client.post(f"/api/cameras/{cam['id']}/zones", json={
        "name": "Northbound", "direction": "NB", "polygon": [[0, 0.3], [0.5, 0.3], [0.5, 1], [0, 1]],
    }).json()
    rule = client.post(f"/api/zones/{zone['id']}/rules", json={
        "name": "Reopened", "kind": "density_change", "channels": ["discord"],
        "params": {"from": ["empty"], "to": ["light", "moderate", "heavy"], "min_prior": 2},
    })
    assert rule.status_code == 200, rule.text
    client.put("/api/settings", json={"discord_enabled": True, "discord_webhook_url": "https://discord.test/hook"})

    for seed in range(3):
        queue_frame(seed, cars=False)
        r = client.post(f"/api/cameras/{cam['id']}/check").json()
        assert r["result"]["status"] == "new", r
        assert r["result"]["events"] == []

    # Same bytes again -> unchanged, nothing analysed.
    assert client.post(f"/api/cameras/{cam['id']}/check").json()["result"]["status"] == "unchanged"

    queue_frame(10, cars=True)
    r = client.post(f"/api/cameras/{cam['id']}/check").json()
    assert len(r["result"]["events"]) == 1
    latest_zone = r["camera"]["zones"][0]["latest"]
    assert latest_zone["count"] == 4 and latest_zone["density"] == "moderate"

    events = client.get("/api/events").json()
    assert events[0]["delivery"] == {"discord": "ok"}
    assert "empty → moderate" in events[0]["title"]
    body = SENT[-1].content
    assert b'filename="now.jpg"' in body and b'filename="before.jpg"' in body

    snap_id = events[0]["snapshot_id"]
    img = client.get(f"/api/snapshots/{snap_id}/annotated")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"

    hist = client.get(f"/api/zones/{zone['id']}/history").json()
    assert [h["density"] for h in hist] == ["empty", "empty", "empty", "moderate"]

    prev = client.post(f"/api/cameras/{cam['id']}/preview", json={"zones": [
        {"polygon": [[0.5, 0.3], [1, 0.3], [1, 1], [0.5, 1]]},
    ]}).json()
    assert prev["zones"][0]["count"] == 0

    sugg = client.post(f"/api/cameras/{cam['id']}/suggest-zones")
    assert sugg.status_code == 200, sugg.text

    snaps = client.get(f"/api/cameras/{cam['id']}/snapshots").json()
    assert len(snaps) == 4 and snaps[0]["observations"][0]["count"] == 4

    assert client.delete(f"/api/cameras/{cam['id']}").json()["ok"]
    assert client.get("/api/events").json() == []


@pytest.mark.skipif(not list_models(), reason="no ONNX models available")
def test_lab_runs_real_models(client):
    queue_frame(3, cars=True)
    r = client.post("/api/lab/run", json={"url": "http://cam.test/a.jpg", "models": [list_models()[0].id], "grids": [0], "runs": 1})
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["ms_median"] > 0


def test_enabled_camera_is_scheduled_and_scanned(client):
    import time
    queue_frame(42, cars=True)
    cam = client.post("/api/cameras", json={"name": "Auto", "url": "http://cam.test/b.jpg", "interval_sec": 60})
    assert cam.status_code == 200, cam.text
    cid = cam.json()["id"]
    for _ in range(50):
        latest = client.get(f"/api/cameras/{cid}").json()["latest"]
        if latest:
            break
        time.sleep(0.1)
    assert latest and latest["vehicle_count"] == 4
    assert client.put(f"/api/cameras/{cid}", json={"name": "Auto", "url": "http://cam.test/b.jpg", "enabled": False}).status_code == 200
    client.delete(f"/api/cameras/{cid}")


def test_ids_not_reused_after_delete_and_images_cache_safely(client):
    """Deleting the newest camera must not let a new camera inherit its snapshot ids,
    or the browser would show the old camera's cached image."""
    queue_frame(50, cars=False)
    a = client.post("/api/cameras", json={"name": "A", "url": "http://cam.test/a.jpg", "enabled": False}).json()
    snap_a = client.post(f"/api/cameras/{a['id']}/check").json()["camera"]["latest"]
    client.delete(f"/api/cameras/{a['id']}")
    queue_frame(51, cars=True)
    b = client.post("/api/cameras", json={"name": "B", "url": "http://cam.test/b.jpg", "enabled": False}).json()
    snap_b = client.post(f"/api/cameras/{b['id']}/check").json()["camera"]["latest"]
    assert b["id"] > a["id"] and snap_b["id"] > snap_a["id"]

    pinned = client.get(f"/api/snapshots/{snap_b['id']}/image?v={snap_b['sha']}")
    assert "immutable" in pinned.headers["cache-control"]
    assert client.get(f"/api/snapshots/{snap_b['id']}/image").headers["cache-control"] == "no-cache"
    assert client.get(f"/api/snapshots/{snap_b['id']}/image?v=deadbeefdead").headers["cache-control"] == "no-cache"
    client.delete(f"/api/cameras/{b['id']}")


def test_delivery_reports_switched_off_channels():
    import asyncio

    from app.notify import Alert, deliver

    async def run(cfg, channels):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await deliver(c, cfg, Alert("t", "m"), channels)

    hook = {"discord_webhook_url": "https://discord.test/hook"}
    assert asyncio.run(run({**hook, "discord_enabled": False}, ["discord", "pushover"])) == {"discord": "off: switched off in Settings"}
    assert asyncio.run(run({**hook, "discord_enabled": True}, ["discord", "pushover"])) == {"discord": "ok"}
    # Never set up -> left out entirely; rule not sending to a channel -> left out.
    assert asyncio.run(run({}, ["discord", "pushover"])) == {}
    assert asyncio.run(run({**hook, "discord_enabled": True}, ["pushover"])) == {}


def test_rule_test_button_sends_to_discord(client):
    """The rule's test button builds an unsaved event; it must still deliver with images."""
    queue_frame(60, cars=True)
    cam = client.post("/api/cameras", json={"name": "T", "url": "http://cam.test/t.jpg", "enabled": False}).json()
    client.post(f"/api/cameras/{cam['id']}/check")
    zone = client.post(f"/api/cameras/{cam['id']}/zones", json={"name": "SB", "polygon": [[0, 0.3], [0.5, 0.3], [0.5, 1], [0, 1]]}).json()
    rule = client.post(f"/api/zones/{zone['id']}/rules", json={
        "kind": "motion_change", "channels": ["discord"], "params": {"from": ["stopped"], "to": ["moving"]},
    }).json()
    client.put("/api/settings", json={"discord_enabled": True, "discord_webhook_url": "https://discord.test/hook"})
    sent_before = len(SENT)
    r = client.post(f"/api/rules/{rule['id']}/test")
    assert r.status_code == 200, r.text
    assert r.json()["delivery"] == {"discord": "ok"}
    assert len(SENT) == sent_before + 1 and b'filename="now.jpg"' in SENT[-1].content
    # Settings-page test path as well.
    assert client.post("/api/settings/test/discord", json={}).json()["result"] == "ok"
    client.delete(f"/api/cameras/{cam['id']}")
