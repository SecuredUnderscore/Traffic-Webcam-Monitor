"""Alert rules evaluated against a zone's observation history.

Rules look at the sequence of scans, not just the latest frame, so they can
express "this direction was empty for the last 3 scans and now has traffic"
or "traffic was stopped for 2 scans and is now moving".

Rule kinds and params:

density_change   {"from": [levels], "to": [levels], "min_prior": int, "confirm": int}
motion_change    {"from": [states], "to": [states], "min_prior": int, "confirm": int}
count_threshold  {"op": "above"|"below", "value": number, "scans": int}
activity_threshold  same as count_threshold, on activity %

min_prior: scans the old state must have held. confirm: scans the new state
must hold before alerting (1 = alert on the first scan that shows it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

RULE_KINDS = ["density_change", "motion_change", "count_threshold", "activity_threshold"]

LABELS = {
    "empty": "empty", "light": "light", "moderate": "moderate", "heavy": "heavy",
    "none": "no traffic", "stopped": "stopped", "slow": "slow / partly stopped", "moving": "moving",
}


@dataclass
class Obs:
    """The fields of an Observation that rules need."""

    count: int
    activity: float | None
    density: str
    motion: str


@dataclass
class Trigger:
    title: str
    detail: str


def _transition(history: list[Obs], attr: str, params: dict) -> Trigger | None:
    src, dst = set(params.get("from") or []), set(params.get("to") or [])
    min_prior = max(1, int(params.get("min_prior", 1)))
    confirm = max(1, int(params.get("confirm", 1)))
    # Scans where the state couldn't be determined don't break or count toward a run.
    known = [getattr(o, attr) for o in history if getattr(o, attr) != "unknown"]
    if not known or getattr(history[-1], attr) == "unknown":
        return None
    cur = known[-1]
    after = known[-confirm:]
    prior = known[-confirm - min_prior:-confirm]
    if len(after) < confirm or not all(a in dst for a in after):
        return None
    if len(prior) < min_prior or not all(p in src for p in prior):
        return None
    before = prior[-1]
    noun = "Traffic" if attr == "density" else "Flow"
    return Trigger(
        f"{noun}: {LABELS.get(before, before)} → {LABELS.get(cur, cur)}",
        f"Was {LABELS.get(before, before)} for {len(prior)}+ scans, now {LABELS.get(cur, cur)}"
        + (f" for {confirm} scans." if confirm > 1 else "."),
    )


def _threshold(history: list[Obs], attr: str, params: dict) -> Trigger | None:
    op = params.get("op", "above")
    value = float(params.get("value", 0))
    scans = max(1, int(params.get("scans", 1)))
    vals = [getattr(o, attr) for o in history]
    if len(vals) < scans + 1 or any(v is None for v in vals[-scans - 1:]):
        return None

    def hit(v: float) -> bool:
        return v > value if op == "above" else v < value

    window, before = vals[-scans:], vals[-scans - 1]
    # Edge-triggered: fire when the condition starts holding, not on every scan it holds.
    if not all(hit(v) for v in window) or hit(before):
        return None
    unit = " vehicles" if attr == "count" else "% activity"
    cur = vals[-1]
    cur_s = f"{cur:g}" if attr == "count" else f"{cur:.1f}"
    return Trigger(
        f"{'Above' if op == 'above' else 'Below'} {value:g}{unit}",
        f"Now {cur_s}{unit} ({scans} scan{'s' if scans > 1 else ''} {op} {value:g}).",
    )


def evaluate(kind: str, params: dict, history: list[Obs]) -> Trigger | None:
    """history is oldest-first and ends with the scan that was just taken."""
    if not history:
        return None
    if kind == "density_change":
        return _transition(history, "density", params)
    if kind == "motion_change":
        return _transition(history, "motion", params)
    if kind == "count_threshold":
        return _threshold(history, "count", params)
    if kind == "activity_threshold":
        return _threshold(history, "activity", params)
    return None


def history_needed(kind: str, params: dict) -> int:
    if kind in ("density_change", "motion_change"):
        # Extra room for skipped "unknown" scans.
        return (int(params.get("min_prior", 1)) + int(params.get("confirm", 1))) * 3 + 4
    return int(params.get("scans", 1)) + 2


def in_cooldown(last_fired: datetime | None, cooldown_min: int, now: datetime) -> bool:
    return last_fired is not None and now - last_fired < timedelta(minutes=cooldown_min)
