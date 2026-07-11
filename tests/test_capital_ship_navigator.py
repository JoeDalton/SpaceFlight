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
    nav.game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    return nav


def make_target(
    position: np.ndarray = None,
    right: np.ndarray = None,
    forward: np.ndarray = None,
    half_extents: np.ndarray = None,
):
    """
    Build a minimal, level orbit target with an oriented bounding box.

    :param position: world position (unused by orbit_target, which is passed it)
    :param right: body +X axis in world
    :param forward: body +Y axis in world
    :param half_extents: model-space bounding-box half-extents (X, Y, Z)
    :return: a MagicMock target with the attributes the orbit reads
    """
    target = MagicMock()
    target.position = np.zeros(3) if position is None else position
    target.right = np.array([1.0, 0.0, 0.0]) if right is None else right
    target.forward = np.array([0.0, 1.0, 0.0]) if forward is None else forward
    target.bounding_box_half_extents = (
        np.array([10.0, 10.0, 10.0]) if half_extents is None else half_extents
    )
    return target


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
# engage_target / orbit
# ---------------------------------------------------------------------------


def test_engage_target_empty_dict_returns_no_direction():
    """
    engage_target() with an empty target dict returns the NO_DIRECTION sentinel.
    """
    nav = make_capital_ship_navigator()

    result = nav.engage_target(target_dict={})

    no_dir_vector, no_dir_speed = NO_DIRECTION
    np.testing.assert_array_equal(result[0], no_dir_vector)
    assert result[1] == pytest.approx(no_dir_speed)


def test_engage_target_unknown_target_returns_no_direction():
    """
    engage_target() returns NO_DIRECTION when the target is no longer in the
    interactions (destroyed since the last intent update).
    """
    nav = make_capital_ship_navigator()
    # The self lookup succeeds; the target lookup raises (target gone).
    nav.game.interactions.get_actor_index_from_id.side_effect = [0, ValueError()]

    result = nav.engage_target(target_dict={"target_id": uuid.uuid4()})

    no_dir_vector, no_dir_speed = NO_DIRECTION
    np.testing.assert_array_equal(result[0], no_dir_vector)
    assert result[1] == pytest.approx(no_dir_speed)


def test_nearest_point_on_obb_clamps_to_extents():
    """
    The nearest point on the horizontal OBB clamps the query point to the box
    half-extents along each footprint axis.
    """
    nav = make_capital_ship_navigator()
    # Long along +Y (forward), narrow along +X (right).
    target = make_target(half_extents=np.array([10.0, 100.0, 5.0]))

    # Far out along +X: clamped to the +X half-extent, on the box edge.
    nearest_x = nav._nearest_point_on_horizontal_obb(
        target=target, center=np.zeros(3), point=np.array([500.0, 0.0, 0.0])
    )
    np.testing.assert_allclose(nearest_x, np.array([10.0, 0.0, 0.0]), atol=1e-6)

    # Far out along +Y beyond the long half-extent: clamped to +Y half-extent.
    nearest_y = nav._nearest_point_on_horizontal_obb(
        target=target, center=np.zeros(3), point=np.array([0.0, 500.0, 0.0])
    )
    np.testing.assert_allclose(nearest_y, np.array([0.0, 100.0, 0.0]), atol=1e-6)


def test_orbit_target_returns_unit_direction_and_orbit_speed():
    """
    orbit_target() returns a unit direction and the configured orbit speed.
    """
    nav = make_capital_ship_navigator(pawn_position=np.array([410.0, 0.0, 0.0]))
    target = make_target()

    direction, speed = nav.orbit_target(target=target, target_position=np.zeros(3))

    assert np.linalg.norm(direction) == pytest.approx(1.0, abs=1e-6)
    assert speed == pytest.approx(
        Personality.CAPITAL_SHIP_DEFAULT["navigator"]["orbit"]["orbit_speed_mps"]
    )


def test_orbit_target_drives_tangentially_when_on_standoff():
    """
    Sitting at the standoff distance abeam of a compact target, the desired
    direction is mostly tangential (perpendicular to the line of sight), not
    radial toward or away from the target.
    """
    nav = make_capital_ship_navigator(pawn_position=np.array([410.0, 0.0, 0.0]))
    target = make_target()  # standoff = max(300, 400) = 400; box edge at x=10

    direction, _ = nav.orbit_target(target=target, target_position=np.zeros(3))

    # Outward normal is +X; tangential (about +Z) is +Y. The radial (X) component
    # must be small compared to the tangential (Y) component.
    assert abs(direction[0]) < abs(direction[1])
    assert direction[1] > 0.0  # default orbit sense s = +1


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
