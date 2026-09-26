"""
Tests for the Python Mission authoring API
(:mod:`space_flight.game.scenario.mission`) and the small engine fixes it
relies on (the fixed any_destroyed, formation-join spawning, mixed-composition
waves, the team-cascade helper).

Mirrors the fakes used in test_scenario.py: real Bot/Pawn construction needs a
running Panda3D engine, so spawn_bot is monkeypatched with a lightweight stub
and the "pawn" objects here are plain mocks carrying just the attributes the
scenario engine and the Mission API touch.
"""

import uuid
from pathlib import Path

import numpy as np
import pytest

from space_flight.game.scenario import Scenario
from space_flight.game.scenario.actions import _validate_wave_cfg, set_bot_team
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission, WaveHandle

LEVELS_DIR = Path(__file__).parent.parent / "src" / "space_flight" / "game" / "levels"

# ---------------------------------------------------------------------------
# Fakes (see test_scenario.py for the pattern this mirrors)
# ---------------------------------------------------------------------------


class FakeGameTime:
    def __init__(self):
        self.t = 0.0

    def get_current_time(self):
        return self.t


class FakeInteractions:
    def __init__(self):
        self.actors = []
        self.actors_id_dict = {}

    def add(self, actor):
        slot = len(self.actors)
        self.actors.append(actor)
        self.actors_id_dict[actor.id] = slot

    def kill(self, actor):
        slot = self.actors_id_dict.pop(actor.id)
        self.actors[slot] = None

    @property
    def live_actors(self):
        return [self.actors[s] for s in self.actors_id_dict.values()]


class MockNavigator:
    def __init__(self):
        self.next_waypoint_idx = 0
        self.waypoints = []
        self.is_loop = False

    def set_waypoints(self, waypoints, is_loop=False):
        self.waypoints = waypoints
        self.is_loop = is_loop


class MockPawn:
    def __init__(self, parent, position, team):
        self.id = uuid.uuid4()
        self.parent = parent
        self.position = np.array(position, dtype=float)
        self.team = team


class MockBot:
    """Bot stub carrying the attributes the scenario engine/Mission touch."""

    def __init__(self, name, position, team):
        self.name = name
        self.team = team
        self.pawn = MockPawn(self, position, team)
        self.navigator = MockNavigator()

        class _Tactician:
            primary_target_ids = None

        self.tactician = _Tactician()
        self.tactician.primary_target_ids = []


class MockHud:
    def __init__(self):
        self.messages = []
        self.chatter = []

    def set_event_text(self, text, display_time_s=2.5):
        self.messages.append((text, display_time_s))

    def set_chatter_text(self, text, display_time_s=4.0):
        self.chatter.append((text, display_time_s))


class FakeGame:
    def __init__(self):
        self.game_time = FakeGameTime()
        self.interactions = FakeInteractions()
        self.hud = MockHud()
        self.scenario = Scenario()
        self.headless = False
        self.end_level_calls = []
        self.player = MockBot("player", [0, 0, 0], team=1)

    def end_level(self, outcome, text=""):
        self.end_level_calls.append((outcome, text))


@pytest.fixture
def patch_spawn_bot(monkeypatch):
    spawned = []

    def fake_spawn_bot(game, **kwargs):
        bot = MockBot(
            name=kwargs.get("name"),
            position=kwargs.get("ini_position"),
            team=kwargs.get("team", 2),
        )
        game.interactions.add(bot.pawn)
        spawned.append(bot)
        return bot

    monkeypatch.setattr("space_flight.game.scenario.spawn_bot", fake_spawn_bot)
    return spawned


@pytest.fixture
def game():
    return FakeGame()


@pytest.fixture
def mission(game):
    return Mission(game)


def _run_jobs(game, n=1000):
    """Step the scenario until its jobs list is empty, or n steps pass."""
    for _ in range(n):
        if not game.scenario.jobs:
            return
        game.scenario.update(game)


WAVE_CFG = {
    "id": "wave_a",
    "size": 3,
    "ship_model": "tie-bomber",
    "spawn_point": [100, 200, 300],
}


# ---------------------------------------------------------------------------
# any_destroyed (engine fix)
# ---------------------------------------------------------------------------


def test_any_destroyed_false_before_spawn(game):
    assert game.scenario.any_destroyed(game, "wave") is False


def test_any_destroyed_true_after_one_loss_and_stays_true_when_all_lost(game):
    a = MockBot("a", [0, 0, 0], team=2)
    b = MockBot("b", [0, 0, 0], team=2)
    game.interactions.add(a.pawn)
    game.interactions.add(b.pawn)
    game.scenario.register("wave", [a, b])

    assert game.scenario.any_destroyed(game, "wave") is False
    game.interactions.kill(a.pawn)
    assert game.scenario.any_destroyed(game, "wave") is True
    # all_destroyed is not true yet (b still alive) -- the two are independent
    assert game.scenario.all_destroyed(game, "wave") is False

    game.interactions.kill(b.pawn)
    # any_destroyed stays true after a total wipe too
    assert game.scenario.any_destroyed(game, "wave") is True
    assert game.scenario.all_destroyed(game, "wave") is True


def test_any_destroyed_condition_matches_scenario_method(game):
    a = MockBot("a", [0, 0, 0], team=2)
    game.interactions.add(a.pawn)
    game.scenario.register("wave", [a])
    from space_flight.game.scenario.conditions import any_destroyed

    check = any_destroyed("wave")
    assert check(game) is False
    game.interactions.kill(a.pawn)
    assert check(game) is True


# ---------------------------------------------------------------------------
# Wave cfg validation
# ---------------------------------------------------------------------------


def test_validate_wave_cfg_accepts_well_formed():
    _validate_wave_cfg(WAVE_CFG)  # must not raise


def test_validate_wave_cfg_rejects_missing_key():
    with pytest.raises(ValueError, match="wave_a"):
        _validate_wave_cfg({"id": "wave_a", "ship_model": "x"})


def test_validate_wave_cfg_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown key"):
        _validate_wave_cfg({**WAVE_CFG, "not_a_real_key": 1})


def test_validate_wave_cfg_mixed_composition_does_not_need_size():
    cfg = {
        "id": "mixed",
        "ship_model": [{"ship_model": "x-wing", "count": 2}],
        "spawn_point": [0, 0, 0],
    }
    _validate_wave_cfg(cfg)  # must not raise


# ---------------------------------------------------------------------------
# Mission.spawn
# ---------------------------------------------------------------------------


def test_mission_spawn_validates_and_returns_handle(mission, game, patch_spawn_bot):
    handle = mission.spawn(WAVE_CFG)
    assert isinstance(handle, WaveHandle)
    assert handle.name == "wave_a"
    _run_jobs(game)
    assert len(patch_spawn_bot) == WAVE_CFG["size"]


def test_mission_spawn_rejects_bad_cfg(mission):
    with pytest.raises(ValueError):
        mission.spawn({"id": "bad"})


def test_mission_spawn_with_target_wavehandle(mission, game, patch_spawn_bot):
    transports = mission.spawn(
        {"id": "transports", "size": 1, "ship_model": "cr-90", "spawn_point": [0, 0, 0]}
    )
    _run_jobs(game)
    mission.spawn({**WAVE_CFG, "id": "attackers"}, target=transports)
    _run_jobs(game)
    transport_pawn_id = game.scenario.resolve(game, "transports")[0].id
    for bot in patch_spawn_bot[1:]:
        assert transport_pawn_id in bot.tactician.primary_target_ids


def test_mission_spawn_mixed_ship_types(mission, game, patch_spawn_bot):
    cfg = {
        "id": "mixed_wave",
        "ship_model": [
            {"ship_model": "x-wing", "count": 2},
            {"ship_model": "y-wing", "count": 1},
        ],
        "spawn_point": [0, 0, 0],
    }
    mission.spawn(cfg)
    _run_jobs(game)
    assert len(patch_spawn_bot) == 3
    assert len(game.scenario.resolve(game, "mixed_wave")) == 3


def test_mission_spawn_join_formation_continues_slots(mission, game, patch_spawn_bot):
    escort = mission.spawn(
        {
            "id": "escort",
            "size": 2,
            "ship_model": "x-wing",
            "spawn_point": [0, 0, 0],
            "formation": {"scale_m": 30, "shape": "arrowhead"},
        }
    )
    _run_jobs(game)
    formation = escort.formation
    assert formation is not None
    assert len(formation.ship_ids) == 2

    reinforcements = mission.spawn(
        {
            "id": "reinforcements",
            "size": 2,
            "ship_model": "x-wing",
            "spawn_point": [0, 0, 0],
        },
        join=formation,
    )
    _run_jobs(game)
    assert len(formation.ship_ids) == 4
    assert reinforcements.formation is formation


# ---------------------------------------------------------------------------
# WaveHandle
# ---------------------------------------------------------------------------


def test_wave_handle_alive_and_all_destroyed(mission, game, patch_spawn_bot):
    wave = mission.spawn(WAVE_CFG)
    _run_jobs(game)
    assert wave.alive is True
    assert wave.all_destroyed is False
    for bot in list(patch_spawn_bot):
        game.interactions.kill(bot.pawn)
    assert wave.alive is False
    assert wave.all_destroyed is True
    assert wave.any_destroyed is True


def test_wave_handle_conditions_usable_with_wait_until(mission, game, patch_spawn_bot):
    wave = mission.spawn(WAVE_CFG)
    _run_jobs(game)
    cond = wave.all_destroyed_cond()
    assert cond(game) is False
    for bot in list(patch_spawn_bot):
        game.interactions.kill(bot.pawn)
    assert cond(game) is True


def test_wave_handle_set_targets(mission, game, patch_spawn_bot):
    attackers = mission.spawn(WAVE_CFG)
    _run_jobs(game)
    defenders = mission.spawn({**WAVE_CFG, "id": "defenders"})
    _run_jobs(game)

    attackers.set_targets(defenders)
    defender_ids = {p.id for p in game.scenario.resolve(game, "defenders")}
    for bot in patch_spawn_bot:
        if bot.pawn.id not in defender_ids:
            assert set(bot.tactician.primary_target_ids) == defender_ids


def test_wave_handle_set_waypoints(mission, game, patch_spawn_bot):
    wave = mission.spawn(WAVE_CFG)
    _run_jobs(game)
    wave.set_waypoints([[0, 0, 0], [0, 100, 0]], loop=False)
    for bot in patch_spawn_bot:
        assert len(bot.navigator.waypoints) == 2
        assert bot.navigator.is_loop is False


def test_wave_handle_set_team_lone_fighter(mission, game, patch_spawn_bot):
    wave = mission.spawn(WAVE_CFG)
    _run_jobs(game)
    wave.set_team(9)
    for bot in patch_spawn_bot:
        assert bot.pawn.team == 9
        assert bot.team == 9


# ---------------------------------------------------------------------------
# set_bot_team cascade (capital ship with mounted turrets)
# ---------------------------------------------------------------------------


class _FakeSubSystem:
    def __init__(self, team):
        self.team = team


class _FakeShield:
    def __init__(self, team):
        self.team = team


class _FakeCapitalPawn:
    def __init__(self, team, sub_systems, shield, mounted_bots):
        self.id = uuid.uuid4()
        self.team = team
        self.sub_systems = sub_systems
        self.shield = shield
        self.mounted_bots = mounted_bots


def test_set_bot_team_cascades_to_capital_ship_dependents():
    turret_bot = MockBot("turret", [0, 0, 0], team=2)
    tractor_bot = MockBot("tractor", [0, 0, 0], team=2)
    sub_systems = [_FakeSubSystem(team=2), _FakeSubSystem(team=2)]
    shield = _FakeShield(team=2)

    capital_bot = MockBot("frigate", [0, 0, 0], team=2)
    capital_bot.pawn = _FakeCapitalPawn(
        team=2,
        sub_systems=sub_systems,
        shield=shield,
        mounted_bots=[turret_bot, tractor_bot],
    )

    set_bot_team(capital_bot, 5)

    assert capital_bot.team == 5
    assert capital_bot.pawn.team == 5
    assert all(sub.team == 5 for sub in sub_systems)
    assert shield.team == 5
    assert turret_bot.team == 5
    assert turret_bot.pawn.team == 5
    assert tractor_bot.team == 5
    assert tractor_bot.pawn.team == 5


# ---------------------------------------------------------------------------
# Sequencing helpers
# ---------------------------------------------------------------------------


def test_wait_yields_until_seconds_elapsed(mission, game):
    game.game_time.t = 0
    gen = mission.wait(3)
    next(gen)  # primes the deadline (now + 3 = 3) and yields once, at t=0
    steps = 1
    while True:
        game.game_time.t += 1
        try:
            next(gen)
            steps += 1
        except StopIteration:
            break
    assert steps == 3  # yields at t=0, 1, 2; done once t=3 is reached


def test_wait_until_accepts_condition_or_number(mission, game):
    flag = {"v": False}
    gen = mission.wait_until(lambda g: flag["v"])
    assert next(gen) is None
    flag["v"] = True
    with pytest.raises(StopIteration):
        next(gen)

    gen2 = mission.wait_until(2)
    game.game_time.t = 0
    next(gen2)
    game.game_time.t = 2
    with pytest.raises(StopIteration):
        next(gen2)


def test_wait_any_and_wait_all(mission, game):
    a, b = {"v": False}, {"v": False}
    gen_any = mission.wait_any(lambda g: a["v"], lambda g: b["v"])
    next(gen_any)
    a["v"] = True
    with pytest.raises(StopIteration):
        next(gen_any)

    c, d = {"v": False}, {"v": False}
    gen_all = mission.wait_all(lambda g: c["v"], lambda g: d["v"])
    next(gen_all)
    c["v"] = True
    next(gen_all)  # d still false
    d["v"] = True
    with pytest.raises(StopIteration):
        next(gen_all)


# ---------------------------------------------------------------------------
# on() reactive rules
# ---------------------------------------------------------------------------


def test_on_registers_named_trigger(mission, game):
    calls = []
    mission.on(lambda g: True, lambda g: calls.append(1), name="my_rule")
    assert "my_rule" in game.scenario.triggers_by_name
    game.scenario.update(game)
    assert calls == [1]
    assert game.scenario.has_fired("my_rule") is True


# ---------------------------------------------------------------------------
# Thin action wrappers
# ---------------------------------------------------------------------------


def test_hud_speech_and_end_level_wrappers(mission, game):
    mission.hud("hello")
    assert game.hud.messages == [("hello", 2.5)]

    mission.speech("hi", speaker="Red Leader")
    assert game.hud.chatter == [("Red Leader: hi", 4.0)]

    mission.victory("won")
    assert game.end_level_calls == [("victory", "won")]

    mission.defeat("lost")
    assert game.end_level_calls[-1] == ("defeat", "lost")


# ---------------------------------------------------------------------------
# The 3 shipped levels' mission functions, run against fakes
# ---------------------------------------------------------------------------


def test_mission_waves_setter_predeclares_groups(mission):
    """
    Assigning Mission.waves pre-declares every wave id as an empty group on
    the scenario, mirroring what load_scenario does for the legacy DSL.
    """
    mission.waves = {"first_wave": {"id": "first_wave"}, "second_wave": {"id": "s"}}
    assert mission.scenario.groups == {"first_wave": [], "second_wave": []}


def test_reactive_rule_on_unspawned_wave_does_not_warn_unknown_group(
    mission, game, patch_spawn_bot, caplog
):
    """
    Regression test: a reactive rule registered up front (see the intro
    level's "blockade_past") polls reached_waypoint on a wave before it has
    spawned. Without Mission.waves pre-declaring the group, Scenario.resolve
    would log a spurious "unknown group 'transports'" warning on every frame
    until the wave actually spawns.
    """
    from space_flight.game.scenario.conditions import reached_waypoint

    mission.waves = load_waves(LEVELS_DIR / "intro_level.yaml")
    mission.on(reached_waypoint("transports", 8), lambda game: None, name="check")

    with caplog.at_level("WARNING"):
        for _ in range(5):  # well before transports spawns at 0.1s
            game.scenario.update(game)

    assert "unknown group" not in caplog.text


def test_dev_mission_spawns_frigate(game, patch_spawn_bot):
    from space_flight.game.levels.dev_level import dev_mission

    m = Mission(game)
    m.waves = load_waves(LEVELS_DIR / "dev_level.yaml")
    game.scenario.schedule(dev_mission(m))

    for _ in range(400):
        game.game_time.t += 1 / 60
        game.scenario.update(game)

    assert len(game.scenario.resolve(game, "enemy_frigate")) == 1


def test_race_mission_checkpoint_and_finish(game, patch_spawn_bot, monkeypatch):
    from space_flight.game.levels.race_level import race_mission

    # PlayerWaypoints needs a real app/loader to build its marker model; stub
    # it out (mirrors test_scenario.py's test_player_waypoints_action_creates_route).
    monkeypatch.setattr(
        "space_flight.game.scenario.actions.PlayerWaypoints",
        lambda game, points, **kwargs: None,
    )

    m = Mission(game)
    m.waves = load_waves(LEVELS_DIR / "race_level.yaml")
    game.scenario.schedule(race_mission(m))

    # Advance until the rivals have spawned (after 1s + one ship per frame).
    for _ in range(200):
        game.game_time.t += 1 / 60
        game.scenario.update(game)
    assert len(game.scenario.resolve(game, "rivals")) == 3

    # Player reaches the first checkpoint -> banter fires once.
    game.player.pawn.position = np.array([0.0, 2000.0, 500.0])
    game.scenario.update(game)
    assert any("Hobbie" in text for text, _ in game.hud.chatter)

    # Player crosses the finish line first -> victory.
    game.player.pawn.position = np.array([-3000.0, 12000.0, 500.0])
    game.scenario.update(game)
    assert game.end_level_calls[0][0] == "victory"


def test_intro_mission_full_sequence_to_victory(game, patch_spawn_bot):
    from space_flight.game.levels.intro_level import intro_mission

    m = Mission(game)
    m.waves = load_waves(LEVELS_DIR / "intro_level.yaml")
    game.scenario.schedule(intro_mission(m))

    def advance(seconds, dt=1 / 60):
        steps = int(seconds / dt) + 1
        for _ in range(steps):
            game.game_time.t += dt
            game.scenario.update(game)

    # Past the first three waves (transports at 0.1s, escort at 1s, first
    # wave at 10s) -- generous margin for the one-ship-per-frame spawn jobs.
    advance(12)
    assert len(game.scenario.resolve(game, "transports")) == 3
    assert len(game.scenario.resolve(game, "escort")) == 6
    assert len(game.scenario.resolve(game, "first_wave")) == 5

    # Wipe out the first wave -> third wave should arrive ~3s later (well
    # before the 200s fallback). Keep advancing past t=30s so the (purely
    # time-sequenced) second wave has also spawned by now.
    for pawn in list(game.scenario.resolve(game, "first_wave")):
        game.interactions.kill(pawn)
    advance(20)  # t ~= 32s
    assert len(game.scenario.resolve(game, "third_wave")) == 8
    assert len(game.scenario.resolve(game, "second_wave")) == 5

    # Wipe out the second wave and move transports past waypoint 8 -> the
    # blockade_past objective fires, and victory follows 3s later.
    for pawn in list(game.scenario.resolve(game, "second_wave")):
        game.interactions.kill(pawn)
    for pawn in game.scenario.resolve(game, "transports"):
        pawn.parent.navigator.next_waypoint_idx = 9
    advance(4)

    assert game.scenario.has_fired("blockade_past") is True
    assert any(o == "victory" for o, _ in game.end_level_calls)


def test_intro_mission_defeat_path(game, patch_spawn_bot):
    from space_flight.game.levels.intro_level import intro_mission

    m = Mission(game)
    m.waves = load_waves(LEVELS_DIR / "intro_level.yaml")
    game.scenario.schedule(intro_mission(m))

    def advance(seconds, dt=1 / 60):
        steps = int(seconds / dt) + 1
        for _ in range(steps):
            game.game_time.t += dt
            game.scenario.update(game)

    advance(2)  # transports and escort spawned
    for pawn in list(game.scenario.resolve(game, "transports")):
        game.interactions.kill(pawn)
    advance(4)

    assert game.scenario.has_fired("all_transports_destroyed") is True
    assert any(o == "defeat" for o, _ in game.end_level_calls)
