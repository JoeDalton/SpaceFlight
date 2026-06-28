from unittest.mock import MagicMock

import pytest

from space_flight.game.time_keeping import DelayedMethodManager


class MockGameTime:
    def __init__(self, dt: float = 0.1):
        self._dt = dt

    def get_time_step(self) -> float:
        return self._dt


class MockGame:
    def __init__(self, dt: float = 0.1, is_paused: bool = False):
        self.is_paused = is_paused
        self.game_time = MockGameTime(dt)


@pytest.fixture
def game():
    return MockGame(dt=0.1)


@pytest.fixture
def manager(game):
    return DelayedMethodManager(game)


# ---------------------------
# do_method_later
# ---------------------------


def test_do_method_later_registers_method(manager):
    method = MagicMock()
    manager.do_method_later(1.0, "test", method)
    assert len(manager.methods_to_run_dict) == 1


def test_do_method_later_same_name_twice_creates_two_entries(manager):
    # Same name is allowed because UUID is appended
    method = MagicMock()
    manager.do_method_later(1.0, "foo", method)
    manager.do_method_later(1.0, "foo", method)
    assert len(manager.methods_to_run_dict) == 2


def test_do_method_later_stores_delay(manager):
    method = MagicMock()
    manager.do_method_later(2.5, "my_method", method)
    entry = next(iter(manager.methods_to_run_dict.values()))
    assert entry["delay_s"] == 2.5


def test_do_method_later_default_extra_args(manager):
    method = MagicMock()
    manager.do_method_later(1.0, "no_args", method)
    entry = next(iter(manager.methods_to_run_dict.values()))
    assert entry["extra_args"] == []


def test_do_method_later_with_extra_args(manager):
    method = MagicMock()
    manager.do_method_later(1.0, "with_args", method, extra_args=[1, 2, 3])
    entry = next(iter(manager.methods_to_run_dict.values()))
    assert entry["extra_args"] == [1, 2, 3]


# ---------------------------
# update — paused game
# ---------------------------


def test_update_does_nothing_when_paused(manager):
    manager.game.is_paused = True
    method = MagicMock()
    manager.do_method_later(0.0, "immediate", method)
    manager.update()
    method.assert_not_called()
    assert len(manager.methods_to_run_dict) == 1


# ---------------------------
# update — timer countdown
# ---------------------------


def test_update_decrements_timer(manager):
    manager.game.game_time._dt = 0.05
    method = MagicMock()
    manager.do_method_later(0.2, "delayed", method)
    manager.update()
    entry = next(iter(manager.methods_to_run_dict.values()))
    assert abs(entry["delay_s"] - 0.15) < 1e-9
    method.assert_not_called()


def test_update_fires_method_when_timer_expires(manager):
    manager.game.game_time._dt = 0.1
    method = MagicMock()
    manager.do_method_later(0.1, "fire", method)
    manager.update()
    method.assert_called_once()
    assert len(manager.methods_to_run_dict) == 0


def test_update_fires_method_exactly_at_zero(manager):
    manager.game.game_time._dt = 0.3
    method = MagicMock()
    manager.do_method_later(0.3, "exact", method)
    manager.update()
    method.assert_called_once()


def test_update_fires_method_when_timer_goes_negative(manager):
    manager.game.game_time._dt = 1.0
    method = MagicMock()
    manager.do_method_later(0.1, "overshoot", method)
    manager.update()
    method.assert_called_once()


def test_update_passes_extra_args_to_method(manager):
    manager.game.game_time._dt = 1.0
    method = MagicMock()
    manager.do_method_later(0.0, "args_method", method, extra_args=["a", "b"])
    manager.update()
    method.assert_called_once_with("a", "b")


def test_update_removes_fired_methods(manager):
    manager.game.game_time._dt = 1.0
    method = MagicMock()
    manager.do_method_later(0.0, "to_remove", method)
    manager.update()
    assert len(manager.methods_to_run_dict) == 0


def test_update_only_fires_expired_methods(manager):
    manager.game.game_time._dt = 0.1
    fast = MagicMock()
    slow = MagicMock()
    manager.do_method_later(0.05, "fast", fast)
    manager.do_method_later(1.0, "slow", slow)
    manager.update()
    fast.assert_called_once()
    slow.assert_not_called()
    assert len(manager.methods_to_run_dict) == 1


def test_update_multiple_methods_fire_in_same_frame(manager):
    manager.game.game_time._dt = 1.0
    m1 = MagicMock()
    m2 = MagicMock()
    manager.do_method_later(0.1, "first", m1)
    manager.do_method_later(0.2, "second", m2)
    manager.update()
    m1.assert_called_once()
    m2.assert_called_once()
    assert len(manager.methods_to_run_dict) == 0


# ---------------------------
# clean
# ---------------------------


def test_clean_clears_references(manager):
    manager.do_method_later(1.0, "pending", MagicMock())
    manager.clean()
    assert manager.game is None
    assert manager.methods_to_run_dict is None
