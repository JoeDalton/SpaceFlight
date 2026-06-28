"""
Unit tests for the StateManager stack lifecycle.

Uses lightweight mock state classes that record lifecycle calls without
requiring any Panda3D initialisation.
"""
from unittest.mock import MagicMock

import pytest

from space_flight.global_architecture.simulator import StateManager

# ---------------------------------------------------------------------------
# Mock state helpers
# ---------------------------------------------------------------------------


class _MockState:
    """Minimal state class that tracks lifecycle call counts."""

    PAUSES_BELOW = True

    def __init__(self, app):
        self.app = app
        self.enter_count = 0
        self.exit_count = 0
        self.pause_count = 0
        self.resume_count = 0

    def enter(self):
        self.enter_count += 1

    def exit(self):
        self.exit_count += 1

    def pause(self):
        self.pause_count += 1

    def resume(self):
        self.resume_count += 1


class _OverlayState(_MockState):
    """State that does not pause the state below it."""

    PAUSES_BELOW = False


@pytest.fixture
def manager():
    """Empty StateManager backed by a MagicMock app."""
    return StateManager(app=MagicMock())


# ---------------------------------------------------------------------------
# get_current
# ---------------------------------------------------------------------------


def test_get_current_empty_stack_returns_none(manager):
    assert manager.get_current() is None


def test_get_current_returns_topmost_state(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    assert isinstance(manager.get_current(), _MockState)
    assert len(manager.stack) == 2


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


def test_push_adds_state_to_stack(manager):
    manager.push(_MockState)
    assert len(manager.stack) == 1


def test_push_calls_enter_on_new_state(manager):
    manager.push(_MockState)
    assert manager.get_current().enter_count == 1


def test_push_pauses_previous_state_when_pauses_below_true(manager):
    manager.push(_MockState)
    previous = manager.get_current()
    manager.push(_MockState)
    assert previous.pause_count == 1


def test_push_does_not_pause_previous_state_for_overlay(manager):
    manager.push(_MockState)
    previous = manager.get_current()
    manager.push(_OverlayState)
    assert previous.pause_count == 0


def test_push_on_empty_stack_does_not_raise(manager):
    manager.push(_MockState)
    assert manager.get_current().enter_count == 1


def test_push_stacks_multiple_states(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    manager.push(_MockState)
    assert len(manager.stack) == 3


# ---------------------------------------------------------------------------
# pop
# ---------------------------------------------------------------------------


def test_pop_calls_exit_on_top_state(manager):
    manager.push(_MockState)
    top = manager.get_current()
    manager.pop()
    assert top.exit_count == 1


def test_pop_removes_top_from_stack(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    manager.pop()
    assert len(manager.stack) == 1


def test_pop_calls_resume_on_new_top(manager):
    manager.push(_MockState)
    below = manager.get_current()
    manager.push(_MockState)
    manager.pop()
    assert below.resume_count == 1


def test_pop_empty_stack_does_not_raise(manager):
    manager.pop()


def test_pop_last_state_leaves_empty_stack(manager):
    manager.push(_MockState)
    manager.pop()
    assert manager.stack == []


def test_pop_single_state_does_not_resume_itself(manager):
    manager.push(_MockState)
    top = manager.get_current()
    manager.pop()
    assert top.resume_count == 0


# ---------------------------------------------------------------------------
# replace
# ---------------------------------------------------------------------------


def test_replace_exits_old_top_state(manager):
    manager.push(_MockState)
    old = manager.get_current()
    manager.replace(_MockState)
    assert old.exit_count == 1


def test_replace_enters_new_state(manager):
    manager.push(_MockState)
    manager.replace(_MockState)
    assert manager.get_current().enter_count == 1


def test_replace_keeps_stack_size_the_same(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    size_before = len(manager.stack)
    manager.replace(_MockState)
    assert len(manager.stack) == size_before


def test_replace_new_state_is_not_old_state(manager):
    manager.push(_MockState)
    old = manager.get_current()
    manager.replace(_MockState)
    assert manager.get_current() is not old


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


def test_clear_exits_all_states_below_top(manager):
    manager.push(_MockState)
    bottom = manager.get_current()
    manager.push(_MockState)
    middle = manager.get_current()
    manager.push(_MockState)
    manager.clear()
    assert bottom.exit_count == 1
    assert middle.exit_count == 1


def test_clear_preserves_top_state(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    top = manager.get_current()
    manager.clear()
    assert manager.get_current() is top


def test_clear_leaves_exactly_one_state_in_stack(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    manager.push(_MockState)
    manager.clear()
    assert len(manager.stack) == 1


def test_clear_does_not_call_exit_on_top_state(manager):
    manager.push(_MockState)
    manager.push(_MockState)
    top = manager.get_current()
    manager.clear()
    assert top.exit_count == 0


def test_clear_empty_stack_does_not_raise(manager):
    manager.clear()
    assert manager.stack == []


def test_clear_single_state_stack_leaves_it_intact(manager):
    manager.push(_MockState)
    only = manager.get_current()
    manager.clear()
    assert manager.get_current() is only
    assert only.exit_count == 0
