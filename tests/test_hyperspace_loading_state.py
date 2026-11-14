from unittest.mock import MagicMock

import pytest

from space_flight.fx.hyperspace_overlay import FADE_DURATION, MAX_DT
from space_flight.game import hyperspace_loading_state as loading_state
from space_flight.game.hyperspace_loading_state import (
    INSIDE_MIN_DURATION,
    INTO_DURATION,
    OUTOF_DURATION,
    REVEAL_START,
    HyperspaceLoadingState,
)


def make_state() -> HyperspaceLoadingState:
    return HyperspaceLoadingState(MagicMock(), wait_for_key=True)


def test_request_jump_out_ignored_before_awaiting():
    state = make_state()
    state._awaiting_jump = False
    state._jump_requested = False
    assert state.request_jump_out() is False
    assert not state._jump_requested


def test_request_jump_out_accepted_while_awaiting():
    state = make_state()
    state._awaiting_jump = True
    state._jump_requested = False
    assert state.request_jump_out() is True
    assert state._jump_requested


# ---------------------------
# Phase sequence (on a fake overlay)
# ---------------------------


@pytest.fixture
def make_entered_state(fake_overlay_factory, monkeypatch):
    """
    Return a function making states as enter() leaves them, drawing on a fake
    overlay, settled on a given phase.
    """

    def make(phase: str = "into", **kwargs) -> HyperspaceLoadingState:
        overlay = fake_overlay_factory()
        monkeypatch.setattr(
            loading_state, "HyperspaceOverlay", lambda *args, **kw: overlay
        )
        state = HyperspaceLoadingState(MagicMock(), **kwargs)
        state.enter()
        state._clock = MagicMock()
        overlay.show(phase)
        return state

    return make


def run_frame(state: HyperspaceLoadingState, dt: float, task: MagicMock):
    state._clock.getDt.return_value = dt
    return state._update(task)


def run_for(state: HyperspaceLoadingState, seconds: float, task: MagicMock):
    for _ in range(round(seconds / MAX_DT)):
        run_frame(state, MAX_DT, task)


def test_enter_starts_on_into(make_entered_state):
    state = make_entered_state()

    assert state._overlay.phase == "into"


def test_into_cross_fades_to_inside(make_entered_state):
    state = make_entered_state()
    task = MagicMock()

    run_for(state, INTO_DURATION + MAX_DT, task)
    assert state._overlay.transitioning

    run_for(state, FADE_DURATION + MAX_DT, task)
    assert state._overlay.phase == "inside"


def test_inside_builds_one_step_per_settled_frame(make_entered_state):
    build_step = MagicMock(return_value=True)
    state = make_entered_state("inside", build_step=build_step)
    task = MagicMock()

    run_for(state, 10 * MAX_DT, task)

    assert build_step.call_count == 10


def test_inside_drops_out_once_built_and_shown_long_enough(make_entered_state):
    on_build_complete = MagicMock()
    state = make_entered_state(
        "inside",
        build_step=MagicMock(return_value=False),
        on_build_complete=on_build_complete,
    )
    task = MagicMock()

    run_frame(state, MAX_DT, task)
    on_build_complete.assert_called_once_with()
    assert not state._overlay.transitioning

    run_for(state, INSIDE_MIN_DURATION, task)
    assert state._overlay._next_phase == "outof"


def test_inside_waits_for_the_jump_key(make_entered_state):
    state = make_entered_state("inside", wait_for_key=True)
    task = MagicMock()

    run_for(state, INSIDE_MIN_DURATION + 3.0, task)
    assert state._awaiting_jump
    assert not state._overlay.transitioning

    assert state.request_jump_out()
    run_frame(state, MAX_DT, task)
    assert not state._awaiting_jump
    assert state._overlay._next_phase == "outof"


# ---------------------------
# outof phase: reveal and pop
# ---------------------------


def test_outof_reveals_once_at_reveal_start(make_entered_state):
    """
    on_reveal fires once, on the first frame at or past REVEAL_START, while
    the overlay is still up, and never again.
    """
    on_reveal = MagicMock()
    state = make_entered_state("outof", on_reveal=on_reveal)
    task = MagicMock()
    step = MAX_DT / 2

    while state._overlay.phase_time + step < REVEAL_START:
        run_frame(state, step, task)
    on_reveal.assert_not_called()

    run_frame(state, step, task)
    on_reveal.assert_called_once_with()
    state.app.state_manager.pop.assert_not_called()

    run_frame(state, step, task)
    on_reveal.assert_called_once_with()


def test_outof_pops_at_outof_duration(make_entered_state):
    """The overlay pops itself (once) when the outof phase ends."""
    state = make_entered_state("outof", on_reveal=MagicMock())
    task = MagicMock()

    result = None
    for _ in range(int(OUTOF_DURATION / MAX_DT) + 2):
        result = run_frame(state, MAX_DT, task)
        if state._popped:
            break

    assert state._popped
    assert state._overlay.phase_time >= OUTOF_DURATION
    assert result is task.done
    state.app.state_manager.pop.assert_called_once_with()


def test_update_clamps_frame_time(make_entered_state):
    """
    A long stalled frame advances the animation by MAX_DT only, so it does
    not skip the rest of the outof dissolve and pop the overlay at once.
    """
    state = make_entered_state("outof", on_reveal=MagicMock())
    task = MagicMock()

    run_frame(state, 5.0, task)

    assert state._overlay.phase_time == pytest.approx(MAX_DT)
    assert not state._popped


def test_exit_destroys_the_overlay(make_entered_state):
    state = make_entered_state()
    quads = list(state._overlay._quads)

    state.exit()

    assert all(quad.removed for quad in quads)
