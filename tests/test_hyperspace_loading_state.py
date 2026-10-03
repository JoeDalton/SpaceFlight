from unittest.mock import MagicMock

from space_flight.game.hyperspace_loading_state import HyperspaceLoadingState


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
