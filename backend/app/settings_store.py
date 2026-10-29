"""App settings live in the database and are edited from the web UI."""

from __future__ import annotations

import os

from . import db

DEFAULTS: dict[str, object] = {
    # Discord
    "discord_enabled": False,
    "discord_webhook_url": "",
    "discord_username": "Traffic Webcam Monitor",
    "discord_mention": "",
    # Pushover
    "pushover_enabled": False,
    "pushover_app_token": "",
    "pushover_user_key": "",
    "pushover_priority": 0,
    "pushover_sound": "",
    "pushover_device": "",
    # Notification content
    "send_before_image": True,
    "app_base_url": "",
    # Detector
    "detector_model": "yolo11s",
    "detector_device": "cpu",
    "detector_conf": 0.25,
    "detector_tile_grid": 2,
    # Housekeeping
    "retention_hours": 72,
    "event_retention_days": 30,
    # Cap on everything stored in the data directory; hosting plans often have small disks.
    "storage_limit_mb": int(os.environ.get("TW_STORAGE_LIMIT_MB", 400)),
}

MIN_STORAGE_LIMIT_MB = 50

SECRET_KEYS = {"discord_webhook_url", "pushover_app_token", "pushover_user_key"}


def get_all() -> dict[str, object]:
    with db.session() as s:
        stored = {row.key: row.value for row in s.query(db.Setting).all()}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def get(key: str):
    return get_all()[key]


def update(values: dict[str, object]) -> dict[str, object]:
    with db.session() as s:
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            default = DEFAULTS[key]
            # Coerce to the default's type so the UI can send strings for numbers.
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            elif isinstance(default, str):
                value = "" if value is None else str(value).strip()
            if key == "storage_limit_mb":
                value = max(MIN_STORAGE_LIMIT_MB, value)
            row = s.get(db.Setting, key)
            if row is None:
                s.add(db.Setting(key=key, value=value))
            else:
                row.value = value
        s.commit()
    return get_all()
