"""
Unit tests for the generic StateMachine, Cooldown and DyingPhase
(space_flight.utils.state_machine).

A tiny mutable clock lets each test advance time deterministically.
"""

import pytest

from space_flight.utils.state_machine import Cooldown, DyingPhase, StateMachine


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


# ---------------------------------------------------------------------------
# DyingPhase
# ---------------------------------------------------------------------------


class RaisingClock:
    """A clock that fails if read — proves a path never touches the clock."""

    def __call__(self) -> float:
        raise AssertionError("clock should not be read on this path")


def test_dying_phase_starts_not_dying():
    phase = DyingPhase(clock=Clock())
    assert phase.is_dying is False
    assert phase.elapsed_s() == pytest.approx(0.0)


def test_begin_marks_dying_and_returns_true():
    clock = Clock()
    phase = DyingPhase(clock=clock)

    started = phase.begin()

    assert started is True
    assert phase.is_dying is True


def test_begin_is_idempotent():
    clock = Clock()
    phase = DyingPhase(clock=clock)
    phase.begin()
    clock.advance(2.0)

    # A second begin does nothing and does NOT restart the clock.
    assert phase.begin() is False
    assert phase.elapsed_s() == pytest.approx(2.0)


def test_elapsed_zero_before_begin_then_tracks_clock():
    clock = Clock()
    phase = DyingPhase(clock=clock)

    clock.advance(3.0)
    assert phase.elapsed_s() == pytest.approx(0.0)  # not started yet

    phase.begin()
    assert phase.elapsed_s() == pytest.approx(0.0)  # begins at "now"
    clock.advance(1.5)
    assert phase.elapsed_s() == pytest.approx(1.5)


def test_elapsed_counts_from_first_begin_not_reset():
    clock = Clock(t=10.0)
    phase = DyingPhase(clock=clock)
    phase.begin()  # started at t=10
    clock.advance(4.0)  # t=14
    phase.begin()  # idempotent, does not re-stamp

    assert phase.elapsed_s() == pytest.approx(4.0)


def test_finished_after_duration_elapses():
    clock = Clock()
    phase = DyingPhase(clock=clock)
    phase.begin()

    assert phase.finished(2.5) is False
    clock.advance(2.0)
    assert phase.finished(2.5) is False
    clock.advance(1.0)  # 3.0 total
    assert phase.finished(2.5) is True


def test_finished_is_false_before_begin_for_positive_duration():
    clock = Clock()
    phase = DyingPhase(clock=clock)
    clock.advance(100.0)  # time passing without begin() must not count
    assert phase.finished(1.0) is False


def test_finished_zero_duration_is_immediate_and_clockless():
    # The legacy "reap the frame health hits zero" path: a non-positive duration
    # finishes at once and must never read the clock.
    phase = DyingPhase(clock=RaisingClock())
    assert phase.finished(0.0) is True
    assert phase.finished(-1.0) is True
