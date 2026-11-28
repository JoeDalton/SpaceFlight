"""
Tests for the generic aim assist (space_flight.ai.aim_assist), shared by the laser
cannons' auto-aim and the bomb launchers.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from space_flight.ai.aim_assist import (
    AssistCone,
    aim_toward,
    exact_target_kinematics,
    target_kinematics,
)

AXIS = np.array([0.0, 1.0, 0.0])


def unit(*v):
    v = np.array(v, dtype=float)
    return v / np.linalg.norm(v)


def test_inside_the_cone_the_direction_is_kept():
    cone = AssistCone(20.0)
    direction = unit(0.1, 1.0, 0.0)

    assert cone.contains(direction, AXIS)
    np.testing.assert_allclose(cone.clamp(direction, AXIS), direction)


def test_outside_the_cone_it_is_clamped_onto_the_surface_keeping_its_lateral():
    cone = AssistCone(20.0)
    direction = unit(1.0, 0.2, 1.0)

    clamped = cone.clamp(direction, AXIS)

    assert not cone.contains(direction, AXIS)
    assert np.linalg.norm(clamped) == pytest.approx(1.0)
    assert np.degrees(np.arccos(clamped @ AXIS)) == pytest.approx(20.0)
    # Same lateral direction (x and z in the ratio they had)
    assert clamped[0] == pytest.approx(clamped[2])
    assert clamped[0] > 0


def test_straight_behind_the_axis_falls_back_on_the_axis():
    np.testing.assert_allclose(AssistCone(20.0).clamp(-AXIS, AXIS), AXIS)


def test_aim_toward_a_point_in_the_cone():
    direction, in_cone = aim_toward(
        AssistCone(30.0), AXIS, np.zeros(3), np.array([10.0, 100.0, 0.0])
    )

    assert in_cone
    np.testing.assert_allclose(direction, unit(10.0, 100.0, 0.0))


def test_aim_toward_a_point_outside_the_cone_is_clamped():
    direction, in_cone = aim_toward(
        AssistCone(10.0), AXIS, np.zeros(3), np.array([100.0, 10.0, 0.0])
    )

    assert not in_cone
    assert np.degrees(np.arccos(direction @ AXIS)) == pytest.approx(10.0)


def test_aim_toward_the_start_point_itself_follows_the_axis():
    direction, in_cone = aim_toward(AssistCone(10.0), AXIS, np.ones(3), np.ones(3))

    np.testing.assert_allclose(direction, AXIS)
    assert in_cone


# exact_target_kinematics: an exact alternative to target_kinematics, not used yet

SHOOTER = np.array([10.0, 20.0, 30.0])


def _kinematics(function, position, velocity, speed, target_id="target"):
    """Run a kinematics function on a target at this offset / relative velocity."""
    position = np.array(position, dtype=float)
    distance = np.linalg.norm(position)
    geometry = (distance, position / distance, np.array(velocity, dtype=float))
    with patch("space_flight.ai.aim_assist.pair_geometry", return_value=geometry):
        return function(MagicMock(), "shooter", SHOOTER, target_id, speed)


@pytest.mark.parametrize(
    "position, velocity, speed",
    [
        ([100.0, 0.0, -300.0], [20.0, 0.0, 0.0], 75.0),
        ([0.0, 500.0, 0.0], [0.0, -100.0, 40.0], 150.0),
        ([-200.0, 50.0, 100.0], [30.0, 10.0, -5.0], 75.0),
    ],
)
def test_exact_lead_is_where_the_projectile_meets_the_target(position, velocity, speed):
    target_position, lead = _kinematics(
        exact_target_kinematics, position, velocity, speed
    )

    # The target is where it is now
    np.testing.assert_allclose(target_position, SHOOTER + position)
    # Fly the projectile at the meeting point: it takes exactly the time the
    # target needs to cover the lead offset
    meeting = np.array(position) + lead
    flight_time_s = np.linalg.norm(meeting) / speed
    np.testing.assert_allclose(lead, np.array(velocity) * flight_time_s)


def test_exact_lead_matches_the_first_order_one_for_a_stationary_target():
    exact = _kinematics(exact_target_kinematics, [60.0, 80.0, 0.0], [0, 0, 0], 50.0)
    first_order = _kinematics(target_kinematics, [60.0, 80.0, 0.0], [0, 0, 0], 50.0)

    np.testing.assert_allclose(exact[0], first_order[0])
    np.testing.assert_allclose(exact[1], first_order[1])


def test_exact_lead_differs_from_first_order_for_a_fast_crossing_target():
    exact = _kinematics(exact_target_kinematics, [0.0, 300.0, 0.0], [60.0, 0, 0], 75.0)
    first_order = _kinematics(target_kinematics, [0.0, 300.0, 0.0], [60.0, 0, 0], 75.0)

    # The first-order lead undershoots: it lets the target move for 300 / 75 s
    # only, while the projectile flies further to reach the led point
    assert exact[1][0] > first_order[1][0] + 1.0


def test_exact_lead_is_linear_when_the_target_is_as_fast_as_the_projectile():
    # Closing head-on at the projectile's own speed: |r + w t| = s t gives t = |r| / 2s
    _, lead = _kinematics(
        exact_target_kinematics, [0.0, 100.0, 0.0], [0, -50.0, 0], 50.0
    )

    np.testing.assert_allclose(lead, [0.0, -50.0, 0.0])  # t = 1 s


@pytest.mark.parametrize(
    "position, velocity, speed",
    [
        ([100.0, 0.0, 0.0], [200.0, 0.0, 0.0], 75.0),  # outruns the projectile
        ([100.0, 0.0, 0.0], [75.0, 0.0, 0.0], 75.0),  # as fast, receding
        ([100.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0.0),  # no speed
    ],
)
def test_exact_lead_is_none_without_an_intercept(position, velocity, speed):
    assert _kinematics(exact_target_kinematics, position, velocity, speed) is None


def test_exact_lead_is_none_without_a_target():
    assert exact_target_kinematics(MagicMock(), "shooter", SHOOTER, None, 75.0) is None
    with patch("space_flight.ai.aim_assist.pair_geometry", return_value=None):
        assert (
            exact_target_kinematics(MagicMock(), "shooter", SHOOTER, "gone", 75.0)
            is None
        )
    with patch("space_flight.ai.aim_assist.pair_geometry", side_effect=ValueError):
        assert (
            exact_target_kinematics(MagicMock(), "dead", SHOOTER, "target", 75.0)
            is None
        )
