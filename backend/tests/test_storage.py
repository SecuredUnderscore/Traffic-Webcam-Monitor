from datetime import datetime, timedelta, timezone

import pytest

from app import db, storage

KB = 1024
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


@pytest.fixture
def data(tmp_path, monkeypatch):
    """A camera with ten 50 KB scans; scan 2 (and its previous, 1) belong to an alert, 10 is the latest."""
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(storage, "_used", None)
    db.init_db()
    folder = db.SNAPSHOT_DIR / "1"
    folder.mkdir()
    with db.session() as s:
        s.add(db.Camera(id=1, name="Cam", url="http://x/y.jpg"))
        for i in range(1, 11):
            path = folder / f"{i}.jpg"
            path.write_bytes(b"\0" * 50 * KB)
            s.add(db.Snapshot(id=i, camera_id=1, ts=T0 + timedelta(minutes=i), path=str(path), sha="", width=1, height=1))
        s.add(db.Event(camera_id=1, ts=T0, title="t", message="m", snapshot_id=2, prev_snapshot_id=1))
        s.get(db.Camera, 1).last_snapshot_id = 10
        s.commit()
    return tmp_path


def remaining() -> list[int]:
    with db.session() as s:
        return [sid for (sid,) in s.query(db.Snapshot.id).order_by(db.Snapshot.id)]


def test_under_limit_deletes_nothing(data):
    assert storage.enforce(force=True)["snapshots_deleted"] == 0
    assert remaining() == list(range(1, 11))


def test_oldest_unreferenced_scans_go_first(data, monkeypatch):
    used = storage.dir_size(data)
    monkeypatch.setattr(storage, "limit_bytes", lambda: used - 120 * KB)

    result = storage.enforce(force=True)

    assert result["events_deleted"] == 0
    left = remaining()
    assert {1, 2, 10} <= set(left), "alert images and the latest frame are kept"
    deleted = sorted(set(range(1, 11)) - set(left))
    assert deleted == list(range(3, 3 + len(deleted))), "oldest first"
    assert sorted(p.stem for p in (db.SNAPSHOT_DIR / "1").iterdir()) == sorted(map(str, left))
    assert storage.dir_size(data) <= used - 120 * KB


def test_alerts_are_dropped_when_images_alone_are_not_enough(data, monkeypatch):
    monkeypatch.setattr(storage, "limit_bytes", lambda: 60 * KB)

    result = storage.enforce(force=True)

    assert result["events_deleted"] == 1
    assert remaining() == [10], "a camera's latest frame is never deleted"
    with db.session() as s:
        assert s.query(db.Event).count() == 0


def test_limit_setting_has_a_floor(data):
    from app import settings_store

    assert settings_store.update({"storage_limit_mb": "5"})["storage_limit_mb"] == settings_store.MIN_STORAGE_LIMIT_MB
    assert settings_store.get("storage_limit_mb") == 50
    assert storage.usage()["limit"] == 50 * storage.MB
