"""Discord webhook and Pushover delivery."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)


@dataclass
class Alert:
    title: str
    message: str
    color: str = "#38bdf8"
    fields: list[tuple[str, str]] = field(default_factory=list)
    now_image: bytes | None = None
    before_image: bytes | None = None
    combined_image: bytes | None = None
    url: str | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _color_int(color: str) -> int:
    try:
        return int(color.lstrip("#"), 16)
    except ValueError:
        return 0x38BDF8


async def send_discord(client: httpx.AsyncClient, cfg: dict, alert: Alert) -> str:
    url = cfg.get("discord_webhook_url")
    if not url:
        return "skipped: no webhook URL"
    embed = {
        "title": alert.title[:256],
        "description": alert.message[:4000],
        "color": _color_int(alert.color),
        "timestamp": alert.ts.isoformat(),
        "fields": [{"name": k[:256], "value": v[:1024] or "-", "inline": True} for k, v in alert.fields][:25],
        "footer": {"text": "TrafficWatch"},
    }
    if alert.url:
        embed["url"] = alert.url
    files = []
    if alert.now_image:
        embed["image"] = {"url": "attachment://now.jpg"}
        files.append(("files[0]", ("now.jpg", alert.now_image, "image/jpeg")))
    embeds = [embed]
    if alert.before_image:
        embeds.append({"title": "Previous scan", "color": 0x64748B, "image": {"url": "attachment://before.jpg"}})
        files.append(("files[1]", ("before.jpg", alert.before_image, "image/jpeg")))
    payload = {
        "username": cfg.get("discord_username") or "TrafficWatch",
        "content": cfg.get("discord_mention") or None,
        "embeds": embeds,
        "allowed_mentions": {"parse": ["roles", "users", "everyone"]},
    }
    try:
        resp = await client.post(url, data={"payload_json": json.dumps(payload)}, files=files or None, timeout=30)
    except httpx.HTTPError as e:
        return f"error: {e}"
    if resp.status_code >= 300:
        return f"error: HTTP {resp.status_code} {resp.text[:200]}"
    return "ok"


async def send_pushover(client: httpx.AsyncClient, cfg: dict, alert: Alert) -> str:
    token, user = cfg.get("pushover_app_token"), cfg.get("pushover_user_key")
    if not token or not user:
        return "skipped: missing app token or user key"
    data = {
        "token": token,
        "user": user,
        "title": alert.title[:250],
        "message": (alert.message + ("\n" + "\n".join(f"{k}: {v}" for k, v in alert.fields) if alert.fields else ""))[:1024],
        "priority": str(cfg.get("pushover_priority", 0)),
        "timestamp": str(int(alert.ts.timestamp())),
    }
    if cfg.get("pushover_sound"):
        data["sound"] = cfg["pushover_sound"]
    if cfg.get("pushover_device"):
        data["device"] = cfg["pushover_device"]
    if int(cfg.get("pushover_priority", 0)) == 2:
        # Emergency priority requires retry/expire.
        data["retry"], data["expire"] = "60", "1800"
    if alert.url:
        data["url"], data["url_title"] = alert.url, "Open in TrafficWatch"
    image = alert.combined_image or alert.now_image
    files = {"attachment": ("alert.jpg", image, "image/jpeg")} if image and len(image) < 5_000_000 else None
    try:
        resp = await client.post("https://api.pushover.net/1/messages.json", data=data, files=files, timeout=30)
    except httpx.HTTPError as e:
        return f"error: {e}"
    if resp.status_code >= 300:
        return f"error: HTTP {resp.status_code} {resp.text[:200]}"
    return "ok"


CONFIGURED = {
    "discord": lambda cfg: bool(cfg.get("discord_webhook_url")),
    "pushover": lambda cfg: bool(cfg.get("pushover_app_token") and cfg.get("pushover_user_key")),
}
SENDERS = {"discord": send_discord, "pushover": send_pushover}
NO_CHANNELS = "No notification channels are set up. Add a Discord webhook or Pushover keys in Settings."


async def deliver(client: httpx.AsyncClient, cfg: dict, alert: Alert, channels: list[str]) -> dict[str, str]:
    """Send to the rule's channels. Statuses: "ok", "off: …" (set up but switched off), "error: …".

    Channels that were never set up are left out so they don't clutter every alert.
    """
    out: dict[str, str] = {}
    for ch in ("discord", "pushover"):
        if ch not in channels:
            continue
        if cfg.get(f"{ch}_enabled"):
            out[ch] = await SENDERS[ch](client, cfg, alert)
        elif CONFIGURED[ch](cfg):
            out[ch] = "off: switched off in Settings"
    for ch, status in out.items():
        if status != "ok":
            log.warning("%s delivery: %s", ch, status)
    return out
