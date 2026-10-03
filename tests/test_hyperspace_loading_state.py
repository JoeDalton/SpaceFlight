from unittest.mock import MagicMock

import pytest

from space_flight.game.hyperspace_loading_state import (
    MAX_DT,
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
# outof phase: reveal and pop
# ---------------------------


def make_outof_state(on_reveal: MagicMock | None = None) -> HyperspaceLoadingState:
    """
    A state already settled on the outof phase (back quad visible, front
    hidden, no cross-fade running), without enter()'s shader and quad setup.
    """
    state = HyperspaceLoadingState(MagicMock(), on_reveal=on_reveal)
    state._clock = MagicMock()
    back, front = MagicMock(), MagicMock()
    back.isHidden.return_value = False
    front.isHidden.return_value = True
    state._quads = [back, front]
    state._quad_time = [0.0, 0.0]
    state._back, state._front = 0, 1
    state._transitioning = False
    state._state = "outof"
    state._revealing = False
    state._popped = False
    return state


def run_frame(state: HyperspaceLoadingState, dt: float, task: MagicMock):
    state._clock.getDt.return_value = dt
    return state._update(task)


def test_outof_reveals_once_at_reveal_start():
    """
    on_reveal fires once, on the first frame at or past REVEAL_START, while
    the overlay is still up, and never again.
    """
    on_reveal = MagicMock()
    state = make_outof_state(on_reveal)
    task = MagicMock()
    step = MAX_DT / 2

    while state._quad_time[0] + step < REVEAL_START:
        run_frame(state, step, task)
    on_reveal.assert_not_called()

    run_frame(state, step, task)
    on_reveal.assert_called_once_with()
    state.app.state_manager.pop.assert_not_called()

    run_frame(state, step, task)
    on_reveal.assert_called_once_with()


def test_outof_pops_at_outof_duration():
    """The overlay pops itself (once) when the outof phase ends."""
    state = make_outof_state(MagicMock())
    task = MagicMock()

    result = None
    for _ in range(int(OUTOF_DURATION / MAX_DT) + 2):
        result = run_frame(state, MAX_DT, task)
        if state._popped:
            break

    assert state._popped
    assert state._quad_time[0] >= OUTOF_DURATION
    assert result is task.done
    state.app.state_manager.pop.assert_called_once_with()


def test_update_clamps_frame_time():
    """
    A long stalled frame advances the animation by MAX_DT only, so it does
    not skip the rest of the outof dissolve and pop the overlay at once.
    """
    state = make_outof_state(MagicMock())
    task = MagicMock()

    run_frame(state, 5.0, task)

    assert state._quad_time[0] == pytest.approx(MAX_DT)
    assert not state._popped
