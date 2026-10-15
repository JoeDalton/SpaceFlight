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

from space_flight.actors.major_ship.hangar import LaunchOrder
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M
from space_flight.ai.formation import Formation
from space_flight.game.kills import KillLog
from space_flight.ui.hud import CHATTER_DISPLAY_S, EVENT_DISPLAY_S, HINT_DISPLAY_S


class FakeGameTime:
    def __init__(self):
        self.t = 0.0

    def get_current_time(self):
        return self.t


class _LivePairs:
    """
    Read-only stand-in for an Interactions matrix: ``matrix[i, j]`` is
    computed from the actors' current positions on each access, so tests can
    move pawns without an update step.
    """

    def __init__(self, interactions, pair_value):
        self.interactions = interactions
        self.pair_value = pair_value

    def __getitem__(self, pair):
        source_idx, target_idx = pair
        actors = self.interactions.actors
        return self.pair_value(actors[source_idx], actors[target_idx])


def _distance(source, target):
    distance = float(np.linalg.norm(target.position - source.position))
    return distance if distance > TARGET_DISTANCE_TOLERANCE_M else 0.0


def _alignment(source, target):
    distance = _distance(source, target)
    if distance == 0.0:
        return 0.0
    return float(np.dot((target.position - source.position) / distance, source.forward))


class FakeInteractions:
    def __init__(self):
        self.actors = []
        self.actors_id_dict = {}
        self.distances = _LivePairs(self, _distance)
        self.alignments = _LivePairs(self, _alignment)

    def add(self, actor):
        self.actors_id_dict[actor.id] = len(self.actors)
        self.actors.append(actor)

    def kill(self, actor):
        slot = self.actors_id_dict.pop(actor.id)
        self.actors[slot] = None

    def get_actor_index_from_id(self, actor_id):
        try:
            return self.actors_id_dict[actor_id]
        except KeyError:
            raise ValueError(f"Actor {actor_id} is not in the actors' list")


class MockNavigator:
    def __init__(self):
        self.next_waypoint_idx = 0
        self.waypoints = []
        self.is_loop = False

    def set_waypoints(self, waypoints, is_loop=False):
        """Mirrors the real navigators: a new route starts at its first point."""
        self.waypoints = waypoints
        self.is_loop = is_loop
        self.next_waypoint_idx = 0

    def clear_waypoints(self):
        self.waypoints = []
        self.next_waypoint_idx = 0


class MockPawn:
    def __init__(self, parent, position, team):
        self.id = uuid.uuid4()
        self.parent = parent
        self.position = np.array(position, dtype=float)
        self.team = team
        self.is_dead = False
        self.forward = np.array([0.0, 1.0, 0.0])
        self.right = np.array([1.0, 0.0, 0.0])
        self.orientation = np.array([1.0, 0.0, 0.0, 0.0])
        self.target = None
        self.health = 100.0
        self.shield_level = 0.0
        self.category = "fighter"


class MockBot:
    def __init__(self, name, position, team, pawn_model=None, orientation=None):
        self.name = name
        self.team = team
        self.pawn_model = pawn_model
        self.ini_orientation = orientation
        self.pawn = MockPawn(self, position, team)
        self.navigator = MockNavigator()
        self.tactician = SimpleNamespace(primary_target_ids=[])
        #: The delay of each hyperspace arrival begun, in order
        self.hyperspace_arrivals = []
        #: The spool time of each jump out ordered, in order
        self.jump_outs = []

    def begin_hyperspace_arrival(self, delay_s=0.0):
        self.hyperspace_arrivals.append(delay_s)

    def jump_out(self, spool_s=None):
        """Records the order: a test makes the ship leave with depart_all."""
        self.jump_outs.append(spool_s)

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


class FakeHangar:
    """
    Stand-in for a Hangar, with its request rules (stock per type, a type not
    in the stock raises, an empty type launches nothing), but launching only
    when a test calls :meth:`launch_next` / :meth:`launch_pending`.
    """

    def __init__(self, game, team, name="hangar_0", group_size=3):
        self.game = game
        self.team = team
        self.name = name
        self.group_size = group_size
        self.stock = {}
        self.is_operational = True
        self.orders = []
        #: Every bot it launched, in launch order
        self.launched = []

    def set_stock(self, stock):
        self.stock = dict(stock)

    def launch(
        self,
        fighter_type,
        count=None,
        on_launched=None,
        primary_target_ids=(),
        formation="arrowhead",
        formation_scale_m=Formation.FIGHTER_SCALE_M,
        loadout=None,
    ):
        if fighter_type not in self.stock:
            raise KeyError(fighter_type)
        order = LaunchOrder(
            fighter_type=fighter_type,
            count=self.group_size if count is None else count,
            on_launched=on_launched,
            primary_target_ids=list(primary_target_ids),
            formation_shape=formation,
            formation_scale_m=formation_scale_m,
            loadout=loadout,
        )
        if self.stock[fighter_type] <= 0 or not self.is_operational:
            order.cancelled = True
        else:
            self.orders.append(order)
        return order

    def launch_next(self):
        """Launch the next queued fighter, as the real hangar does every
        launch interval (cancelling a request whose type ran out)."""
        self.orders = [order for order in self.orders if not order.done]
        if not self.orders:
            return
        order = self.orders[0]
        if self.stock[order.fighter_type] <= 0:
            order.cancelled = True
            return
        bot = MockBot(
            f"launched_{len(self.launched)}",
            [0, 0, 0],
            self.team,
            pawn_model=order.fighter_type,
        )
        self.game.interactions.add(bot.pawn)
        self.stock[order.fighter_type] -= 1
        order.ids.append(bot.pawn.id)
        if order.formation_shape is not None:
            if order.formation is None:
                order.formation = Formation(
                    scale_m=order.formation_scale_m, shape=order.formation_shape
                )
            order.formation.add_ship(ship=bot.pawn)
        self.launched.append(bot)
        if order.on_launched is not None:
            order.on_launched(bot)

    def launch_pending(self):
        """Launch every queued fighter now, as far as the stock lasts."""
        while self.orders:
            self.launch_next()


class MockHud:
    def __init__(self):
        self.messages = []
        self.chatter = []
        self.hints = []

    def set_hint_text(self, text, display_time_s=HINT_DISPLAY_S):
        self.hints.append((text, display_time_s))

    def set_event_text(self, text, display_time_s=EVENT_DISPLAY_S):
        self.messages.append((text, display_time_s))

    def set_chatter_text(self, text, display_time_s=CHATTER_DISPLAY_S):
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
        self.departed_ids = set()
        self.hud = MockHud()
        self.headless = False
        self.end_level_calls = []
        self.kill_log = KillLog(self)
        self.player = MockBot("player", [0, 0, 0], team=1)
        self.interactions.add(self.player.pawn)
        self.player_waypoints = None
        self.app = SimpleNamespace(
            bindings={
                "contexts": {
                    "flight": {"keyboard": {"radial_menu": "r", "loop_target": ","}}
                },
            }
        )

    def end_level(self, outcome, text=""):
        self.end_level_calls.append((outcome, text))
        # What the level-end tally sees: each objective's state, by its text
        mission = getattr(self, "mission", None)
        if mission is not None:
            self.objectives_at_end = {o.text: o.state for o in mission.objectives}


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
            orientation=kwargs.get("ini_orientation"),
        )
        bot.spawn_kwargs = kwargs
        if kwargs.get("bot_type") == "major_ship":
            # A major ship with one hangar bay
            bot.pawn.hangars = [FakeHangar(game, team=kwargs["team"])]
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


def kill_all(game, pawns, by=None):
    """
    Kill pawns, logging each death in the kill log.

    :param by: The killer's DamageSource (None for no one)
    """
    for pawn in list(pawns):
        pawn.last_hit_by = by
        pawn.last_hit_cause = None if by is None else "weapon"
        game.interactions.kill(pawn)
        game.kill_log.record(pawn)


def depart_all(game, pawns):
    """The pawns leave the level alive, as at the end of a jump out (no kill)."""
    for pawn in list(pawns):
        game.interactions.kill(pawn)
        game.departed_ids.add(pawn.id)
