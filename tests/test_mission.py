"""
Tests for the mission scripting framework (:mod:`space_flight.game.scenario`):
Mission (running, sequencing, rules, clock conditions, actions), WaveSpec,
WaveHandle (spawning, state, mutations) and the spatial conditions.
"""

import uuid

import numpy as np
import pytest
from mission_fakes import FakeGame, advance, kill_all, patch_engine

from space_flight.game.scenario import Mission, WaveSpec
from space_flight.game.scenario.conditions import (
    all_of,
    any_of,
    near,
    near_actor,
    not_,
    pawns_of,
    reached_waypoint,
)

WAVE = WaveSpec(
    name="wave", ship_model="tie-bomber", size=3, spawn_point=[100, 200, 300]
)


@pytest.fixture
def game():
    return FakeGame()


@pytest.fixture
def mission(game):
    return Mission(game)


@pytest.fixture
def spawned(monkeypatch):
    return patch_engine(monkeypatch)


def run_jobs(mission, n=1000):
    """Step the mission until no job is left."""
    for _ in range(n):
        if not mission.jobs:
            return
        mission.update()


def run_body(mission, body):
    """Run a mission body to completion and return what it returned."""
    result = {}

    def wrapper(m):
        result["value"] = yield from body(m)

    mission.run(wrapper)
    return result


# ---------------------------------------------------------------------------
# Running and sequencing
# ---------------------------------------------------------------------------


def test_run_steps_the_body_once_per_frame(mission):
    steps = []

    def body(m):
        steps.append(1)
        yield
        steps.append(2)

    mission.run(body)
    mission.update()
    assert steps == [1]
    mission.update()
    assert steps == [1, 2]
    assert mission.jobs == []


def test_wait_pauses_for_game_time(game, mission):
    done = []

    def body(m):
        yield from m.wait(10)
        done.append(True)

    mission.run(body)
    advance(game, mission, 9)
    assert not done
    advance(game, mission, 2)
    assert done


def test_wait_until_returns_true_when_the_condition_holds(game, mission):
    flag = {"v": False}
    result = run_body(mission, lambda m: m.wait_until(lambda: flag["v"], timeout=5))
    advance(game, mission, 1)
    assert "value" not in result
    flag["v"] = True
    mission.update()
    assert result["value"] is True


def test_wait_until_returns_false_on_timeout(game, mission):
    result = run_body(mission, lambda m: m.wait_until(lambda: False, timeout=5))
    advance(game, mission, 4)
    assert "value" not in result
    advance(game, mission, 2)
    assert result["value"] is False


# ---------------------------------------------------------------------------
# Reactive rules
# ---------------------------------------------------------------------------


def test_on_fires_once_by_default(mission):
    calls = []
    trigger = mission.on(lambda: True, lambda: calls.append(1))
    for _ in range(3):
        mission.update()
    assert calls == [1]
    assert trigger.fired is True


def test_on_repeats_every_frame_when_not_once(mission):
    calls = []
    mission.on(lambda: True, lambda: calls.append(1), once=False)
    for _ in range(3):
        mission.update()
    assert calls == [1, 1, 1]


def test_cancel_stops_a_rule(mission):
    flag = {"v": False}
    calls = []
    trigger = mission.on(lambda: flag["v"], lambda: calls.append(1))
    mission.update()
    trigger.cancel()
    flag["v"] = True
    mission.update()
    assert calls == []
    assert mission.triggers == []


# ---------------------------------------------------------------------------
# Clock conditions
# ---------------------------------------------------------------------------


def test_after_is_relative_to_its_creation(game, mission):
    game.game_time.t = 100
    cond = mission.after(10)
    game.game_time.t = 109
    assert cond() is False
    game.game_time.t = 110
    assert cond() is True


def test_delay_latches_once_armed(game, mission):
    inner = {"v": False}
    cond = mission.delay(lambda: inner["v"], 3)
    assert cond() is False  # not armed
    inner["v"] = True
    game.game_time.t = 10
    assert cond() is False  # armed at t=10
    inner["v"] = False  # a flicker must not disarm
    game.game_time.t = 13
    assert cond() is True


def test_sustained_needs_an_unbroken_run(game, mission):
    inner = {"v": True}
    cond = mission.sustained(lambda: inner["v"], 10)
    assert cond() is False  # armed at t=0
    game.game_time.t = 5
    inner["v"] = False  # breaks the run: resets, unlike delay
    assert cond() is False
    inner["v"] = True
    game.game_time.t = 10
    assert cond() is False  # re-armed at t=10
    game.game_time.t = 16
    assert cond() is False
    game.game_time.t = 20
    assert cond() is True


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_hud_and_speech(game, mission):
    mission.hud("First wave")
    mission.speech("Standing by.", speaker="Red Leader")
    mission.speech("Narration.")
    assert game.hud.messages == [("First wave", 5.0)]
    assert game.hud.chatter == [
        ("Red Leader: Standing by.", 6.0),
        ("Narration.", 6.0),
    ]


def test_hud_and_speech_are_skipped_headless(game, mission):
    game.headless = True
    mission.hud("x")
    mission.speech("y")
    assert game.hud.messages == [] and game.hud.chatter == []


def test_end_level_victory_defeat(game, mission):
    mission.victory("won")
    mission.defeat("lost")
    mission.end_level("death", "dead")
    assert game.end_level_calls == [
        ("victory", "won"),
        ("defeat", "lost"),
        ("death", "dead"),
    ]


def test_player_waypoints_replaces_the_previous_route(game, mission, spawned):
    mission.player_waypoints([[0, 0, 0]], arrival_radius_m=200)
    first = game.player_waypoints
    assert first.kwargs == {"arrival_radius_m": 200}

    mission.player_waypoints([[1, 1, 1]])
    assert first.cleaned is True
    assert game.player_waypoints.waypoints == [[1, 1, 1]]

    second = game.player_waypoints
    mission.clear_player_waypoints()
    assert second.cleaned is True
    assert game.player_waypoints is None


# ---------------------------------------------------------------------------
# WaveSpec
# ---------------------------------------------------------------------------


def test_wave_spec_requires_size_for_a_single_model():
    with pytest.raises(ValueError, match="size"):
        WaveSpec(name="w", ship_model="x-wing")


def test_wave_spec_infers_size_for_a_mixed_wave():
    spec = WaveSpec(name="w", ship_model=[("tie-bomber", 2), ("tie-interceptor", 1)])
    assert spec.ship_models() == ["tie-bomber", "tie-bomber", "tie-interceptor"]
    with pytest.raises(ValueError, match="inferred"):
        WaveSpec(name="w", ship_model=[("x-wing", 1)], size=3)


def test_wave_spec_rejects_unknown_fields():
    with pytest.raises(TypeError):
        WaveSpec(name="w", ship_model="x-wing", size=1, not_a_field=1)


# ---------------------------------------------------------------------------
# WaveHandle: spawning
# ---------------------------------------------------------------------------


def test_spawn_creates_one_ship_per_frame(mission, spawned):
    mission.spawn(WAVE)
    assert spawned == []  # deferred to the next update
    mission.update()
    assert [b.name for b in spawned] == ["wave_0"]
    run_jobs(mission)
    assert [b.name for b in spawned] == ["wave_0", "wave_1", "wave_2"]


def test_spawn_point_can_be_given_at_spawn_time(mission, spawned):
    spec = WaveSpec(name="w", ship_model="x-wing", size=1)
    with pytest.raises(ValueError, match="spawn point"):
        mission.spawn(spec)
    mission.spawn(spec, spawn_point=[1, 2, 3])
    run_jobs(mission)
    assert np.allclose(spawned[0].pawn.position, [1, 2, 3])


def test_spawn_uses_formation_slots(mission, spawned):
    spec = WaveSpec(
        name="w",
        ship_model="x-wing",
        size=3,
        spawn_point=[100, 200, 300],
        formation="arrowhead",
    )
    wave = mission.spawn(spec)
    run_jobs(mission)
    # The leader spawns exactly on the spawn point; wingmen at their slots.
    assert np.allclose(spawned[0].pawn.position, [100, 200, 300])
    expected = np.array([100, 200, 300]) + wave.formation.relative_positions[1]
    assert np.allclose(spawned[1].pawn.position, expected)
    assert wave.formation.ship_ids == [b.pawn.id for b in spawned]


def test_spawn_without_formation_uses_a_centred_line(mission, spawned):
    mission.spawn(WAVE)
    run_jobs(mission)
    xs = [b.pawn.position[0] for b in spawned]
    assert xs == [50.0, 100.0, 150.0]


def test_join_continues_the_formation_slots(mission, spawned):
    escort = mission.spawn(
        WaveSpec(
            name="escort",
            ship_model="x-wing",
            size=2,
            spawn_point=[0, 0, 0],
            formation="arrowhead",
        )
    )
    run_jobs(mission)
    reinforcements = mission.spawn(
        WaveSpec(name="reinf", ship_model="x-wing", size=2, spawn_point=[0, 0, 0]),
        join=escort.formation,
    )
    run_jobs(mission)
    assert reinforcements.formation is escort.formation
    assert len(escort.formation.ship_ids) == 4
    # Reinforcements take slots 2 and 3, not the leader's slot 0.
    assert np.allclose(spawned[2].pawn.position, escort.formation.relative_positions[2])


def test_join_while_the_host_is_still_spawning_never_shares_a_slot(mission, spawned):
    host = mission.spawn(
        WaveSpec(
            name="host",
            ship_model="x-wing",
            size=3,
            spawn_point=[0, 0, 0],
            formation="arrowhead",
        )
    )
    mission.update()  # only the host's leader exists so far
    mission.spawn(
        WaveSpec(name="joiner", ship_model="x-wing", size=2, spawn_point=[0, 0, 0]),
        join=host.formation,
    )
    run_jobs(mission)
    positions = {tuple(b.pawn.position) for b in spawned}
    assert len(positions) == 5
    assert len(host.formation.ship_ids) == 5


def test_mixed_wave_spawns_each_model(mission, spawned):
    spec = WaveSpec(
        name="mixed",
        ship_model=[("tie-bomber", 2), ("tie-interceptor", 1)],
        spawn_point=[0, 0, 0],
    )
    mission.spawn(spec)
    run_jobs(mission)
    assert [b.pawn_model for b in spawned] == [
        "tie-bomber",
        "tie-bomber",
        "tie-interceptor",
    ]


def test_spawn_target_accepts_a_wave_or_a_ship(game, mission, spawned):
    transports = mission.spawn(WAVE)
    run_jobs(mission)
    attackers = mission.spawn(
        WaveSpec(name="att", ship_model="x", size=1, spawn_point=[0, 0, 0]),
        target=transports,
    )
    hunters = mission.spawn(
        WaveSpec(name="hunt", ship_model="x", size=1, spawn_point=[0, 0, 0]),
        target=game.player,
    )
    run_jobs(mission)
    transport_ids = [p.id for p in transports.pawns()]
    assert attackers.pawns()[0].parent.tactician.primary_target_ids == transport_ids
    assert hunters.pawns()[0].parent.tactician.primary_target_ids == [
        game.player.pawn.id
    ]


# ---------------------------------------------------------------------------
# WaveHandle: state
# ---------------------------------------------------------------------------


def test_wave_state_before_during_and_after(game, mission, spawned):
    wave = mission.wave(WAVE)
    assert not wave.alive() and not wave.all_destroyed() and not wave.any_destroyed()

    wave.spawn()
    mission.update()  # one of three ships spawned
    assert wave.alive() and not wave.all_destroyed() and not wave.any_destroyed()
    run_jobs(mission)

    game.interactions.kill(wave.pawns()[0])
    assert wave.alive() and wave.any_destroyed() and not wave.all_destroyed()

    kill_all(game, wave.pawns())
    assert not wave.alive() and wave.any_destroyed() and wave.all_destroyed()


def test_wave_state_methods_are_conditions(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    calls = []
    mission.on(wave.all_destroyed, lambda: calls.append(1))
    mission.update()
    assert calls == []
    kill_all(game, wave.pawns())
    mission.update()
    assert calls == [1]


# ---------------------------------------------------------------------------
# WaveHandle: mutations
# ---------------------------------------------------------------------------


def test_set_targets(mission, spawned):
    attackers = mission.spawn(WAVE)
    defenders = mission.spawn(
        WaveSpec(name="def", ship_model="x", size=2, spawn_point=[0, 0, 0])
    )
    run_jobs(mission)
    attackers.set_targets(defenders)
    defender_ids = [p.id for p in defenders.pawns()]
    for pawn in attackers.pawns():
        assert pawn.parent.tactician.primary_target_ids == defender_ids


def test_set_waypoints(mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    wave.set_waypoints([[0, 0, 0], [0, 100, 0]], loop=False)
    for bot in spawned:
        assert len(bot.navigator.waypoints) == 2
        assert bot.navigator.is_loop is False


def test_set_team(mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    wave.set_team(9)
    assert all(b.team == 9 and b.pawn.team == 9 for b in spawned)


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


def test_pawns_of(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    assert pawns_of(wave) == wave.pawns()
    assert pawns_of(game.player) == [game.player.pawn]
    assert pawns_of(game.player.pawn) == [game.player.pawn]
    game.player.pawn.is_dead = True
    assert pawns_of(game.player) == []
    game.player.pawn = None  # a cleaned-up bot
    assert pawns_of(game.player) == []


def test_near(game):
    cond = near(game.player, [0, 0, 0], 100)
    assert cond() is True
    game.player.pawn.position = np.array([200.0, 0, 0])
    assert cond() is False


def test_near_actor_tracks_both_sides_live(game, mission, spawned):
    wave = mission.spawn(
        WaveSpec(name="w", ship_model="x", size=2, spawn_point=[1000, 0, 0])
    )
    run_jobs(mission)
    cond = near_actor(game.player, wave, 100)
    assert cond() is False
    wave.pawns()[1].position = np.array([50.0, 0, 0])  # any member will do
    assert cond() is True
    game.player.pawn.position = np.array([500.0, 0, 0])
    assert cond() is False


def test_reached_waypoint(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    cond = reached_waypoint(wave, 0)
    assert cond() is False  # next_waypoint_idx starts at 0: not reached yet
    wave.pawns()[2].parent.navigator.next_waypoint_idx = 1
    assert cond() is True
    assert reached_waypoint(wave.pawns()[0], 0)() is False  # per-ship check


def test_combinators():
    def yes():
        return True

    def no():
        return False

    assert all_of(yes, yes)() and not all_of(yes, no)()
    assert any_of(no, yes)() and not any_of(no, no)()
    assert not_(no)() and not not_(yes)()


def test_ids_are_unique_per_spawn(mission, spawned):
    wave = mission.spawn(WAVE)
    wave.spawn()  # spawning again adds the same composition to the wave
    run_jobs(mission)
    assert len(wave.ids) == 6 and len(set(wave.ids)) == 6
    assert all(isinstance(i, uuid.UUID) for i in wave.ids)
