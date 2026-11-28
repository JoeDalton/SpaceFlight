"""
Tests for the generic aim assist (space_flight.ai.aim_assist), shared by the laser
cannons' auto-aim and the bomb launchers.
"""

import numpy as np
import pytest

from space_flight.ai.aim_assist import AssistCone, aim_toward

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
