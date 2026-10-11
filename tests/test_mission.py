"""
Tests for the mission scripting framework (:mod:`space_flight.game.scenario`):
Mission (running, sequencing, rules, clock conditions, actions), WaveSpec,
WaveHandle (spawning, launching from a hangar, state, mutations), the
conditions and scanning.
"""

import uuid

import numpy as np
import pytest
from mission_fakes import (
    FakeGame,
    FakeHangar,
    MockBot,
    advance,
    kill_all,
    patch_engine,
)

from space_flight.ai.formation import Formation
from space_flight.game.kills import DamageSource
from space_flight.game.scenario import Mission, WaveSpec
from space_flight.game.scenario.conditions import (
    all_of,
    any_of,
    being_hit,
    damaged,
    ids_of,
    near,
    near_actor,
    not_,
    pawns_of,
    reached_waypoint,
)
from space_flight.game.scenario.mission import LEVEL_END_DELAY_S
from space_flight.ui.hud import CHATTER_DISPLAY_S, EVENT_DISPLAY_S, HINT_DISPLAY_S

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


def test_hud_hint_and_speech(game, mission):
    mission.hud("First wave")
    mission.hint("Press [1].")
    mission.speech("Standing by.", speaker="Red Leader")
    mission.speech("Narration.")
    assert game.hud.messages == [("First wave", EVENT_DISPLAY_S)]
    assert game.hud.hints == [("Press [1].", HINT_DISPLAY_S)]
    assert game.hud.chatter == [
        ("Red Leader: Standing by.", CHATTER_DISPLAY_S),
        ("Narration.", CHATTER_DISPLAY_S),
    ]


def test_hud_and_speech_are_skipped_headless(game, mission):
    game.headless = True
    mission.hud("x")
    mission.hint("z")
    mission.speech("y")
    assert game.hud.messages == [] and game.hud.chatter == []
    assert game.hud.hints == []


@pytest.mark.parametrize(
    "end, outcome",
    [
        (lambda m: m.victory("why"), "victory"),
        (lambda m: m.defeat("why"), "defeat"),
        (lambda m: m.end_level("death", "why"), "death"),
    ],
)
def test_the_level_ends_after_a_delay(game, mission, end, outcome):
    end(mission)
    advance(game, mission, LEVEL_END_DELAY_S - 0.1)
    assert game.end_level_calls == []

    advance(game, mission, 0.2)
    assert game.end_level_calls == [(outcome, "why")]


def test_only_the_first_ending_counts(game, mission):
    mission.victory("won")
    mission.defeat("lost")
    advance(game, mission, LEVEL_END_DELAY_S + 1)

    assert mission.ending == "victory"
    assert game.end_level_calls == [("victory", "won")]


def test_objectives_are_frozen_once_the_level_ends(game, mission):
    lost = []
    objective = mission.objective("Keep them alive", failed=lambda: bool(lost))
    mission.victory("won")

    lost.append(True)
    advance(game, mission, LEVEL_END_DELAY_S + 1)

    assert objective.active()


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


def test_wave_destroyed_count(game, mission, spawned):
    wave = mission.spawn(WAVE)
    assert wave.destroyed_count() == 0
    run_jobs(mission)

    kill_all(game, wave.pawns()[:2])

    assert wave.destroyed_count() == 2


def test_being_hit_is_true_on_the_frames_integrity_drops(game):
    pawn = game.player.pawn
    pawn.shield_level = 50.0
    hit = being_hit(game.player)
    assert not hit()  # takes the readings

    pawn.shield_level = 40.0
    assert hit()
    assert not hit()  # nothing new

    # A regenerating shield never hides the next hit
    pawn.shield_level = 60.0
    assert not hit()
    pawn.health -= 1.0
    assert hit()


def test_being_hit_by_the_player_reads_the_last_hitter(game):
    pawn = game.player.pawn
    target = MockBot("tie", [0, 0, 0], team=2).pawn
    game.interactions.add(target)
    hit = being_hit(target, by_player=True)
    hit()

    target.last_hit_by = DamageSource.of(MockBot("x", [0, 0, 0], team=2).pawn, game)
    target.health -= 1.0
    assert not hit()

    target.last_hit_by = DamageSource.of(pawn, game)
    target.health -= 1.0
    assert hit()


# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------


def test_objective_starts_active_and_listed(game, mission):
    game.game_time.t = 3.0
    objective = mission.objective("Reach the nav point")

    assert mission.objectives == [objective]
    assert objective.active() and not objective.done() and not objective.failed()
    assert objective.label() == "Reach the nav point"
    assert objective.changed_at_s == 3.0


def test_objective_is_ticked_by_its_done_condition(game, mission):
    flag = []
    objective = mission.objective("Reach the nav point", done=lambda: bool(flag))
    mission.update()
    assert objective.active()

    flag.append(True)
    game.game_time.t = 5.0
    mission.update()

    assert objective.done()
    assert objective.changed_at_s == 5.0


def test_objective_is_failed_by_its_failed_condition(mission):
    lost = []
    objective = mission.objective(
        "Stay with the formation", done=lambda: False, failed=lambda: bool(lost)
    )
    lost.append(True)
    mission.update()

    assert objective.failed()
    assert mission.triggers == []  # both rules retired


def test_a_settled_objective_stays_settled(mission):
    both = mission.objective("Scan it", done=lambda: True, failed=lambda: True)
    mission.update()
    assert both.done()  # its done rule came first

    both.fail()
    assert both.done()


def test_objective_progress_completes_it_at_the_goal(mission):
    count = [0]
    objective = mission.objective("Destroy the TIEs", progress=lambda: count[0], goal=3)
    assert objective.label() == "Destroy the TIEs (0/3)"

    count[0] = 3
    mission.update()

    assert objective.done()
    assert objective.label() == "Destroy the TIEs (3/3)"


def test_objective_progress_freezes_once_settled(mission):
    count = [1]
    objective = mission.objective(
        "Keep the transports alive", progress=lambda: count[0], goal=3, done=None
    )
    objective.fail()

    count[0] = 0
    assert objective.label() == "Keep the transports alive (1/3)"


def test_objective_counts_kills(game, mission, spawned):
    wave = mission.spawn(WAVE)
    objective = mission.objective(
        "Shoot down two bombers", progress=mission.kills(wave, by_player=True), goal=2
    )
    run_jobs(mission)
    player = DamageSource.of(game.player.pawn, game)

    kill_all(game, wave.pawns()[:1], by=player)
    kill_all(game, wave.pawns()[1:2])
    mission.update()
    assert objective.label() == "Shoot down two bombers (1/2)"

    kill_all(game, wave.pawns(), by=player)
    mission.update()
    assert objective.done()


def test_removed_objective_leaves_the_list_and_its_rules(mission):
    objective = mission.objective("Scan it", done=lambda: False)

    objective.remove()

    assert mission.objectives == []
    assert all(trigger.cancelled for trigger in mission.triggers)


def test_ending_the_level_settles_objectives_due_this_frame(game, mission):
    """
    A rule ending the level that fires before an objective's rule (same
    condition, registered first) still sees the objective settled in the
    level's tally.
    """
    wiped = []
    states_at_end = []
    game.end_level = lambda outcome, text="": states_at_end.append(objective.state)
    mission.on(lambda: bool(wiped), lambda: mission.defeat("Wiped out."))
    objective = mission.objective("Keep them alive", failed=lambda: bool(wiped))

    wiped.append(True)
    advance(game, mission, LEVEL_END_DELAY_S + 0.1)

    assert states_at_end == ["failed"]


def test_objectives_work_headless(game, mission):
    game.headless = True
    objective = mission.objective("Reach the nav point", done=lambda: True)

    mission.update()

    assert objective.done()
    assert game.hud.messages == []


# ---------------------------------------------------------------------------
# Kills
# ---------------------------------------------------------------------------


def test_ids_of_keeps_the_dead(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    ids = [pawn.id for pawn in wave.pawns()]
    kill_all(game, wave.pawns())

    assert ids_of(wave) == ids
    assert ids_of(game.player) == [game.player.pawn.id]
    assert ids_of([wave, game.player.pawn]) == [*ids, game.player.pawn.id]


def test_kills_counts_a_waves_deaths_and_the_players_share(game, mission, spawned):
    wave = mission.wave(WAVE)
    everyone = mission.kills()
    wave_kills = mission.kills(wave)
    player_kills = mission.kills(wave, by_player=True)
    wave.spawn()
    run_jobs(mission)
    pawns = wave.pawns()
    player = DamageSource.of(game.player.pawn, game)

    kill_all(game, pawns[:2], by=player)
    kill_all(game, pawns[2:])

    assert (everyone(), wave_kills(), player_kills()) == (3, 3, 2)


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


def test_follow_puts_the_leader_first_and_drops_routes(game, mission, spawned):
    spec = WaveSpec(
        name="flight",
        ship_model="x-wing",
        size=2,
        spawn_point=[0, 0, 0],
        formation="arrowhead",
        waypoints=[[0, 100, 0]],
    )
    wave = mission.spawn(spec)
    run_jobs(mission)
    old_leader, wingman = wave.pawns()
    wave.follow(game.player)
    assert wave.formation.ship_ids == [game.player.pawn.id, old_leader.id, wingman.id]
    assert game.player.pawn.formation is wave.formation
    assert all(bot.navigator.waypoints == [] for bot in spawned)


def test_break_formation(mission, spawned):
    spec = WaveSpec(
        name="flight",
        ship_model="x-wing",
        size=3,
        spawn_point=[0, 0, 0],
        formation="arrowhead",
        waypoints=[[0, 100, 0]],
    )
    wave = mission.spawn(spec)
    run_jobs(mission)
    formation = wave.formation
    wave.break_formation()
    assert wave.formation is None
    assert formation.ship_ids == []
    assert all(pawn.formation is None for pawn in wave.pawns())
    # Each keeps its own route
    assert all(len(bot.navigator.waypoints) == 1 for bot in spawned)


def test_follow_creates_a_formation_if_the_wave_has_none(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    wave.follow(game.player)
    assert wave.formation is not None
    assert wave.formation.ship_ids[0] == game.player.pawn.id
    assert len(wave.formation.ship_ids) == WAVE.size + 1


def test_set_targets_skips_scripted_capital_ships(mission, spawned):
    capital_ships = mission.spawn(
        WaveSpec(name="isd", ship_model="isd", size=1, spawn_point=[0, 0, 0])
    )
    defenders = mission.spawn(
        WaveSpec(name="def", ship_model="x", size=1, spawn_point=[0, 0, 0])
    )
    run_jobs(mission)
    capital_ships.pawns()[0].parent.tactician = None  # as a scripted capital ship
    capital_ships.set_targets(defenders)  # must not raise
    assert capital_ships.pawns()[0].parent.tactician is None


def test_follow_leaves_scripted_capital_ships_out(game, mission, spawned):
    spec = WaveSpec(
        name="group",
        ship_model="x",
        size=2,
        spawn_point=[0, 0, 0],
        waypoints=[[0, 100, 0]],
    )
    wave = mission.spawn(spec)
    run_jobs(mission)
    capital_ship, fighter = wave.pawns()
    capital_ship.parent.tactician = None  # as a scripted capital ship
    wave.follow(game.player)
    assert wave.formation.ship_ids == [game.player.pawn.id, fighter.id]
    assert capital_ship.parent.navigator.waypoints != []
    assert fighter.parent.navigator.waypoints == []


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


def test_pawns_of_a_list(game, mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    assert pawns_of([wave, game.player]) == wave.pawns() + [game.player.pawn]
    game.player.pawn.is_dead = True
    assert pawns_of((wave, game.player)) == wave.pawns()


def test_spawn_target_accepts_a_list(game, mission, spawned):
    escort = mission.spawn(WAVE)
    run_jobs(mission)
    hunters = mission.spawn(WAVE, target=[escort, game.player])
    run_jobs(mission)
    expected = [pawn.id for pawn in escort.pawns()] + [game.player.pawn.id]
    for pawn in hunters.pawns():
        assert pawn.parent.tactician.primary_target_ids == expected


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


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

SUBJECT = WaveSpec(
    name="subject", ship_model="gr-75", size=1, team=0, spawn_point=[0, 500, 0]
)


def _subject(game, mission):
    """A spawned, scannable wave ahead of the player, and its scan pawn."""
    wave = mission.spawn(SUBJECT)
    advance(game, mission, 0.1)
    return wave, wave.pawns()[0]


def test_scan_fills_while_the_target_is_held(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    scan = mission.scan(wave, duration_s=15)
    game.player.pawn.target = pawn
    advance(game, mission, 7.5)
    assert pawn.scan.progress == pytest.approx(0.5, abs=0.01)
    assert scan.started() and not scan.complete()
    assert pawn.scan.status_text.startswith("SCANNING")
    advance(game, mission, 8)
    assert scan.complete()
    assert pawn.scan.result == "clear"
    assert pawn.scan.status_text == "CLEAR"


def test_scan_reveals_contraband(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    scan = mission.scan(wave, contraband=True)
    game.player.pawn.target = pawn
    advance(game, mission, 16)
    assert scan.complete()
    assert pawn.scan.result == "contraband"


@pytest.mark.parametrize(
    "breaking",
    [
        "untargeted",
        "out_of_range",
        "off_cone",
    ],
)
def test_scan_does_not_fill_unless_held(game, mission, spawned, breaking):
    wave, pawn = _subject(game, mission)
    mission.scan(wave, range_m=1000, cone_deg=10)
    game.player.pawn.target = pawn
    if breaking == "untargeted":
        game.player.pawn.target = None
    elif breaking == "out_of_range":
        pawn.position = np.array([0.0, 1500.0, 0.0])
    else:
        pawn.position = np.array([200.0, 500.0, 0.0])  # ~22 deg off the nose
    advance(game, mission, 5)
    assert pawn.scan.progress == 0.0


def test_scan_does_not_fill_once_the_player_is_removed(game, mission, spawned):
    """A dead player is no longer in the interactions: the scan just stops."""
    wave, pawn = _subject(game, mission)
    mission.scan(wave)
    game.player.pawn.target = pawn
    game.interactions.kill(game.player.pawn)
    advance(game, mission, 2)
    assert pawn.scan.progress == 0.0


def test_scan_decays_at_half_rate_when_broken(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    scan = mission.scan(wave, duration_s=10, decay_ratio=0.5)
    game.player.pawn.target = pawn
    advance(game, mission, 6)
    held = pawn.scan.progress
    game.player.pawn.target = None
    advance(game, mission, 4)
    assert pawn.scan.progress == pytest.approx(held - 0.2, abs=0.01)
    assert not scan.complete()


def test_scan_freezes_once_complete(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    mission.scan(wave, duration_s=1)
    game.player.pawn.target = pawn
    advance(game, mission, 2)
    game.player.pawn.target = None
    advance(game, mission, 5)
    assert pawn.scan.progress == 1.0
    assert pawn.scan.complete


def test_scan_picks_up_a_wave_spawned_later(game, mission, spawned):
    wave = mission.wave(SUBJECT)
    scan = mission.scan(wave, duration_s=1)
    advance(game, mission, 1)
    assert not scan.complete()
    wave.spawn()
    advance(game, mission, 0.1)
    game.player.pawn.target = wave.pawns()[0]
    advance(game, mission, 1.5)
    assert scan.complete()


def test_scan_progress_at_least(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    scan = mission.scan(wave, duration_s=10)
    half = scan.progress_at_least(0.5)
    game.player.pawn.target = pawn
    advance(game, mission, 4)
    assert not half()
    advance(game, mission, 2)
    assert half()


def test_spawn_orientation_can_be_given_at_spawn_time(mission, spawned):
    mission.spawn(WAVE, orientation=(0.5, 0.5, 0.5, 0.5))
    for _ in range(WAVE.size):
        mission.update()
    assert all(list(bot.ini_orientation) == [0.5, 0.5, 0.5, 0.5] for bot in spawned)


def test_damaged(game, mission, spawned):
    wave, pawn = _subject(game, mission)
    cond = damaged(wave)
    assert not cond()
    pawn.shield_level = 0.0
    pawn.health -= 1
    assert cond()


# ---------------------------------------------------------------------------
# Mission.launch: fighters launched from a hangar, as a wave
# ---------------------------------------------------------------------------


@pytest.fixture
def hangar(game):
    """A stocked (fake) hangar of team 2."""
    hangar = FakeHangar(game, team=2, name="hangar_0", group_size=3)
    hangar.set_stock({"tie-fighter": 4, "tie-bomber": 0})
    return hangar


def test_launch_returns_a_wave_of_the_requested_fighters(mission, hangar):
    squadron = mission.launch(hangar, "tie-fighter", 2)

    assert squadron.spec.ship_model == "tie-fighter"
    assert squadron.spec.size == 2
    assert squadron.spec.team == 2
    assert squadron.name == "hangar_0_tie-fighter"
    assert squadron.ids == []  # nothing has left the bay yet


def test_launch_defaults_to_the_hangars_group_and_takes_a_name(mission, hangar):
    squadron = mission.launch(hangar, "tie-fighter", name="red")

    assert squadron.spec.size == hangar.group_size
    assert squadron.name == "red"


def test_launched_fighters_join_the_wave_as_they_leave_the_bay(mission, hangar):
    squadron = mission.launch(hangar, "tie-fighter", 2)

    hangar.launch_next()
    assert squadron.ids == [hangar.launched[0].pawn.id]
    hangar.launch_next()
    assert [pawn.id for pawn in squadron.pawns()] == [
        bot.pawn.id for bot in hangar.launched
    ]
    assert squadron.alive()


def test_launched_wave_flies_in_an_arrowhead_by_default(mission, hangar):
    squadron = mission.launch(hangar, "tie-fighter", 2)
    hangar.launch_pending()

    assert squadron.spec.formation == "arrowhead"
    assert squadron.launch_order.formation_shape == "arrowhead"
    assert squadron.formation is squadron.launch_order.formation
    assert squadron.formation.ship_ids == squadron.ids


def test_launch_sets_the_waves_formation(mission, hangar):
    """The formation shape and spacing go to the wave's spec and the request."""
    squadron = mission.launch(
        hangar, "tie-fighter", 2, formation="diamond", formation_scale_m=80.0
    )
    hangar.launch_pending()

    assert squadron.spec.formation == "diamond"
    assert squadron.spec.formation_scale_m == 80.0
    expected = Formation(scale_m=80.0, shape="diamond").relative_positions
    np.testing.assert_allclose(squadron.formation.relative_positions, expected)


def test_launch_without_formation(mission, hangar):
    squadron = mission.launch(hangar, "tie-fighter", 2, formation=None)
    hangar.launch_pending()

    assert squadron.formation is None
    assert squadron.launch_order.formation is None


def test_each_launched_fighter_attacks_the_target(mission, spawned, hangar):
    """
    The target is resolved as each fighter launches: fighters leaving the bay
    after a new prey appeared attack it too.
    """
    prey = mission.spawn(
        WaveSpec(name="prey", ship_model="x-wing", size=1, spawn_point=[0, 0, 0])
    )
    run_jobs(mission)
    squadron = mission.launch(hangar, "tie-fighter", 2, target=prey)

    hangar.launch_next()
    prey.spawn()  # a second prey joins the wave
    run_jobs(mission)
    hangar.launch_next()

    first, second = (bot.tactician.primary_target_ids for bot in hangar.launched)
    prey_ids = [pawn.id for pawn in prey.pawns()]
    assert first == prey_ids[:1]
    assert second == prey_ids
    assert len(squadron.ids) == 2


def test_launched_wave_is_destroyed_only_once_the_launch_is_over(game, mission, hangar):
    """
    all_destroyed never reads True between two launches: the first fighter
    dying before the second leaves the bay does not wipe the wave.
    """
    squadron = mission.launch(hangar, "tie-fighter", 2)
    assert not squadron.all_destroyed()  # nothing launched yet

    hangar.launch_next()
    kill_all(game, squadron.pawns())
    assert not squadron.all_destroyed()  # one more to come
    assert squadron.any_destroyed()

    hangar.launch_next()
    kill_all(game, squadron.pawns())
    assert squadron.all_destroyed()


def test_launched_wave_is_destroyed_when_its_type_runs_out(game, mission, hangar):
    """A launch cut short by the stock is over once the stock is spent."""
    squadron = mission.launch(hangar, "tie-fighter", 6)  # only 4 in stock

    hangar.launch_pending()
    assert len(squadron.ids) == 4
    assert squadron.launch_order.cancelled
    kill_all(game, squadron.pawns())
    assert squadron.all_destroyed()


def test_launching_an_empty_type_gives_a_wave_already_over(mission, hangar):
    """An empty type launches nothing: the wave reads destroyed at once."""
    squadron = mission.launch(hangar, "tie-bomber", 3)

    assert squadron.ids == []
    assert squadron.all_destroyed()
    assert not squadron.any_destroyed()


def test_launching_a_type_not_in_the_stock_raises(mission, hangar):
    with pytest.raises(KeyError):
        mission.launch(hangar, "tie-interceptor")


def test_launched_wave_is_a_who(mission, hangar):
    """A launched wave designates its live fighters, e.g. as a target."""
    squadron = mission.launch(hangar, "tie-fighter", 2)
    hangar.launch_pending()

    assert pawns_of(squadron) == squadron.pawns()
    assert near(squadron, [0, 0, 0], 10)()


def test_a_launched_wave_cannot_be_spawned(mission, hangar):
    """It has no spawn point: its fighters come from the hangar."""
    squadron = mission.launch(hangar, "tie-fighter", 2)

    with pytest.raises(ValueError):
        squadron.spawn()
