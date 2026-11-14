"""
Tests for escorting the player through a local warp (issue #184): the Bot's
escort states (align, jump to warp and park, drop back in).
"""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import BitMask32, CollisionNode, CollisionSphere, NodePath

from space_flight.actors.bot import Bot
from space_flight.actors.hyperspace import TRANSIT_DISTANCE_M, TRANSIT_DURATION_S
from space_flight.ai.think_scheduler import ThinkScheduler
from space_flight.game.collisions import CollisionLayers
from space_flight.utils.state_machine import DyingPhase


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_pawn():
    """A ship stand-in: a real node carrying a hull collider, a recorded
    hold_step and move."""
    node = NodePath("root").attachNewNode("ship_node")
    collider = CollisionNode("hull")
    collider.addSolid(CollisionSphere(0, 0, 0, 1))
    collider.setFromCollideMask(CollisionLayers.DESTRUCTIBLE_FROM)
    collider.setIntoCollideMask(CollisionLayers.DESTRUCTIBLE_INTO)
    hull = node.attachNewNode(collider)
    pawn = SimpleNamespace(
        id="wingman",
        node=node,
        hull=hull,
        position=np.array([10.0, 20.0, 30.0]),
        orientation=np.array([1.0, 0.0, 0.0, 0.0]),
        speed=np.array([0.0, 100.0, 0.0]),
        in_hyperspace=False,
        held=[],
        move=MagicMock(),
    )

    def hold_step(position, orientation, speed, offset_m):
        pawn.position = np.array(position)
        pawn.orientation = np.array(orientation)
        pawn.speed = np.array(speed)
        pawn.held.append(offset_m)

    pawn.hold_step = hold_step
    return pawn


def make_bot(bot_type="fighter"):
    bot = object.__new__(Bot)
    bot.name = "wingman"
    bot.bot_type = bot_type
    bot.pawn = make_pawn()
    bot.pilot = MagicMock()
    bot.pilot.pilot.return_value = (0.6, 0.1, 0.2, 0.0)
    bot.navigator = MagicMock()
    bot.tactician = MagicMock()
    bot.tactician.think.return_value = ("patrol", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.game = MagicMock()
    bot.clock = Clock()
    bot.game.game_time.get_current_time.side_effect = bot.clock
    bot.game.game_time.get_time_step.return_value = 1.0 / 60.0
    bot.game.departed_ids = set()
    bot.game.destructibles.alive_objects = []
    bot.record = False
    bot._dying = DyingPhase(clock=lambda: 0.0)
    bot._think_slot = ThinkScheduler().register(period_s=0.1)
    bot._next_think_s = -math.inf
    bot._commands = None
    bot.hyperspace_transit = None
    bot._jump_at_s = None
    bot.has_departed = False
    bot._warp_leader = None
    bot._warp_departure = None
    bot.parked_in_hyperspace = False
    return bot


def make_leader():
    return SimpleNamespace(
        forward=np.array([0.0, 0.0, 1.0]), speed=np.array([0.0, 0.0, 250.0])
    )


def run(bot, seconds):
    """Step move_bot_task at 60 fps for seconds of game time."""
    for _ in range(round(seconds * 60)):
        bot.move_bot_task()
        bot.clock.t += 1.0 / 60.0


def hull_masks(bot):
    node = bot.pawn.hull.node()
    return node.getFromCollideMask(), node.getIntoCollideMask()


def park(bot):
    bot.jump_to_warp()
    run(bot, TRANSIT_DURATION_S[bot.bot_type] + 0.1)


# ---------------------------------------------------------------------------
# Alignment while the leader charges
# ---------------------------------------------------------------------------


def test_aligning_flies_along_the_leader_heading_weapons_cold():
    bot = make_bot()
    leader = make_leader()

    bot.begin_warp_alignment(leader)
    run(bot, 0.5)

    bot.tactician.think.assert_not_called()
    bot.navigator.navigate.assert_not_called()
    bot.navigator.update_triggers.assert_not_called()
    kwargs = bot.pilot.pilot.call_args.kwargs
    np.testing.assert_allclose(kwargs["target_direction"], leader.forward)
    assert kwargs["desired_speed_mps"] == pytest.approx(250.0)
    assert bot.pawn.move.call_count == 30
    bot.pawn.move.assert_called_with(
        throttle=0.6, yaw_rate=0.1, pitch_rate=0.2, roll_rate=0.0
    )


def test_a_called_off_jump_sends_the_ship_back_to_the_fight_at_once():
    bot = make_bot()
    bot.begin_warp_alignment(make_leader())
    run(bot, 0.2)

    bot.cancel_warp_alignment()
    assert bot._next_think_s == -math.inf
    run(bot, 1 / 60)

    bot.tactician.think.assert_called_once()
    bot.navigator.navigate.assert_called_once()


def test_a_ship_still_dropping_in_lands_to_align():
    bot = make_bot()
    bot.hyperspace_transit = arrival = MagicMock(arriving=True)

    bot.begin_warp_alignment(make_leader())

    arrival.end.assert_called_once()
    assert bot.hyperspace_transit is None
    assert bot._warp_leader is not None


@pytest.mark.parametrize("case", ["dying", "departed", "jumping_out", "turret"])
def test_a_ship_that_cannot_escort_ignores_the_leader(case):
    bot = make_bot("turret" if case == "turret" else "fighter")
    if case == "dying":
        bot._dying.begin()
    elif case == "departed":
        bot.has_departed = True
    elif case == "jumping_out":
        bot._jump_at_s = 2.0

    bot.begin_warp_alignment(make_leader())
    bot.jump_to_warp()

    assert bot._warp_leader is None
    assert bot._warp_departure is None


# ---------------------------------------------------------------------------
# Jumping to warp and waiting parked
# ---------------------------------------------------------------------------


def test_jumping_to_warp_streaks_out_then_parks_without_departing():
    bot = make_bot()
    bot.begin_warp_alignment(make_leader())

    bot.jump_to_warp()

    assert bot._warp_leader is None
    assert bot.pawn.in_hyperspace
    assert hull_masks(bot) == (BitMask32.allOff(), BitMask32.allOff())
    bot.navigator.collision_sensor.set_active.assert_called_with(False)
    bot.game.player.remove_target.assert_called_with(target_to_remove=bot.pawn)

    run(bot, TRANSIT_DURATION_S["fighter"] + 0.1)

    assert bot.parked_in_hyperspace
    assert bot.pawn.node.isHidden()
    assert bot.pawn.in_hyperspace
    # Alive: still in the level, its wave and its formation
    assert not bot.has_departed
    assert bot.pawn.id not in bot.game.departed_ids
    bot.game.destructibles.depart.assert_not_called()
    bot.game.interactions.remove_actor.assert_not_called()
    bot.tactician.think.assert_not_called()


def test_a_parked_ship_is_held_still_and_hidden():
    bot = make_bot()
    park(bot)
    held = len(bot.pawn.held)
    position = bot.pawn.position.copy()

    run(bot, 2.0)

    assert len(bot.pawn.held) == held + 120
    np.testing.assert_allclose(bot.pawn.position, position)
    assert bot.pawn.held[-1] == pytest.approx(TRANSIT_DISTANCE_M["fighter"])
    assert bot.pawn.node.isHidden()


def test_a_parked_ship_ordered_out_departs_at_once():
    bot = make_bot()
    park(bot)

    bot.jump_out()

    assert bot.has_departed
    assert bot._warp_departure is None
    assert not bot.parked_in_hyperspace
    assert bot.pawn.id in bot.game.departed_ids


def test_jumping_out_while_aligning_drops_the_alignment():
    bot = make_bot()
    bot.begin_warp_alignment(make_leader())

    bot.jump_out(spool_s=1.0)

    assert bot._warp_leader is None
    assert bot._jump_at_s == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Dropping back in
# ---------------------------------------------------------------------------

NEW_POSITION = np.array([5e6, -3e6, 2e5])
NEW_ORIENTATION = np.array([0.0, 0.0, 0.0, 1.0])
NEW_VELOCITY = np.array([0.0, 0.0, 300.0])


@pytest.mark.parametrize("streaking", [False, True])
def test_arriving_from_warp_lands_on_the_new_pose_then_fights(streaking):
    bot = make_bot()
    if streaking:
        # A very short jump: dropped in before the streak out is over
        bot.jump_to_warp()
        run(bot, 0.1)
        assert not bot.parked_in_hyperspace
    else:
        park(bot)

    bot.arrive_from_warp(NEW_POSITION, NEW_ORIENTATION, NEW_VELOCITY, delay_s=0.3)

    assert bot._warp_departure is None
    assert not bot.parked_in_hyperspace
    arrival = bot.hyperspace_transit
    assert arrival is not None and arrival.arriving
    np.testing.assert_allclose(arrival.position, NEW_POSITION)
    np.testing.assert_allclose(arrival.orientation, NEW_ORIENTATION)
    np.testing.assert_allclose(arrival.velocity, NEW_VELOCITY)
    # Waits out its delay hidden, untouchable
    assert bot.pawn.node.isHidden()
    assert bot.pawn.in_hyperspace

    run(bot, 0.3 + TRANSIT_DURATION_S["fighter"] + 0.1)

    assert bot.hyperspace_transit is None
    assert not bot.pawn.in_hyperspace
    assert not bot.pawn.node.isHidden()
    assert hull_masks(bot) == (
        CollisionLayers.DESTRUCTIBLE_FROM,
        CollisionLayers.DESTRUCTIBLE_INTO,
    )
    bot.tactician.think.assert_called()
    assert not bot.has_departed


def test_an_undelayed_arrival_is_never_drawn_on_its_pose():
    bot = make_bot()
    park(bot)

    bot.arrive_from_warp(NEW_POSITION, NEW_ORIENTATION, NEW_VELOCITY)

    # Drawn far behind from the start
    assert bot.pawn.held[-1] == pytest.approx(-TRANSIT_DISTANCE_M["fighter"])


def test_arriving_without_having_jumped_is_a_no_op():
    bot = make_bot()

    bot.arrive_from_warp(NEW_POSITION, NEW_ORIENTATION, NEW_VELOCITY)

    assert bot.hyperspace_transit is None
    assert bot.pawn.held == []
