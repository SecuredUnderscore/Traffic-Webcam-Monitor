from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import TypeDecorator

DATA_DIR = Path(os.environ.get("TW_DATA_DIR", "/data"))
SNAPSHOT_DIR = DATA_DIR / "snapshots"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TZDateTime(TypeDecorator):
    """SQLite drops tzinfo; store naive UTC and hand back aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


# AUTOINCREMENT stops SQLite from handing out an id again after the highest row is
# deleted. Reused ids are dangerous here: images are cached by snapshot id.
NO_ID_REUSE = {"sqlite_autoincrement": True}


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Camera(Base):
    __tablename__ = "cameras"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    interval_sec: Mapped[int] = mapped_column(Integer, default=300)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    cache_bust: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Per-camera detector overrides; None means use the global setting.
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tile_grid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    # Runtime state maintained by the monitor.
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_new_image_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    zones: Mapped[list[Zone]] = relationship(back_populates="camera", cascade="all, delete-orphan", order_by="Zone.id")


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(40), default="")
    color: Mapped[str] = mapped_column(String(16), default="#38bdf8")
    # Polygon as [[x, y], ...] with coordinates normalised to 0..1.
    polygon: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # "count" (vehicle detections) or "activity" (% of zone that differs from the learned empty road).
    metric: Mapped[str] = mapped_column(String(16), default="count")
    # Upper bounds for empty / light / moderate; anything above is heavy.
    thresholds: Mapped[dict] = mapped_column(JSON, default=dict)
    min_vehicles_for_motion: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    camera: Mapped[Camera] = relationship(back_populates="zones")
    rules: Mapped[list[Rule]] = relationship(back_populates="zone", cascade="all, delete-orphan", order_by="Rule.id")


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    kind: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    cooldown_min: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["discord", "pushover"])
    last_fired_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)

    zone: Mapped[Zone] = relationship(back_populates="rules")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    path: Mapped[str] = mapped_column(Text)
    sha: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    detections: Mapped[list] = mapped_column(JSON, default=list)
    inference_ms: Mapped[float] = mapped_column(Float, default=0)
    model_id: Mapped[str] = mapped_column(String(64), default="")
    view_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    view_shift: Mapped[bool] = mapped_column(Boolean, default=False)
    brightness: Mapped[float] = mapped_column(Float, default=0)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    occupancy: Mapped[float] = mapped_column(Float, default=0)
    activity: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    stationary: Mapped[float | None] = mapped_column(Float, nullable=True)
    density: Mapped[str] = mapped_column(String(16))
    motion: Mapped[str] = mapped_column(String(16))
    light_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = NO_ID_REUSE
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id", ondelete="CASCADE"), index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id", ondelete="SET NULL"), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prev_snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


engine = None
SessionLocal: sessionmaker | None = None


def init_db(path: Path | None = None) -> None:
    global engine, SessionLocal
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = path or DATA_DIR / "trafficwatch.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    _migrate_autoincrement(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _migrate_autoincrement(eng) -> None:
    """Rebuild tables created before AUTOINCREMENT was enabled (v1.0.0 databases)."""
    with eng.connect() as conn:
        existing = dict(conn.exec_driver_sql("SELECT name, sql FROM sqlite_master WHERE type='table'").all())
        todo = [t for t in Base.metadata.sorted_tables
                if t.dialect_options["sqlite"]["autoincrement"] and "AUTOINCREMENT" not in (existing.get(t.name) or "AUTOINCREMENT")]
        if not todo:
            return
        # FKs off and legacy rename so other tables' references aren't rewritten to the _old copy.
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
        try:
            for t in todo:
                for (idx,) in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (t.name,)
                ).all():
                    conn.exec_driver_sql(f'DROP INDEX "{idx}"')
                conn.exec_driver_sql(f'ALTER TABLE "{t.name}" RENAME TO "{t.name}_old"')
                t.create(conn)
                cols = ", ".join(f'"{c.name}"' for c in t.columns)
                conn.exec_driver_sql(f'INSERT INTO "{t.name}" ({cols}) SELECT {cols} FROM "{t.name}_old"')
                conn.exec_driver_sql(f'DROP TABLE "{t.name}_old"')
            conn.commit()
        finally:
            conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def session():
    assert SessionLocal is not None, "init_db() not called"
    return SessionLocal()
