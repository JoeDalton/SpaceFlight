"""
Unit tests for the generic StateMachine and Cooldown (space_flight.utils.state_machine).

A tiny mutable clock lets each test advance time deterministically.
"""

import pytest

from space_flight.utils.state_machine import Cooldown, StateMachine


class Clock:
    """A controllable time source."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float):
        self.t += dt


# ---------------------------------------------------------------------------
# StateMachine basics
# ---------------------------------------------------------------------------


def test_initial_state_and_time():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock)

    assert sm.state == "a"
    assert sm.previous_state is None
    assert sm.time_in_state_s == pytest.approx(0.0)

    clock.advance(2.5)
    assert sm.time_in_state_s == pytest.approx(2.5)


def test_request_changes_state_and_resets_timer():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock)
    clock.advance(3.0)

    changed = sm.request("b")

    assert changed is True
    assert sm.state == "b"
    assert sm.previous_state == "a"
    assert sm.time_in_state_s == pytest.approx(0.0)


def test_request_same_state_is_noop():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock)
    clock.advance(1.0)

    assert sm.request("a") is False
    assert sm.time_in_state_s == pytest.approx(1.0)  # timer not reset


# ---------------------------------------------------------------------------
# StateMachine commitment gate
# ---------------------------------------------------------------------------


def test_commitment_refuses_early_transition():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock, commit_times=5.0)

    clock.advance(2.0)  # below the 5s commit
    assert sm.is_committed() is False
    assert sm.request("b") is False
    assert sm.state == "a"

    clock.advance(4.0)  # now 6s in state
    assert sm.is_committed() is True
    assert sm.request("b") is True
    assert sm.state == "b"


def test_force_overrides_commitment():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock, commit_times=5.0)
    clock.advance(1.0)

    assert sm.request("b", force=True) is True
    assert sm.state == "b"


def test_per_state_commit_times_dict():
    clock = Clock()
    sm = StateMachine(
        initial_state="a", clock=clock, commit_times={"a": 1.0, "b": 10.0}
    )
    assert sm.commit_time_s() == pytest.approx(1.0)
    assert sm.commit_time_s("b") == pytest.approx(10.0)
    assert sm.commit_time_s("missing") == pytest.approx(0.0)  # unlisted -> no dwell


def test_none_commit_times_always_committed():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock, commit_times=None)
    assert sm.is_committed() is True
    assert sm.request("b") is True


# ---------------------------------------------------------------------------
# StateMachine hooks and reset
# ---------------------------------------------------------------------------


def test_enter_and_exit_hooks_fire_in_order():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock)
    events = []
    sm.on_exit("a", lambda: events.append("exit_a"))
    sm.on_enter("b", lambda: events.append("enter_b"))

    sm.request("b")

    assert events == ["exit_a", "enter_b"]


def test_hooks_do_not_fire_on_refused_transition():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock, commit_times=5.0)
    fired = []
    sm.on_exit("a", lambda: fired.append("exit_a"))

    sm.request("b")  # refused (not committed)

    assert fired == []


def test_reset_timer():
    clock = Clock()
    sm = StateMachine(initial_state="a", clock=clock)
    clock.advance(3.0)
    assert sm.time_in_state_s == pytest.approx(3.0)

    sm.reset_timer()

    assert sm.state == "a"  # unchanged
    assert sm.time_in_state_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


def test_cooldown_ready_at_start_by_default():
    clock = Clock()
    cd = Cooldown(duration_s=5.0, clock=clock)
    assert cd.ready() is True


def test_cooldown_not_ready_at_start_when_requested():
    clock = Clock()
    cd = Cooldown(duration_s=5.0, clock=clock, ready_at_start=False)
    assert cd.ready() is False


def test_cooldown_ready_after_duration():
    clock = Clock()
    cd = Cooldown(duration_s=5.0, clock=clock)
    cd.trigger()

    assert cd.ready() is False
    clock.advance(4.0)
    assert cd.ready() is False
    clock.advance(2.0)  # 6s total
    assert cd.ready() is True


def test_cooldown_multiplier_lengthens():
    clock = Clock()
    cd = Cooldown(duration_s=5.0, clock=clock)
    cd.trigger()
    clock.advance(6.0)

    assert cd.ready(multiplier=1.0) is True
    assert cd.ready(multiplier=2.0) is False  # needs 10s
    clock.advance(5.0)  # 11s total
    assert cd.ready(multiplier=2.0) is True
