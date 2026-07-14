"""
Unit tests for GenericShipNavigator (space_flight.ai.generic.generic_ship_navigator).

GenericShipNavigator.__init__ instantiates a CollisionSensor which requires
Panda3D collision nodes.  All tests bypass __init__ via object.__new__() and
populate the instance with the minimal attributes consumed by each method.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)
from space_flight.utils.state_machine import StateMachine


def make_ship_navigator(
    pawn_position: np.ndarray = None,
    max_speed_mps: float = 500.0,
    personality: dict = None,
) -> GenericShipNavigator:
    """
    Build a GenericShipNavigator that bypasses __init__.

    :param pawn_position: world-space position of the owning ship
    :param max_speed_mps: maximum speed of the owning ship in m/s
    :param personality: personality dict; defaults to FIGHTER_DEFAULT
    :return: a GenericShipNavigator whose methods can be tested in isolation
    """
    if personality is None:
        personality = Personality.FIGHTER_DEFAULT
    nav = object.__new__(GenericShipNavigator)
    nav.game = MagicMock()
    nav.game.game_time.get_current_time.return_value = 0.0
    nav.pawn = MagicMock()
    nav.pawn.position = np.zeros(3) if pawn_position is None else pawn_position.copy()
    nav.pawn.max_speed_mps = max_speed_mps
    nav.pawn.parent = MagicMock()
    nav.personality = personality
    nav.debug = False
    nav.behaviour_sm = StateMachine("idle", clock=nav.game.game_time.get_current_time)
    nav.waypoints = []
    nav.next_waypoint_idx = 0
    nav.distance_to_waypoint_m = 0.0
    nav.has_waypoint_loop = False
    nav.time_in_spiral_s = 0.0
    nav.collision_sensor = MagicMock()
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)
    return nav


# ---------------------------------------------------------------------------
# regroup
# ---------------------------------------------------------------------------


def test_regroup_returns_direction_toward_target():
    """
    regroup() must return a unit direction pointing from self toward the
    target's position.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 300.0, 0.0])

    direction, _ = nav.regroup(target_dict={"position": target_position})

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_regroup_speed_matches_personality():
    """
    regroup() must return the regroup speed from the personality dict.
    """
    nav = make_ship_navigator()
    target_position = np.array([0.0, 300.0, 0.0])

    _, speed = nav.regroup(target_dict={"position": target_position})

    expected_speed = Personality.FIGHTER_DEFAULT["navigator"]["regroup"]["speed_mps"]
    assert speed == pytest.approx(expected_speed)


def test_regroup_at_zero_distance_returns_no_direction():
    """
    When the target coincides with self, regroup() must return NO_DIRECTION
    (zero vector, constant speed) to avoid dividing by zero.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))

    result = nav.regroup(target_dict={"position": np.zeros(3)})

    no_dir_vector, no_dir_speed = NO_DIRECTION
    result_vector, result_speed = result
    np.testing.assert_array_equal(result_vector, no_dir_vector)
    assert result_speed == pytest.approx(no_dir_speed)


# ---------------------------------------------------------------------------
# disengage
# ---------------------------------------------------------------------------


def test_disengage_returns_direction_away_from_target():
    """
    disengage() must return a unit direction pointing away from the target.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    target_position = np.array([0.0, 200.0, 0.0])

    direction, _ = nav.disengage(target_dict={"position": target_position})

    np.testing.assert_allclose(direction, np.array([0.0, -1.0, 0.0]), atol=1e-6)


def test_disengage_at_zero_distance_returns_no_direction():
    """
    When the danger center coincides with self, disengage() must return
    NO_DIRECTION.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))

    result = nav.disengage(target_dict={"position": np.zeros(3)})

    no_dir_vector, _ = NO_DIRECTION
    result_vector, _ = result
    np.testing.assert_array_equal(result_vector, no_dir_vector)


# ---------------------------------------------------------------------------
# set_waypoints / follow_waypoints
# ---------------------------------------------------------------------------


def test_follow_waypoints_returns_direction_toward_next_waypoint():
    """
    follow_waypoints() must return a unit direction pointing to the current
    waypoint when it is far enough away.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    waypoint = np.array([0.0, 500.0, 0.0])
    nav.set_waypoints([waypoint], is_loop=False)

    direction, _ = nav.follow_waypoints()

    np.testing.assert_allclose(direction, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_follow_waypoints_advances_index_when_within_tolerance():
    """
    When the ship is already within the waypoint tolerance radius, the index
    must advance and NO_DIRECTION is returned for that frame.
    """
    tolerance_m = Personality.FIGHTER_DEFAULT["navigator"]["patrol"][
        "waypoint_meeting_tolerance_m"
    ]
    nearby_waypoint = np.array([0.0, tolerance_m * 0.5, 0.0])
    far_waypoint = np.array([0.0, 1000.0, 0.0])
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([nearby_waypoint, far_waypoint], is_loop=False)

    nav.follow_waypoints()

    assert nav.next_waypoint_idx == 1


def test_follow_waypoints_loops_when_has_waypoint_loop():
    """
    After all waypoints are visited in loop mode, the index wraps back to 0
    and the navigator points toward the first waypoint again.
    """
    tolerance_m = Personality.FIGHTER_DEFAULT["navigator"]["patrol"][
        "waypoint_meeting_tolerance_m"
    ]
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    # Place the waypoint far enough away so it is NOT reached within tolerance
    far_waypoint = np.array([0.0, tolerance_m * 10.0, 0.0])
    nav.set_waypoints([far_waypoint], is_loop=True)
    nav.next_waypoint_idx = 1  # Simulate all waypoints visited

    nav.follow_waypoints()

    # Loop wraps to 0, then processes waypoints[0] which is far → stays at 0
    assert nav.next_waypoint_idx == 0


def test_follow_waypoints_no_loop_clears_waypoints_when_done():
    """
    After all non-loop waypoints are visited the waypoints list is emptied.
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.set_waypoints([np.array([0.0, 1000.0, 0.0])], is_loop=False)
    nav.next_waypoint_idx = 1  # All visited

    nav.follow_waypoints()

    assert nav.waypoints == []


# ---------------------------------------------------------------------------
# compute_follow_speed
# ---------------------------------------------------------------------------


def test_compute_follow_speed_clamped_above_zero():
    """
    compute_follow_speed must never return a negative speed even when the
    target's speed and distance contribution would pull it below zero.
    """
    nav = make_ship_navigator(max_speed_mps=100.0)

    speed = nav.compute_follow_speed(
        distance_m=0.0,
        target_speed_mps=0.0,
        longitudinal_speed_scalar_mps=0.0,
        intent="formation",
    )

    assert speed >= 0.0


def test_compute_follow_speed_clamped_below_max_speed():
    """
    compute_follow_speed must never exceed pawn.max_speed_mps.
    """
    max_speed = 300.0
    nav = make_ship_navigator(max_speed_mps=max_speed)

    speed = nav.compute_follow_speed(
        distance_m=10000.0,
        target_speed_mps=max_speed,
        longitudinal_speed_scalar_mps=0.0,
        intent="formation",
    )

    assert speed <= max_speed


# ---------------------------------------------------------------------------
# navigate — blending intent and avoidance
# ---------------------------------------------------------------------------


def test_navigate_with_zero_avoidance_equals_intent_output():
    """
    When the collision sensor returns zero avoidance weight the navigate()
    result must match the intent output directly (no blending penalty).
    """
    nav = make_ship_navigator(pawn_position=np.zeros(3))
    nav.collision_sensor.compute_repulsion.return_value = (np.zeros(3), 0.0)

    intent_direction = np.array([0.0, 1.0, 0.0])
    intent_speed = 200.0

    nav.navigate_intent = MagicMock(return_value=(intent_direction, intent_speed))

    result_direction, result_speed = nav.navigate(
        intent=Intent.REGROUP, target_dict={"position": np.array([0.0, 500.0, 0.0])}
    )

    np.testing.assert_allclose(result_direction, intent_direction, atol=1e-6)
    assert result_speed == pytest.approx(intent_speed)
