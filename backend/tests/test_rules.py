from app.rules import Obs, evaluate


def seq(*states, attr="density"):
    out = []
    for st in states:
        if attr == "density":
            out.append(Obs(count=0 if st == "empty" else 5, activity=None, density=st, motion="unknown"))
        else:
            out.append(Obs(count=5, activity=None, density="moderate", motion=st))
    return out


EMPTY_TO_TRAFFIC = {"from": ["empty"], "to": ["light", "moderate", "heavy"], "min_prior": 3}


def test_density_change_fires_after_sustained_empty():
    t = evaluate("density_change", EMPTY_TO_TRAFFIC, seq("empty", "empty", "empty", "light"))
    assert t is not None
    assert "empty" in t.title and "light" in t.title


def test_density_change_needs_enough_prior_scans():
    assert evaluate("density_change", EMPTY_TO_TRAFFIC, seq("empty", "empty", "light")) is None
    assert evaluate("density_change", EMPTY_TO_TRAFFIC, seq("light", "empty", "empty", "light")) is None


def test_density_change_only_fires_on_the_transition_scan():
    assert evaluate("density_change", EMPTY_TO_TRAFFIC, seq("empty", "empty", "empty", "light", "light")) is None


def test_unknown_scans_are_skipped_not_reset():
    assert evaluate("density_change", EMPTY_TO_TRAFFIC, seq("empty", "unknown", "empty", "empty", "heavy")) is not None
    # Current scan unknown -> nothing.
    assert evaluate("density_change", EMPTY_TO_TRAFFIC, seq("empty", "empty", "empty", "unknown")) is None


def test_motion_stopped_to_moving():
    p = {"from": ["stopped"], "to": ["moving", "slow"], "min_prior": 2}
    assert evaluate("motion_change", p, seq("stopped", "stopped", "moving", attr="motion")) is not None
    assert evaluate("motion_change", p, seq("moving", "stopped", "moving", attr="motion")) is None
    assert evaluate("motion_change", p, seq("stopped", "unknown", "stopped", "slow", attr="motion")) is not None


def test_count_threshold_is_edge_triggered():
    p = {"op": "above", "value": 10, "scans": 2}
    mk = lambda *c: [Obs(count=x, activity=None, density="heavy", motion="moving") for x in c]  # noqa: E731
    assert evaluate("count_threshold", p, mk(3, 12, 14)) is not None
    assert evaluate("count_threshold", p, mk(12, 12, 14)) is None  # already above before
    assert evaluate("count_threshold", p, mk(3, 4, 14)) is None  # only one scan above
    below = {"op": "below", "value": 1, "scans": 1}
    assert evaluate("count_threshold", below, mk(5, 0)) is not None


def test_activity_threshold_ignores_missing_values():
    p = {"op": "above", "value": 5, "scans": 1}
    obs = [Obs(0, None, "unknown", "unknown"), Obs(0, 9.0, "light", "moving")]
    assert evaluate("activity_threshold", p, obs) is None
    obs = [Obs(0, 1.0, "empty", "none"), Obs(0, 9.0, "light", "moving")]
    assert evaluate("activity_threshold", p, obs) is not None


def test_confirm_requires_new_state_to_hold():
    p = {"from": ["moving", "slow"], "to": ["stopped"], "min_prior": 2, "confirm": 2}
    s = lambda *x: seq(*x, attr="motion")  # noqa: E731
    assert evaluate("motion_change", p, s("moving", "moving", "stopped")) is None
    t = evaluate("motion_change", p, s("moving", "moving", "stopped", "stopped"))
    assert t is not None and "for 2 scans" in t.detail
    # Fires once: a third stopped scan doesn't re-trigger.
    assert evaluate("motion_change", p, s("moving", "moving", "stopped", "stopped", "stopped")) is None
    # A blip back to moving resets it.
    assert evaluate("motion_change", p, s("moving", "moving", "stopped", "moving", "stopped")) is None
