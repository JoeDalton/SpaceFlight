"""
Lightweight fakes for testing missions without a running Panda3D engine.

Shared by test_mission.py, test_levels.py and test_all_features_example.py.
Real Bot/Pawn construction needs a live engine, so spawn_bot and
PlayerWaypoints are monkeypatched (see :func:`patch_engine`) and pawns are
plain objects carrying just the attributes missions touch.
"""

import uuid
from types import SimpleNamespace

import numpy as np


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
        self.actors_id_dict[actor.id] = len(self.actors)
        self.actors.append(actor)

    def kill(self, actor):
        slot = self.actors_id_dict.pop(actor.id)
        self.actors[slot] = None


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
        self.is_dead = False
        self.forward = np.array([0.0, 1.0, 0.0])
        self.right = np.array([1.0, 0.0, 0.0])


class MockBot:
    def __init__(self, name, position, team, pawn_model=None):
        self.name = name
        self.team = team
        self.pawn_model = pawn_model
        self.pawn = MockPawn(self, position, team)
        self.navigator = MockNavigator()
        self.tactician = SimpleNamespace(primary_target_ids=[])

    def set_team(self, team):
        """Mirrors Bot.set_team's cascade, for waves that reassign teams."""
        self.team = team
        self.pawn.team = team
        for sub_system in getattr(self.pawn, "sub_systems", []):
            sub_system.team = team
        shield = getattr(self.pawn, "shield", None)
        if shield is not None:
            shield.team = team
        for mounted_bot in getattr(self.pawn, "mounted_bots", []):
            mounted_bot.set_team(team)


class MockHud:
    def __init__(self):
        self.messages = []
        self.chatter = []

    def set_event_text(self, text, display_time_s):
        self.messages.append((text, display_time_s))

    def set_chatter_text(self, text, display_time_s):
        self.chatter.append((text, display_time_s))


class FakePlayerWaypoints:
    def __init__(self, game, waypoints, **kwargs):
        self.waypoints = waypoints
        self.kwargs = kwargs
        self.cleaned = False

    def clean(self):
        self.cleaned = True


class FakeGame:
    def __init__(self):
        self.game_time = FakeGameTime()
        self.interactions = FakeInteractions()
        self.hud = MockHud()
        self.headless = False
        self.end_level_calls = []
        self.player = MockBot("player", [0, 0, 0], team=1)
        self.player_waypoints = None
        self.app = SimpleNamespace(
            bindings={
                "input_type": "keyboard",
                "contexts": {
                    "flight": {"keyboard": {"radial_menu": "r", "loop_target": ","}}
                },
            }
        )

    def end_level(self, outcome, text=""):
        self.end_level_calls.append((outcome, text))


def patch_engine(monkeypatch):
    """
    Replace spawn_bot and PlayerWaypoints with fakes.

    :return: The live list of every bot spawned, in spawn order
    """
    spawned = []

    def fake_spawn_bot(game, **kwargs):
        bot = MockBot(
            name=kwargs["name"],
            position=kwargs["ini_position"],
            team=kwargs["team"],
            pawn_model=kwargs["pawn_model"],
        )
        game.interactions.add(bot.pawn)
        spawned.append(bot)
        return bot

    monkeypatch.setattr("space_flight.game.scenario.wave.spawn_bot", fake_spawn_bot)
    monkeypatch.setattr(
        "space_flight.game.scenario.mission.PlayerWaypoints", FakePlayerWaypoints
    )
    return spawned


def advance(game, mission, seconds, dt=1 / 60):
    """Advance the clock and the mission, frame by frame, for seconds."""
    for _ in range(int(seconds / dt) + 1):
        game.game_time.t += dt
        mission.update()


def live(game, spawned, name):
    """The live spawned pawns of the wave called name."""
    return [
        bot.pawn
        for bot in spawned
        if bot.name.startswith(f"{name}_")
        and bot.pawn.id in game.interactions.actors_id_dict
    ]


def kill_all(game, pawns):
    for pawn in list(pawns):
        game.interactions.kill(pawn)
