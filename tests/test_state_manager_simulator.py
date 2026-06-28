from unittest.mock import MagicMock

import pytest

from space_flight.global_architecture.simulator import StateManager


class MockState:
    """Concrete BaseState stub that records lifecycle calls."""

    PAUSES_BELOW = True

    def __init__(self, app, **kwargs):
        self.app = app
        self.kwargs = kwargs
        self.entered = False
        self.exited = False
        self.paused = False
        self.resumed = False

    def enter(self):
        self.entered = True

    def exit(self):
        self.exited = True

    def pause(self):
        self.paused = True

    def resume(self):
        self.resumed = True


class NonPausingState(MockState):
    PAUSES_BELOW = False


@pytest.fixture
def manager():
    app = MagicMock()
    return StateManager(app=app)


# ---------------------------
# get_current
# ---------------------------


def test_get_current_empty_stack_returns_none(manager):
    assert manager.get_current() is None


def test_get_current_returns_top_state(manager):
    manager.stack.append(MockState(manager.app))
    state = MockState(manager.app)
    manager.stack.append(state)
    assert manager.get_current() is state


# ---------------------------
# push
# ---------------------------


def test_push_enters_new_state(manager):
    manager.push(MockState)
    assert manager.stack[0].entered is True


def test_push_appends_to_stack(manager):
    manager.push(MockState)
    manager.push(MockState)
    assert len(manager.stack) == 2


def test_push_pauses_previous_state_when_pauses_below_true(manager):
    manager.push(MockState)
    previous = manager.stack[0]
    manager.push(MockState)
    assert previous.paused is True


def test_push_does_not_pause_previous_when_pauses_below_false(manager):
    manager.push(MockState)
    previous = manager.stack[0]
    manager.push(NonPausingState)
    assert previous.paused is False


def test_push_passes_kwargs_to_state(manager):
    manager.push(MockState, foo="bar", baz=42)
    assert manager.stack[0].kwargs == {"foo": "bar", "baz": 42}


def test_push_on_empty_stack_does_not_pause(manager):
    # No exception, no prior state to pause
    manager.push(MockState)
    assert len(manager.stack) == 1


# ---------------------------
# pop
# ---------------------------


def test_pop_empty_stack_does_not_raise(manager):
    manager.pop()  # should log a warning and return


def test_pop_exits_top_state(manager):
    manager.push(MockState)
    state = manager.stack[0]
    manager.pop()
    assert state.exited is True


def test_pop_removes_top_state(manager):
    manager.push(MockState)
    manager.pop()
    assert len(manager.stack) == 0


def test_pop_resumes_state_below(manager):
    manager.push(MockState)
    below = manager.stack[0]
    manager.push(MockState)
    manager.pop()
    assert below.resumed is True


def test_pop_does_not_resume_when_stack_becomes_empty(manager):
    manager.push(MockState)
    state = manager.stack[0]
    manager.pop()
    # No exception; resumed is still False because there was nothing below
    assert state.resumed is False


def test_pop_sequence_restores_correct_state(manager):
    manager.push(MockState)
    state_a = manager.stack[0]
    manager.push(MockState)
    manager.push(MockState)
    manager.pop()
    assert manager.get_current() is not state_a
    manager.pop()
    assert manager.get_current() is state_a


# ---------------------------
# replace
# ---------------------------


def test_replace_exits_old_state(manager):
    manager.push(MockState)
    old = manager.stack[0]
    manager.replace(MockState)
    assert old.exited is True


def test_replace_pushes_new_state(manager):
    manager.push(MockState)
    manager.replace(MockState)
    assert len(manager.stack) == 1
    assert manager.stack[0].entered is True


def test_replace_new_state_is_different_instance(manager):
    manager.push(MockState)
    old = manager.stack[0]
    manager.replace(MockState)
    assert manager.stack[0] is not old


# ---------------------------
# clear
# ---------------------------


def test_clear_empty_stack_does_nothing(manager):
    manager.clear()
    assert len(manager.stack) == 0


def test_clear_single_state_keeps_it(manager):
    manager.push(MockState)
    top = manager.stack[0]
    manager.clear()
    assert len(manager.stack) == 1
    assert manager.stack[0] is top


def test_clear_exits_all_but_top(manager):
    manager.push(MockState)
    bottom = manager.stack[0]
    manager.push(MockState)
    middle = manager.stack[1]
    manager.push(MockState)
    top = manager.stack[2]
    manager.clear()
    assert bottom.exited is True
    assert middle.exited is True
    assert top.exited is False


def test_clear_keeps_top_state(manager):
    manager.push(MockState)
    manager.push(MockState)
    manager.push(MockState)
    top = manager.stack[-1]
    manager.clear()
    assert manager.stack[0] is top
    assert len(manager.stack) == 1
