"""
Tests for the scenario scripting engine (:mod:`space_flight.game.scenario`).

These exercise the engine logic in isolation: triggers, group membership and
resolution, conditions/combinators, the YAML loader, and the wave-spawning
action. Real :class:`Bot` construction needs a running Panda3D engine, so
spawn_bot is monkeypatched with a lightweight stub.
"""

import uuid

import numpy as np
import pytest

from space_flight.game.scenario import Scenario, Trigger
from space_flight.game.scenario.actions import (
    end_level,
    player_waypoints,
    spawn_wave,
    speech,
)
from space_flight.game.scenario.conditions import (
    AllOf,
    AnyOf,
    Delay,
    after_seconds,
    fired,
    near,
    reached_waypoint,
)
from space_flight.game.scenario.loader import load_scenario

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGameTime:
    """Game clock stub whose time is set directly by the test."""

    def __init__(self):
        self.t = 0.0

    def get_current_time(self):
        return self.t


class FakeInteractions:
    """
    Minimal stand-in for :class:`Interactions` exposing only what
    :meth:`Scenario.resolve` reads: a slot list, an id->slot dict, and
    live_actors.
    """

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
    """Bot stub carrying the attributes the scenario engine touches."""

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
    """Bundles the few attributes conditions/actions reach through game."""

    def __init__(self, scenario):
        self.game_time = FakeGameTime()
        self.interactions = FakeInteractions()
        self.hud = MockHud()
        self.scenario = scenario
        self.method_lists = {}
        self.headless = False


@pytest.fixture
def patch_spawn_bot(monkeypatch):
    """
    Replace spawn_bot (as imported into the scenario module) with a stub
    that builds a :class:`MockBot` and registers its pawn in the fake
    interactions, returning the live list of spawned bots.
    """
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
    return FakeGame(Scenario())


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def test_trigger_fires_once_when_condition_true(game):
    """A one-shot trigger runs its action exactly once."""
    calls = []
    t = Trigger(condition=lambda g: True, action=lambda g: calls.append(1))
    for _ in range(3):
        t.maybe_fire(game)
    assert calls == [1]


def test_trigger_does_not_fire_while_condition_false(game):
    """No action runs while the condition stays false."""
    calls = []
    t = Trigger(condition=lambda g: False, action=lambda g: calls.append(1))
    t.maybe_fire(game)
    assert calls == []


def test_trigger_repeats_when_not_once(game):
    """A trigger with once=False fires every frame its condition holds."""
    calls = []
    t = Trigger(condition=lambda g: True, action=lambda g: calls.append(1), once=False)
    for _ in range(3):
        t.maybe_fire(game)
    assert calls == [1, 1, 1]


# ---------------------------------------------------------------------------
# Group membership and resolution
# ---------------------------------------------------------------------------


def test_resolve_identity_group_filters_dead(game):
    """Resolving an identity group returns only its still-live members."""
    a = MockBot("a", [0, 0, 0], team=2)
    b = MockBot("b", [0, 0, 0], team=2)
    game.interactions.add(a.pawn)
    game.interactions.add(b.pawn)
    game.scenario.register("wave", [a, b])

    assert set(game.scenario.resolve(game, "wave")) == {a.pawn, b.pawn}

    game.interactions.kill(a.pawn)
    assert game.scenario.resolve(game, "wave") == [b.pawn]


def test_resolve_unknown_group_is_empty(game):
    """An unknown group name resolves to an empty list (and warns)."""
    assert game.scenario.resolve(game, "nope") == []


def test_resolve_query_group_is_live(game):
    """A query group is evaluated live against current actors."""
    a = MockBot("a", [0, 0, 0], team=2)
    b = MockBot("b", [0, 0, 0], team=1)
    game.interactions.add(a.pawn)
    game.interactions.add(b.pawn)
    game.scenario.register_query("enemies", lambda actor: actor.team == 2)

    assert game.scenario.resolve(game, "enemies") == [a.pawn]


def test_all_destroyed_false_before_spawn(game):
    """A group that never spawned is not 'destroyed'."""
    assert game.scenario.all_destroyed(game, "wave") is False


def test_all_destroyed_lifecycle(game):
    """Destroyed only once a spawned group has lost all members."""
    a = MockBot("a", [0, 0, 0], team=2)
    game.interactions.add(a.pawn)
    game.scenario.register("wave", [a])

    assert game.scenario.all_destroyed(game, "wave") is False
    game.interactions.kill(a.pawn)
    assert game.scenario.all_destroyed(game, "wave") is True


def test_all_destroyed_false_while_wave_mid_spawn(game, patch_spawn_bot):
    """
    A wave whose spawn has been scheduled but whose ships have not yet appeared
    must NOT read as destroyed. Otherwise a chained all_destroyed condition
    would fire the instant the wave is scheduled, before any ship exists.
    """
    spawn_wave(WAVE_CFG)(game)  # scheduled, but the job has not run yet
    assert "wave_a" in game.scenario.scheduled
    assert "wave_a" not in game.scenario.spawned
    assert game.scenario.all_destroyed(game, "wave_a") is False

    game.scenario.update(game)  # first ship spawns
    assert game.scenario.all_destroyed(game, "wave_a") is False


# ---------------------------------------------------------------------------
# Conditions and combinators
# ---------------------------------------------------------------------------


def test_after_seconds(game):
    cond = after_seconds(50)
    game.game_time.t = 49
    assert cond(game) is False
    game.game_time.t = 51
    assert cond(game) is True


def test_reached_waypoint(game):
    bot = MockBot("a", [0, 0, 0], team=2)
    game.interactions.add(bot.pawn)
    game.scenario.register("convoy", [bot])
    cond = reached_waypoint("convoy", index=5)

    assert cond(game) is False
    bot.navigator.next_waypoint_idx = 5
    assert cond(game) is True


def test_reached_waypoint_missing_group_is_false(game):
    """Resolves to no actor -> condition is false, not an error."""
    assert reached_waypoint("ghost", index=1)(game) is False


def test_delay_latches_and_elapses(game):
    """Delay arms when inner first holds, then fires after the interval."""
    inner = {"v": False}
    cond = Delay(lambda g: inner["v"], seconds=3)

    game.game_time.t = 0
    assert cond(game) is False  # inner still false -> not armed
    inner["v"] = True
    game.game_time.t = 10
    assert cond(game) is False  # armed at t=10, not yet elapsed
    inner["v"] = False  # inner flicker must not disarm
    game.game_time.t = 12
    assert cond(game) is False
    game.game_time.t = 13
    assert cond(game) is True  # 3s after arming


def test_has_fired_tracks_named_trigger(game):
    """has_fired reports whether a named trigger has run."""
    armed = {"v": False}
    trigger = Trigger(
        condition=lambda g: armed["v"], action=lambda g: None, name="alpha"
    )
    game.scenario = Scenario([trigger])

    assert game.scenario.has_fired("alpha") is False
    armed["v"] = True
    game.scenario.update(game)
    assert game.scenario.has_fired("alpha") is True


def test_has_fired_unknown_trigger_is_false(game):
    assert game.scenario.has_fired("ghost") is False


def test_fired_condition(game):
    """The fired condition becomes true once its trigger has run."""
    trigger = Trigger(condition=lambda g: True, action=lambda g: None, name="alpha")
    game.scenario = Scenario([trigger])
    cond = fired("alpha")

    assert cond(game) is False
    game.scenario.update(game)  # alpha fires
    assert cond(game) is True


def test_fired_chains_with_delay(game):
    """A delay over a fired condition fires N seconds after the other trigger."""
    src = Trigger(condition=lambda g: True, action=lambda g: None, name="alpha")
    game.scenario = Scenario([src])
    cond = Delay(fired("alpha"), seconds=3)

    game.game_time.t = 0
    assert cond(game) is False  # alpha not fired yet
    game.scenario.update(game)  # alpha fires at t=0
    assert cond(game) is False  # armed, not elapsed
    game.game_time.t = 3
    assert cond(game) is True


def test_all_of_and_any_of(game):
    def yes(g):
        return True

    def no(g):
        return False

    assert AllOf(yes, yes)(game) is True
    assert AllOf(yes, no)(game) is False
    assert AnyOf(no, no)(game) is False
    assert AnyOf(no, yes)(game) is True


# ---------------------------------------------------------------------------
# Wave spawning action
# ---------------------------------------------------------------------------


WAVE_CFG = {
    "id": "wave_a",
    "size": 3,
    "ship_model": "tie-bomber",
    "spawn_point": [100, 200, 300],
    "formation": {"scale_m": 30, "shape": "arrowhead"},
    "waypoints": [[0, 0, 0], [0, 100, 0]],
    "target": "transports",
    "hud_text": "Incoming!",
}


def test_spawn_wave_is_deferred_and_one_per_frame(game, patch_spawn_bot):
    """The action only schedules; ships then appear one per scenario step."""
    spawn_wave(WAVE_CFG)(game)
    assert len(patch_spawn_bot) == 0  # nothing spawned on the trigger frame
    assert len(game.scenario.jobs) == 1

    for expected in range(1, WAVE_CFG["size"] + 1):
        game.scenario.update(game)
        assert len(patch_spawn_bot) == expected

    game.scenario.update(game)  # job is exhausted and dropped
    assert len(patch_spawn_bot) == WAVE_CFG["size"]
    assert game.scenario.jobs == []


def test_spawn_wave_uses_formation_positions(game, patch_spawn_bot):
    """Leader spawns on the spawn point; wingmen at their slot offsets."""
    from space_flight.ai.formation import Formation

    expected_offsets = Formation(scale_m=30, shape="arrowhead").relative_positions
    spawn_wave(WAVE_CFG)(game)
    while game.scenario.jobs:
        game.scenario.update(game)

    base = np.array(WAVE_CFG["spawn_point"], dtype=float)
    for i, bot in enumerate(patch_spawn_bot):
        np.testing.assert_allclose(bot.pawn.position, base + expected_offsets[i])


def test_spawn_wave_registers_group_waypoints_and_targets(game, patch_spawn_bot):
    """Spawned ships join the wave group, get waypoints, and inherit targets."""
    transport = MockBot("t", [0, 0, 0], team=1)
    game.interactions.add(transport.pawn)
    game.scenario.register("transports", [transport])

    spawn_wave(WAVE_CFG)(game)
    while game.scenario.jobs:
        game.scenario.update(game)

    assert len(game.scenario.resolve(game, "wave_a")) == WAVE_CFG["size"]
    for bot in patch_spawn_bot:
        assert bot.navigator.waypoints  # waypoints applied
        assert transport.pawn.id in bot.tactician.primary_target_ids
    assert game.hud.messages == [("Incoming!", 2.5)]


def test_spawn_wave_guard_blocks_second_spawn(game, patch_spawn_bot):
    """A second spawn of an already-spawned wave is skipped."""
    action = spawn_wave(WAVE_CFG)
    action(game)
    while game.scenario.jobs:
        game.scenario.update(game)
    first_count = len(patch_spawn_bot)

    action(game)  # guard should refuse
    assert game.scenario.jobs == []
    assert len(patch_spawn_bot) == first_count


def test_spawn_wave_allow_respawn(game, patch_spawn_bot):
    """allow_respawn lets the same wave spawn again."""
    cfg = {**WAVE_CFG, "allow_respawn": True}
    action = spawn_wave(cfg)
    action(game)
    while game.scenario.jobs:
        game.scenario.update(game)
    action(game)
    assert len(game.scenario.jobs) == 1


def test_spawn_wave_without_formation_uses_line(game, patch_spawn_bot):
    """With no formation, ships spawn in a centred line along x."""
    cfg = {
        "id": "line_wave",
        "size": 3,
        "ship_model": "tie-fighter",
        "spawn_point": [0, 0, 0],
    }
    spawn_wave(cfg)(game)
    while game.scenario.jobs:
        game.scenario.update(game)

    xs = [bot.pawn.position[0] for bot in patch_spawn_bot]
    assert xs == [-50.0, 0.0, 50.0]


# ---------------------------------------------------------------------------
# Victory action
# ---------------------------------------------------------------------------


def test_speech_action_shows_subtitle_with_speaker(game):
    """Speech with a speaker prefixes the subtitle and honours display time."""
    speech(
        {"text": "All wings report in", "speaker": "Red Leader", "display_time_s": 5}
    )(game)
    assert game.hud.chatter == [("Red Leader: All wings report in", 5)]


def test_speech_action_bare_string(game):
    """A bare-string speech line shows the text with the default display time."""
    speech("Stay on target")(game)
    assert game.hud.chatter == [("Stay on target", 4.0)]


def _end_level_game():
    """A minimal game whose end_level records its call args."""
    calls = []

    class Game:
        def end_level(self, outcome, text=""):
            calls.append((outcome, text))

    return Game(), calls


def test_end_level_action_pushes_level_end_state():
    """end_level forwards the outcome and text to game.end_level."""
    game, calls = _end_level_game()
    end_level({"outcome": "victory", "text": "You won."})(game)
    assert calls == [("victory", "You won.")]


def test_end_level_action_bare_outcome_string():
    """A bare outcome string defaults the explanatory text to empty."""
    game, calls = _end_level_game()
    end_level("defeat")(game)
    assert calls == [("defeat", "")]


def test_player_waypoints_action_creates_route(monkeypatch):
    """The action builds a PlayerWaypoints and stores it on the game."""
    created = {}

    def fake_pw(game, points, **kwargs):
        created["points"] = points
        created["kwargs"] = kwargs
        return "ROUTE"

    monkeypatch.setattr("space_flight.game.scenario.actions.PlayerWaypoints", fake_pw)

    class Game:
        pass

    game = Game()
    player_waypoints({"points": [[0, 0, 0]], "arrival_radius_m": 200})(game)
    assert game.player_waypoints == "ROUTE"
    assert created["points"] == [[0, 0, 0]]
    assert created["kwargs"] == {"arrival_radius_m": 200}


def test_player_waypoints_advances_and_finishes(monkeypatch, game):
    """The route reveals each waypoint in turn and removes the marker at the end."""
    from space_flight.ui import player_waypoints as pw_module

    class FakeMarker:
        def __init__(self, game, **kwargs):
            self.moved = []
            self.visible = None
            self.cleaned = False

        def move_to(self, position):
            self.moved.append(np.asarray(position, dtype=float))

        def set_visible(self, visible):
            self.visible = visible

        def clean(self):
            self.cleaned = True

    monkeypatch.setattr(pw_module, "WaypointMarker", FakeMarker)
    game.player = MockBot("player", [0, 0, 0], team=1)
    game.player.target_filter = "Waypoints"

    route = pw_module.PlayerWaypoints(
        game, [[0, 0, 0], [0, 1000, 0]], arrival_radius_m=100
    )
    marker = route.marker

    assert len(marker.moved) == 1  # first waypoint positioned on creation

    route.update()  # player is on waypoint 0 -> advance, reveal waypoint 1
    assert route.index == 1
    assert len(marker.moved) == 2
    assert marker.visible is True  # Waypoints filter is active

    game.player.pawn.position = np.array([0.0, 500.0, 0.0])
    route.update()  # too far -> no advance
    assert route.index == 1

    game.player.target_filter = "All"
    route.update()  # filter off -> marker hidden
    assert marker.visible is False

    game.player.pawn.position = np.array([0.0, 1000.0, 0.0])
    route.update()  # reached the last waypoint -> finish
    assert route._done is True
    assert marker.cleaned is True


def test_target_filter_selects_by_category():
    """
    The "Waypoints" filter masks to waypoint-category actors; "All" excludes
    them. Exercises Player.update_target_mask against the marker's category.
    """
    from types import SimpleNamespace

    from space_flight.actors.player import Player

    player_actor = SimpleNamespace()  # the player: no category
    ship = SimpleNamespace()  # a ship: no category
    waypoint = SimpleNamespace(category="waypoint")

    fake = SimpleNamespace(
        game=SimpleNamespace(
            interactions=SimpleNamespace(live_actors=[player_actor, ship, waypoint])
        ),
        target_filter="Waypoints",
    )
    Player.update_target_mask(fake, player_actor_index=0)
    assert list(fake.target_mask) == [0.0, 0.0, 1.0]  # only the waypoint

    fake.target_filter = "All"
    Player.update_target_mask(fake, player_actor_index=0)
    assert list(fake.target_mask) == [0.0, 1.0, 0.0]  # ship only (player + wp off)


def test_near_player_condition(game):
    """near(player, ...) is true only when the player is within radius."""
    game.player = MockBot("player", [0, 0, 0], team=1)
    cond = near("player", point=[0, 0, 0], radius=100)

    assert cond(game) is True
    game.player.pawn.position = np.array([200.0, 0.0, 0.0])
    assert cond(game) is False


def test_near_group_condition(game):
    """near(group, ...) is true when any live member is within radius."""
    a = MockBot("a", [1000, 0, 0], team=1)
    b = MockBot("b", [0, 0, 0], team=1)
    game.interactions.add(a.pawn)
    game.interactions.add(b.pawn)
    game.scenario.register("racers", [a, b])
    cond = near("racers", point=[0, 0, 0], radius=100)

    assert cond(game) is True  # b is at the point
    game.interactions.kill(b.pawn)
    assert cond(game) is False  # only the far one (a) remains


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _write_yaml(tmp_path, text):
    path = tmp_path / "scenario.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_builds_triggers_and_combinators(tmp_path):
    """The loader parses leaf conditions and nested combinators."""
    path = _write_yaml(
        tmp_path,
        """
        waves:
          w1: { size: 1, ship_model: x, spawn_point: [0, 0, 0] }
        triggers:
          - name: timed
            when: { after_seconds: 10 }
            then: { spawn: w1 }
          - name: chained
            when:
              any_of:
                - { after_seconds: 200 }
                - delay:
                    after: { all_destroyed: w1 }
                    seconds: 3
            then:
              all:
                - { hud_text: "hi" }
                - { spawn: w1 }
        """,
    )
    scenario = load_scenario(path)
    assert len(scenario.triggers) == 2
    assert scenario.triggers[0].name == "timed"
    assert isinstance(scenario.triggers[1].condition, AnyOf)


def test_loader_builds_end_level_and_near(tmp_path):
    """The loader builds the end_level action and the near condition."""
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - name: finish
            when: { near: { who: player, point: [0, 0, 0], radius: 100 } }
            then:
              all:
                - { hud_text: "done" }
                - { end_level: { outcome: victory, text: "gg" } }
        """,
    )
    scenario = load_scenario(path)
    assert len(scenario.triggers) == 1


def test_loader_builds_player_waypoints(tmp_path):
    """The loader builds the player_waypoints action from a points list."""
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - when: { after_seconds: 1 }
            then:
              player_waypoints:
                points:
                  - [0, 0, 0]
                  - [0, 100, 0]
        """,
    )
    scenario = load_scenario(path)
    assert len(scenario.triggers) == 1


def test_loader_builds_fired_condition_in_delay(tmp_path):
    """delay.after takes an explicit {fired: <name>} condition node."""
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - name: a
            when: { after_seconds: 1 }
            then: { end_level: victory }
          - name: b
            when:
              delay:
                after: { fired: a }
                seconds: 2
            then: { end_level: defeat }
        """,
    )
    scenario = load_scenario(path)
    assert isinstance(scenario.triggers[1].condition, Delay)


def test_loader_rejects_bare_string_condition(tmp_path):
    """A bare string is no longer a valid condition node."""
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - when: blockade_past
            then: { end_level: victory }
        """,
    )
    with pytest.raises(ValueError):
        load_scenario(path)


def test_loader_rejects_unknown_condition(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - when: { no_such_condition: 1 }
            then: { hud_text: "x" }
        """,
    )
    with pytest.raises(ValueError, match="Unknown condition"):
        load_scenario(path)


def test_loader_rejects_unknown_wave(tmp_path):
    path = _write_yaml(
        tmp_path,
        """
        triggers:
          - when: { after_seconds: 1 }
            then: { spawn: ghost_wave }
        """,
    )
    with pytest.raises(ValueError, match="unknown wave"):
        load_scenario(path)


def test_loader_handles_empty_file(tmp_path):
    path = _write_yaml(tmp_path, "")
    scenario = load_scenario(path)
    assert scenario.triggers == []
