from unittest.mock import MagicMock

import pytest

from space_flight.actors.destructibles import Destructible, Destructibles


# Minimal subclass to implement abstract methods
class DummyDestructible(Destructible):
    def clean(self):
        self.cleaned = True

    def get_health(self):
        return self.health

    def play_death(self):
        self.played_death = True


@pytest.fixture
def mock_game():
    game = MagicMock()
    game.destructibles.alive_objects = []
    game.method_lists = {}
    return game


def test_destructible_init_adds_to_game(mock_game):
    d = Destructible(mock_game)
    assert d in mock_game.destructibles.alive_objects
    assert d.id in mock_game.method_lists
    assert mock_game.method_lists[d.id] == []


def test_add_task_appends_to_actor_methods(mock_game):
    d = Destructible(mock_game)

    def task():
        return 42

    d.add_task(task)
    assert task in mock_game.method_lists[d.id]


def test_clear_tasks_removes_actor_methods(mock_game):
    d = Destructible(mock_game)
    d.add_task(lambda: None)
    d.clear_tasks()
    assert d.id not in mock_game.method_lists


# ---------------------------
# Destructibles
# ---------------------------


def test_handle_deaths_calls_play_death_and_clean(mock_game):
    destructibles = Destructibles()
    d1 = DummyDestructible(mock_game)
    d2 = DummyDestructible(mock_game)

    # Assign health
    d1.health = 10.0
    d2.health = 0.0  # should die

    destructibles.alive_objects = [d1, d2]

    # Patch methods to track calls
    d2.played_death = False
    d2.cleaned = False
    d2.clear_tasks = MagicMock()

    destructibles.handle_deaths()

    # d1 should still be alive
    assert destructibles.alive_objects == [d1]

    # d2 should be processed as dead
    assert d2.played_death is True
    d2.clear_tasks.assert_called_once()
    assert d2.cleaned is True


def test_clean_removes_all_destructibles(mock_game):
    destructibles = Destructibles()
    d1 = DummyDestructible(mock_game)
    d2 = DummyDestructible(mock_game)
    destructibles.alive_objects = [d1, d2]

    destructibles.clean()

    assert destructibles.alive_objects is None
    assert d1.cleaned is True
    assert d2.cleaned is True


# ---------------------------
# __del__ logging
# ---------------------------


def test_del_logs_destruction(caplog, mock_game, monkeypatch):
    monkeypatch.setattr("space_flight.actors.destructibles.DEBUG_DELETION", True)

    d = DummyDestructible(mock_game)
    d.name = "TestObject"

    with caplog.at_level("INFO"):
        # Force __del__ call
        d.__del__()

    assert "Destroyed destructible object: TestObject" in caplog.text


# ---------------------------
# Parametrized handle_deaths tests
# ---------------------------


@pytest.mark.parametrize(
    "health_values, expected_alive_count, expected_dead_indices",
    [
        ([10.0, 20.0], 2, []),  # all alive
        ([0.0, -5.0], 0, [0, 1]),  # all dead
        ([10.0, 0.0], 1, [1]),  # mixed
        ([0.0, 10.0, 0.0], 1, [0, 2]),  # multiple dead interleaved
        ([5.0], 1, []),  # single alive
        ([0.0], 0, [0]),  # single dead
    ],
)
def test_handle_deaths_parametrized(
    mock_game, health_values, expected_alive_count, expected_dead_indices
):
    destructibles = Destructibles()
    objects = []

    # Create destructibles with given health
    for h in health_values:
        d = DummyDestructible(mock_game)
        d.health = h
        d.played_death = False
        d.cleaned = False
        d.clear_tasks = MagicMock()
        objects.append(d)

    destructibles.alive_objects = objects

    destructibles.handle_deaths()

    # Count of alive objects
    assert len(destructibles.alive_objects) == expected_alive_count

    # Verify dead objects were processed
    for idx in expected_dead_indices:
        dead_obj = objects[idx]
        assert dead_obj.played_death is True
        dead_obj.clear_tasks.assert_called_once()
        assert dead_obj.cleaned is True

    # Verify alive objects were untouched
    for idx, obj in enumerate(objects):
        if idx not in expected_dead_indices:
            assert obj.played_death is False
            assert obj.cleaned is False
            obj.clear_tasks.assert_not_called()
