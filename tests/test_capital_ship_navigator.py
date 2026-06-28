"""
Unit tests for CapitalShipNavigator space_flight.ai.capital_ship.capital_ship_navigator

CapitalShipNavigator.__init__ creates a CollisionSensor which requires
Panda3D collision nodes.  All tests bypass __init__ via object.__new__() and
populate the instance with the minimal attributes consumed by each method.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.capital_ship.capital_ship_navigator import CapitalShipNavigator
from space_flight.ai.generic.generic_ship_navigator import NO_DIRECTION


def make_capital_ship_navigator(
    pawn_position: np.ndarray = None,
) -> CapitalShipNavigator:
    """
    Build a CapitalShipNavigator that bypasses __init__.

    :param pawn_position: world-space position of the owning ship
    :return: a CapitalShipNavigator whose methods can be tested in isolation
    """
    nav = object.__new__(CapitalShipNavigator)
    nav.game = MagicMock()
    nav.game.game_time.get_current_time.return_value = 0.0
    nav.pawn = MagicMock()
    nav.pawn.position = np.zeros(3) if pawn_position is None else pawn_position.copy()
    nav.pawn.max_speed_mps = 500.0
    nav.pawn.parent = MagicMock()
    nav.personality = Personality.CAPITAL_SHIP_DEFAULT
    nav.debug = False
    nav.behaviour = "idle"
    nav.behaviour_duration_s = 0.0
    nav.last_update_time = 0.0
    nav.waypoints = []
    nav.next_waypoint_idx = 0
    nav.distance_to_waypoint_m = 0.0
    nav.has_waypoint_loop = False
    nav.time_in_spiral_s = 0.0
    nav.collision_sensor = MagicMock()
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)
    nav.engage_phase = ""
    return nav


# ---------------------------------------------------------------------------
# navigate_intent — IDLE
# ---------------------------------------------------------------------------


def test_navigate_intent_idle_returns_no_direction():
    """
    navigate_intent() with IDLE intent must return the NO_DIRECTION sentinel
    (zero vector, constant speed).
    """
    nav = make_capital_ship_navigator()

    result = nav.navigate_intent(intent=Intent.IDLE, target_dict={})

    no_dir_vector, no_dir_speed = NO_DIRECTION
    result_vector, result_speed = result
    np.testing.assert_array_equal(result_vector, no_dir_vector)
    assert result_speed == pytest.approx(no_dir_speed)


# ---------------------------------------------------------------------------
# navigate_intent — ENGAGE (raises NotImplementedError)
# ---------------------------------------------------------------------------


def test_navigate_intent_engage_raises_not_implemented():
    """
    engage_target() is not yet implemented for capital ships; navigate_intent
    with ENGAGE intent must raise NotImplementedError.
    """
    nav = make_capital_ship_navigator()

    with pytest.raises(NotImplementedError):
        nav.navigate_intent(
            intent=Intent.ENGAGE, target_dict={"target_id": uuid.uuid4()}
        )


# ---------------------------------------------------------------------------
# navigate_intent — REGROUP
# ---------------------------------------------------------------------------


def test_navigate_intent_regroup_returns_direction_toward_target():
    """
    navigate_intent() with REGROUP intent must return a direction pointing
    toward the target position.
    """
    nav = make_capital_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 400.0, 0.0])

    direction, _ = nav.navigate_intent(
        intent=Intent.REGROUP, target_dict={"position": target_position}
    )

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)


# ---------------------------------------------------------------------------
# navigate_intent — DISENGAGE
# ---------------------------------------------------------------------------


def test_navigate_intent_disengage_returns_direction_away_from_target():
    """
    navigate_intent() with DISENGAGE intent must return a direction pointing
    away from the target position.
    """
    nav = make_capital_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 400.0, 0.0])

    direction, _ = nav.navigate_intent(
        intent=Intent.DISENGAGE, target_dict={"position": target_position}
    )

    np.testing.assert_allclose(direction, np.array([0.0, -1.0, 0.0]), atol=1e-6)


# ---------------------------------------------------------------------------
# navigate_intent — PATROL (follow_waypoints)
# ---------------------------------------------------------------------------


def test_navigate_intent_patrol_returns_direction_toward_waypoint():
    """
    navigate_intent() with PATROL intent delegates to follow_waypoints() and
    must return a direction toward the next waypoint.
    """
    nav = make_capital_ship_navigator(pawn_position=np.zeros(3))
    waypoint = np.array([0.0, 600.0, 0.0])
    nav.waypoints = [waypoint]
    nav.next_waypoint_idx = 0

    direction, _ = nav.navigate_intent(intent=Intent.PATROL, target_dict={})

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)
