import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app import db


def test_v1_database_is_migrated_to_autoincrement(tmp_path):
    """Databases from v1.0.0 lack AUTOINCREMENT; init_db rebuilds tables keeping data and FKs."""
    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        for t in db.Base.metadata.sorted_tables:
            conn.exec_driver_sql(str(CreateTable(t).compile(eng)).replace(" AUTOINCREMENT", ""))
            for idx in t.indexes:
                conn.exec_driver_sql(str(CreateIndex(idx).compile(eng)))
        conn.exec_driver_sql("INSERT INTO cameras (id, name, url, interval_sec, enabled, headers, cache_bust, notes, consecutive_errors, created_at) "
                             "VALUES (1, 'Old cam', 'http://x/y.jpg', 300, 1, '{}', 0, '', 0, '2026-10-16 00:00:00')")
        conn.exec_driver_sql("INSERT INTO zones (id, camera_id, name, direction, color, polygon, enabled, metric, thresholds, min_vehicles_for_motion, created_at) "
                             "VALUES (1, 1, 'NB', 'NB', '#fff', '[[0,0],[1,0],[1,1]]', 1, 'count', '{}', 2, '2026-10-16 00:00:00')")
    eng.dispose()

    db.init_db(path)

    raw = sqlite3.connect(path)
    sql = dict(raw.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall())
    assert "AUTOINCREMENT" in sql["cameras"] and "AUTOINCREMENT" in sql["snapshots"]
    assert not any(n.endswith("_old") for n in sql)
    assert 'REFERENCES cameras' in sql["zones"] or 'REFERENCES "cameras"' in sql["zones"]
    assert raw.execute("SELECT name FROM cameras").fetchall() == [("Old cam",)]
    assert raw.execute("SELECT name FROM zones").fetchall() == [("NB",)]
    assert raw.execute("PRAGMA foreign_key_check").fetchall() == []
    raw.close()

    # Deleting the only camera then adding another must not reuse id 1.
    with db.session() as s:
        s.delete(s.get(db.Camera, 1))
        s.commit()
        cam = db.Camera(name="New", url="http://x/z.jpg")
        s.add(cam)
        s.commit()
        assert cam.id == 2
