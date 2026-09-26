"""
Runs the all-features reference example
(docs/source/examples/all_features_example.py) end-to-end against the fakes
in mission_fakes.py, to prove it actually works, not just that it imports.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from mission_fakes import FakeGame, advance, kill_all, live, patch_engine

from space_flight.game.scenario import Mission

EXAMPLE = Path(__file__).parent.parent / "docs/source/examples/all_features_example.py"


def load_example():
    """Import the example by path (docs/ is not a package)."""
    spec = importlib.util.spec_from_file_location("all_features_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def game():
    return FakeGame()


@pytest.fixture
def spawned(monkeypatch):
    return patch_engine(monkeypatch)


@pytest.fixture
def mission(game):
    mission = Mission(game)
    mission.run(load_example().all_features_mission)
    return mission


def play_to_the_shadowing_phase(game, mission, spawned):
    """Advance until every wave has spawned and the patrol reached waypoint 0."""
    advance(game, mission, 3)
    live(game, spawned, "patrol")[0].parent.navigator.next_waypoint_idx = 1
    advance(game, mission, 1)


def test_happy_path(game, mission, spawned):
    play_to_the_shadowing_phase(game, mission, spawned)
    boarding = live(game, spawned, "boarding")
    game.player.pawn.position = boarding[0].position.copy()
    advance(game, mission, 1)

    assert game.end_level_calls == [
        ("victory", "Mission complete: every feature exercised.")
    ]

    homeguard_id = live(game, spawned, "homeguard")[0].id
    strike = live(game, spawned, "strike")
    assert len(strike) == 4
    assert all(p.parent.tactician.primary_target_ids == [homeguard_id] for p in strike)

    # join=: both reinforcement spawns took the strike formation's free slots.
    reinforcements = live(game, spawned, "reinforcements")
    assert len(reinforcements) == 4
    # The reinforcements join while the strike wave is still spawning; every
    # ship must still get its own slot.
    formation = strike[0].formation
    assert all(p.formation is formation for p in strike + reinforcements)
    assert set(formation.ship_ids) == {p.id for p in strike + reinforcements}
    positions = {tuple(p.position) for p in strike + reinforcements}
    assert len(positions) == 8

    # Mixed composition.
    assert [p.parent.pawn_model for p in boarding] == [
        "tie-bomber",
        "tie-bomber",
        "tie-interceptor",
    ]

    # Live mutations on the patrol, targeted at the player on spawn.
    patrol = live(game, spawned, "patrol")[0].parent
    assert patrol.pawn.team == 2
    assert patrol.tactician.primary_target_ids == [game.player.pawn.id] + [
        p.id for p in boarding
    ]
    assert [tuple(w) for w in patrol.navigator.waypoints] == [
        (500, -1000, 500),
        (500, -2000, 500),
    ]

    # Repeating rule seen, cancelled rule never seen, route cleared.
    assert ("Engagement in progress.", 1) in game.hud.messages
    assert not any(text == "Too late." for text, _ in game.hud.messages)
    assert game.player_waypoints is None


def test_timeout_ending(game, mission, spawned):
    play_to_the_shadowing_phase(game, mission, spawned)
    advance(game, mission, 9)  # never gets close to the boarding party
    assert game.end_level_calls == [("defeat", "The boarding party got away.")]


def test_homeguard_wiped_defeat(game, mission, spawned):
    advance(game, mission, 1)
    kill_all(game, live(game, spawned, "homeguard"))
    advance(game, mission, 1)
    assert ("Ops: We're taking losses!", 6.0) in game.hud.chatter
    assert game.end_level_calls == []
    advance(game, mission, 3)
    assert game.end_level_calls[0] == ("defeat", "The home guard was destroyed.")


def test_proximity_warning_repeats(game, mission, spawned):
    advance(game, mission, 1)
    game.player.pawn.position = np.array([0.0, -1000.0, 200.0])
    before = len(game.hud.messages)
    mission.update()
    mission.update()
    warnings = [t for t, _ in game.hud.messages[before:] if t.startswith("Danger")]
    assert len(warnings) == 2
