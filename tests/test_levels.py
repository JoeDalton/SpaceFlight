"""
Tests for the shipped levels' mission bodies, run end-to-end against the
fakes in mission_fakes.py. "Combat" (ships dying, a convoy or leader reaching
a waypoint, the player flying somewhere) is simulated by the test reaching
into the fake world directly.
"""

import numpy as np
import pytest
from mission_fakes import FakeGame, advance, kill_all, live, patch_engine

from space_flight.game.levels import LEVELS
from space_flight.game.levels import mission1_level as mission1
from space_flight.game.levels.dev_level import dev_mission
from space_flight.game.levels.intro_level import intro_mission
from space_flight.game.scenario import Mission


@pytest.fixture
def game():
    return FakeGame()


@pytest.fixture
def spawned(monkeypatch):
    return patch_engine(monkeypatch)


def start(game, body):
    mission = Mission(game)
    mission.run(body)
    return mission


def test_every_level_has_an_upfront_and_a_mission():
    for name, entry in LEVELS.items():
        assert callable(entry.upfront), name
        assert callable(entry.mission), name
        assert entry.description, name


# ---------------------------------------------------------------------------
# Dev
# ---------------------------------------------------------------------------


def test_dev_mission_spawns_the_frigate(game, spawned):
    m = start(game, dev_mission)
    advance(game, m, 3)
    assert len(live(game, spawned, "enemy_frigate")) == 1


# ---------------------------------------------------------------------------
# Intro
# ---------------------------------------------------------------------------


def test_intro_victory(game, spawned):
    m = start(game, intro_mission)

    # Transports at 0.1s, escort at 1s, first wave at 10s.
    advance(game, m, 12)
    assert len(live(game, spawned, "transports")) == 3
    assert len(live(game, spawned, "escort")) == 6
    first_wave = live(game, spawned, "first_wave")
    assert len(first_wave) == 5
    transport_ids = {p.id for p in live(game, spawned, "transports")}
    assert set(first_wave[0].parent.tactician.primary_target_ids) == transport_ids

    # Wiping the first wave brings the third wave ~3s later (well before the
    # 200s fallback); the second wave arrives on its own at 30s.
    kill_all(game, first_wave)
    advance(game, m, 20)  # t ~= 32s
    assert len(live(game, spawned, "third_wave")) == 8
    assert len(live(game, spawned, "second_wave")) == 5

    # Second wave gone + convoy past its last waypoint -> victory 3s later.
    kill_all(game, live(game, spawned, "second_wave"))
    for pawn in live(game, spawned, "transports"):
        pawn.parent.navigator.next_waypoint_idx = 9
    advance(game, m, 1)
    assert ("Convoy past the blockade — well done.", 5.0) in game.hud.messages
    assert game.end_level_calls == []
    advance(game, m, 3)
    assert game.end_level_calls[-1][0] == "victory"


def test_intro_defeat(game, spawned):
    m = start(game, intro_mission)
    advance(game, m, 2)  # transports and escort spawned
    kill_all(game, live(game, spawned, "transports"))
    advance(game, m, 1)
    assert any("All transports" in text for text, _ in game.hud.chatter)
    advance(game, m, 3)
    assert game.end_level_calls[-1] == ("defeat", "The convoy has been destroyed.")


# ---------------------------------------------------------------------------
# Mission 1: Rookies
# ---------------------------------------------------------------------------


def reach_formation(game, m, spawned):
    """Play up to the formation spawning; return its live pawns."""
    advance(game, m, 1)
    game.player.pawn.position = np.array(mission1.WAYPOINT_1, dtype=float)
    advance(game, m, 5)  # the 3s intro wait, then 4 ships, one per frame
    return live(game, spawned, "blue")


def finish_circuit(game, m, spawned):
    """Catch up with the formation and fast-forward its circuit."""
    blue = reach_formation(game, m, spawned)
    game.player.pawn.position = blue[0].position.copy()
    advance(game, m, 1)
    blue[0].parent.navigator.next_waypoint_idx = len(mission1.CIRCUIT_WAYPOINTS)
    advance(game, m, 1)
    return blue


def test_mission1_waypoint_to_formation_handoff(game, spawned):
    m = start(game, mission1.mission1_mission)
    advance(game, m, 1)
    intro_route = game.player_waypoints
    assert intro_route.waypoints == [mission1.WAYPOINT_1]
    assert live(game, spawned, "blue") == []

    game.player.pawn.position = np.array(mission1.WAYPOINT_1, dtype=float)
    advance(game, m, 5)

    blue = live(game, spawned, "blue")
    assert len(blue) == 4
    # The leader spawns 1km ahead (+forward) and to the left (-right).
    expected = (
        np.array(mission1.WAYPOINT_1, dtype=float)
        + np.array([0.0, 1.0, 0.0]) * mission1.FORMATION_AHEAD_M
        - np.array([1.0, 0.0, 0.0]) * mission1.FORMATION_LEFT_M
    )
    assert np.allclose(blue[0].position, expected)
    assert intro_route.cleaned is True
    assert any("[R]" in text and "[,]" in text for text, _ in game.hud.messages)


def test_mission1_catch_up_deadline_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    reach_formation(game, m, spawned)
    advance(game, m, mission1.CATCH_UP_DEADLINE_S + 2)
    assert game.end_level_calls[-1][0] == "defeat"
    assert "catch up" in game.end_level_calls[-1][1]


def test_mission1_sustained_separation_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = reach_formation(game, m, spawned)
    game.player.pawn.position = blue[0].position.copy()
    advance(game, m, 1)
    assert game.end_level_calls == []

    game.player.pawn.position = blue[0].position + np.array(
        [mission1.FOLLOW_RADIUS_M * 5, 0.0, 0.0]
    )
    advance(game, m, mission1.SUSTAINED_SEPARATION_S + 1)
    assert game.end_level_calls[-1][0] == "defeat"
    assert "fell too far behind" in game.end_level_calls[-1][1]


def test_mission1_any_formation_member_counts(game, spawned):
    """Staying close to a wingman that drifted away from the leader is enough."""
    m = start(game, mission1.mission1_mission)
    blue = reach_formation(game, m, spawned)
    leader, wingman = blue[0], blue[1]
    wingman.position = leader.position + np.array(
        [0.0, mission1.FOLLOW_RADIUS_M * 5, 0.0]
    )
    game.player.pawn.position = wingman.position.copy()
    advance(game, m, mission1.CATCH_UP_DEADLINE_S + mission1.SUSTAINED_SEPARATION_S)
    assert game.end_level_calls == []


def test_mission1_separation_rule_stops_once_the_race_starts(game, spawned):
    m = start(game, mission1.mission1_mission)
    finish_circuit(game, m, spawned)
    game.player.pawn.position = np.array([1e5, 0.0, 0.0])  # far from everyone
    advance(game, m, mission1.SUSTAINED_SEPARATION_S + 1)
    assert game.end_level_calls == []
    assert game.player_waypoints.waypoints == mission1.RACE_WAYPOINTS


def test_mission1_first_place_is_special(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1)
    for pawn in blue:
        pawn.position = finish.copy()
    advance(game, m, 1)
    assert game.end_level_calls[-1] == (
        "victory",
        "First across the line! Outstanding flying, rookie!",
    )


def test_mission1_middle_place_is_a_plain_victory(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    blue[0].position = finish.copy()
    advance(game, m, 1)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1)
    for pawn in blue[1:]:
        pawn.position = finish.copy()
    advance(game, m, 1)
    assert game.end_level_calls[-1][0] == "victory"
    assert "First" not in game.end_level_calls[-1][1]


def test_mission1_last_place_is_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    for pawn in blue:
        pawn.position = finish.copy()
    advance(game, m, 1)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1)
    assert game.end_level_calls[-1] == (
        "defeat",
        "You crossed the line last. Mission failed.",
    )
