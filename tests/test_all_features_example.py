"""
Tests for the all-features reference examples
(docs/source/examples/all_features_example.{py,yaml} and
all_features_example_trigger_dsl.yaml).

These run each example end-to-end against a lightweight fake game -- the same
style of fake used by tests/test_mission.py and tests/test_scenario.py -- to
prove the examples actually work, not just that they parse. "Combat" (ships
dying, a patrol reaching a waypoint) is simulated by the test itself reaching
into the fake world directly, exactly as test_mission.py's
test_any_destroyed_* tests do.
"""

import importlib.util
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

from space_flight.game.scenario import Scenario
from space_flight.game.scenario.loader import load_scenario, load_waves
from space_flight.game.scenario.mission import Mission

EXAMPLES_DIR = Path(__file__).parent.parent / "docs" / "source" / "examples"


def _load_example_module(name: str):
    """Import a docs/source/examples/*.py file by path (it is not a package)."""
    spec = importlib.util.spec_from_file_location(name, EXAMPLES_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fakes (see test_mission.py for the pattern this mirrors)
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


@pytest.fixture(autouse=True)
def patch_player_waypoints(monkeypatch):
    """
    actions.player_waypoints builds a real PlayerWaypoints, which loads a
    Panda3D model for its marker -- needs a running engine (game.app), which
    these fakes do not provide. Stub it out, mirroring how spawn_bot is
    stubbed for the same reason.
    """
    calls = []

    def fake_player_waypoints(game, points, **kwargs):
        calls.append((points, kwargs))

    monkeypatch.setattr(
        "space_flight.game.scenario.actions.PlayerWaypoints", fake_player_waypoints
    )
    return calls


@pytest.fixture
def game():
    return FakeGame()


def _find(spawned, prefix):
    """The (first) spawned bot whose name starts with prefix, or None."""
    return next((b for b in spawned if b.name and b.name.startswith(prefix)), None)


def _find_all(spawned, prefix):
    return [b for b in spawned if b.name and b.name.startswith(prefix)]


def _step(game, dt=0.1, max_steps=2000, on_each_step=lambda: None):
    """
    Advance the fake game clock and the scenario one frame at a time.

    :param on_each_step: Called after every scenario.update, so a test can
        react to newly-spawned bots (simulate a waypoint being reached, a
        ship dying, ...) exactly when they appear.
    """
    for _ in range(max_steps):
        game.game_time.t += dt
        game.scenario.update(game)
        on_each_step()


# ---------------------------------------------------------------------------
# all_features_example.py / .yaml -- the Mission API
# ---------------------------------------------------------------------------


def test_all_features_mission_runs_to_victory(game, patch_spawn_bot):
    example = _load_example_module("all_features_example")
    waves = load_waves(EXAMPLES_DIR / "all_features_example.yaml")

    mission = Mission(game)
    mission.waves = waves
    game.scenario.schedule(example.all_features_mission(mission))

    def simulate_world():
        # Once the patrol ship AND the whole boarding party exist, mark the
        # patrol's first waypoint reached, unblocking the mission body's
        # `wait_until(reached_waypoint("patrol", 0))` -- there is no real
        # navigator ticking in this fake, so this stands in for "some time
        # passes while the patrol travels" (which, in a real game, takes much
        # longer than the few frames every wave needs to finish spawning).
        patrol_bot = _find(patch_spawn_bot, "patrol_")
        boarding_bots = _find_all(patch_spawn_bot, "boarding_party_")
        if (
            patrol_bot is not None
            and len(boarding_bots) == 3
            and patrol_bot.navigator.next_waypoint_idx == 0
        ):
            patrol_bot.navigator.next_waypoint_idx = 1

    _step(game, on_each_step=simulate_world)

    assert game.end_level_calls == [
        (
            "victory",
            "Mission complete: every scripted feature exercised without incident.",
        )
    ]

    # Mission.spawn(target=...) (runtime override) resolved against homeguard.
    homeguard_pawn_id = game.scenario.resolve(game, "homeguard")[0].id
    strike_bots = _find_all(patch_spawn_bot, "strike_wave_")
    assert len(strike_bots) == 4
    for bot in strike_bots:
        assert homeguard_pawn_id in bot.tactician.primary_target_ids

    # wave cfg's static `target:` key, for reinforcements.
    reinforcement_bots = _find_all(patch_spawn_bot, "reinforcements_")
    assert len(reinforcement_bots) == 2
    for bot in reinforcement_bots:
        assert homeguard_pawn_id in bot.tactician.primary_target_ids

    # join=: reinforcements attached to strike_wave's own formation, sharing
    # slots 4-5 after strike_wave's own 0-3.
    assert (
        game.scenario.formation_by_group["reinforcements"]
        is game.scenario.formation_by_group["strike_wave"]
    )
    assert len(game.scenario.formation_by_group["strike_wave"].ship_ids) == 6

    # Mixed-composition wave: 2 bombers + 1 interceptor, no explicit size.
    boarding_bots = _find_all(patch_spawn_bot, "boarding_party_")
    assert len(boarding_bots) == 3

    # allow_respawn: true let the same wave id spawn twice.
    assert len(_find_all(patch_spawn_bot, "respawnable_probe_")) == 2

    # set_team + set_targets, applied live to the patrol ship.
    patrol_bot = _find(patch_spawn_bot, "patrol_")
    assert patrol_bot.pawn.team == 2
    boarding_pawn_ids = {b.pawn.id for b in boarding_bots}
    assert boarding_pawn_ids.issubset(set(patrol_bot.tactician.primary_target_ids))

    # set_waypoints, applied live to the patrol ship.
    assert [tuple(w) for w in patrol_bot.navigator.waypoints] == [
        (500, -1000, 500),
        (500, -2000, 500),
    ]
    assert patrol_bot.navigator.is_loop is False

    # register(): the home guard's own ships also resolve under the alias.
    assert game.scenario.resolve(game, "vip_ship")[0].id == homeguard_pawn_id

    # register_query() + any_alive: the repeating enemy-fighter ping fired.
    assert any("Enemy fighters detected." == text for text, _ in game.hud.messages)

    # The reactive defeat contingency never fired -- the home guard was never
    # touched in this happy-path run.
    assert not game.scenario.has_fired("defeat")


def test_all_features_mission_defeat_contingency(game, patch_spawn_bot):
    """
    The reactive "home guard wiped -> defeat 3s later" rule (any_destroyed /
    all_destroyed / Delay / fired composed together) fires on its own,
    independently of the sequential body's own ending.
    """
    example = _load_example_module("all_features_example")
    waves = load_waves(EXAMPLES_DIR / "all_features_example.yaml")

    mission = Mission(game)
    mission.waves = waves
    game.scenario.schedule(example.all_features_mission(mission))

    # Let the home guard actually spawn, then wipe it out immediately.
    _step(game, max_steps=5)
    homeguard_pawn = game.scenario.resolve(game, "homeguard")[0]
    game.interactions.kill(homeguard_pawn)

    _step(game, max_steps=200)

    assert game.scenario.has_fired("homeguard_hit")
    assert game.scenario.has_fired("homeguard_wiped")
    assert game.scenario.has_fired("defeat")
    assert ("defeat", "The home guard was destroyed.") in game.end_level_calls


# ---------------------------------------------------------------------------
# all_features_example_trigger_dsl.yaml -- the legacy YAML trigger DSL
# ---------------------------------------------------------------------------


def test_all_features_example_trigger_dsl_fires_every_condition(patch_spawn_bot):
    game = FakeGame()
    game.scenario = load_scenario(
        EXAMPLES_DIR / "all_features_example_trigger_dsl.yaml"
    )

    _step(game, max_steps=15)  # let both waves finish spawning

    assert game.scenario.has_fired("spawn_homeguard")
    assert game.scenario.has_fired("spawn_strike_wave")

    # any_destroyed / all_destroyed: the home guard has only one ship, so
    # killing it satisfies both at once (any_destroyed stays true after a
    # total wipe too).
    homeguard_pawn = game.scenario.resolve(game, "homeguard")[0]
    game.interactions.kill(homeguard_pawn)
    _step(game, max_steps=5)
    assert game.scenario.has_fired("homeguard_hit")
    assert game.scenario.has_fired("homeguard_wiped")

    # delay + fired: "defeat" arms the moment homeguard_wiped fires and
    # reports true only 3s later.
    assert not game.scenario.has_fired("defeat")
    _step(game, dt=1.0, max_steps=4)
    assert game.scenario.has_fired("defeat")
    assert ("defeat", "The home guard was destroyed.") in game.end_level_calls

    # reached_waypoint: any live strike_wave member past waypoint index 1.
    strike_bot = _find(patch_spawn_bot, "strike_wave_")
    strike_bot.navigator.next_waypoint_idx = 2
    _step(game, max_steps=1)
    assert game.scenario.has_fired("strike_wave_turned_back")

    # near + once: false: repeats while the player stays in range, not just
    # the first time.
    assert not game.scenario.has_fired("proximity_warning")  # not a latch
    game.player.pawn.position = np.array([0, -1000, 200], dtype=float)
    before = len(game.hud.messages)
    _step(game, max_steps=1)
    assert len(game.hud.messages) == before + 1
    _step(game, max_steps=1)
    assert len(game.hud.messages) == before + 2  # fires again: once: false

    # all_of / any_of + player_waypoints + end_level: wipe out strike_wave to
    # complete the victory condition.
    for bot in _find_all(patch_spawn_bot, "strike_wave_"):
        game.interactions.kill(bot.pawn)
    _step(game, max_steps=1)
    assert game.scenario.has_fired("victory")
    assert ("victory", "The blockade is broken.") in game.end_level_calls
