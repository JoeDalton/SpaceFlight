"""
Unit tests for CollisionSensor (space_flight.ai.collision_sensor).

CollisionSensor.__init__ attaches Panda3D collision nodes and cannot run
headlessly.  All tests bypass __init__ via object.__new__() and populate
the instance with the minimal attributes consumed by compute_repulsion().
"""

import numpy as np
import pytest

from space_flight.ai.collision_sensor import CollisionSensor


def make_collision_sensor(
    self_position: np.ndarray = None,
    reference_distance_m: float = 100.0,
) -> CollisionSensor:
    """
    Build a CollisionSensor that bypasses __init__.

    :param self_position: world-space position of the owning ship
    :param reference_distance_m: reference distance for weight computation
    :return: a CollisionSensor ready for compute_repulsion tests
    """
    sensor = object.__new__(CollisionSensor)
    sensor.obstacles = []
    sensor.collision_reference_distance_m = reference_distance_m

    class FakeShip:
        pass

    ship = FakeShip()
    ship.position = np.zeros(3) if self_position is None else self_position.copy()
    sensor.ship = ship
    return sensor


def make_obstacle(
    normal: np.ndarray,
    hit_point: np.ndarray,
) -> dict:
    """
    Build an obstacle dictionary as stored in CollisionSensor.obstacles.

    :param normal: surface normal pointing away from the obstacle
    :param hit_point: world-space contact point
    :return: the obstacle dict
    """
    return {"normal": normal.copy(), "hit_point": hit_point.copy()}


# ---------------------------------------------------------------------------
# No obstacles
# ---------------------------------------------------------------------------


def test_compute_repulsion_no_obstacles_returns_zero_vector():
    """
    With an empty obstacle list the repulsion vector must be the zero vector.
    """
    sensor = make_collision_sensor()

    repulsion_vector, total_weight = sensor.compute_repulsion()

    np.testing.assert_array_equal(repulsion_vector, np.zeros(3))


def test_compute_repulsion_no_obstacles_returns_zero_weight():
    """
    With an empty obstacle list the returned weight must be 0.0.
    """
    sensor = make_collision_sensor()

    _, total_weight = sensor.compute_repulsion()

    assert total_weight == pytest.approx(0.0)


def test_compute_repulsion_clears_obstacles_after_call():
    """
    After compute_repulsion() returns, the obstacles list must be empty so
    the next frame starts fresh.
    """
    sensor = make_collision_sensor()
    sensor.obstacles = [
        make_obstacle(np.array([0.0, 1.0, 0.0]), np.array([0.0, 50.0, 0.0]))
    ]

    sensor.compute_repulsion()

    assert sensor.obstacles == []


# ---------------------------------------------------------------------------
# Single obstacle
# ---------------------------------------------------------------------------


def test_compute_repulsion_single_obstacle_returns_normal_direction():
    """
    With one obstacle carrying a clean unit normal, the returned repulsion
    vector must equal that normal (weight cancels out in the normalisation).
    """
    sensor = make_collision_sensor(self_position=np.zeros(3))
    normal = np.array([0.0, -1.0, 0.0])
    hit_point = np.array([0.0, 50.0, 0.0])
    sensor.obstacles = [make_obstacle(normal, hit_point)]

    repulsion_vector, _ = sensor.compute_repulsion()

    np.testing.assert_allclose(repulsion_vector, normal, atol=1e-6)


def test_compute_repulsion_single_obstacle_weight_equals_reference_over_distance():
    """
    With one obstacle the returned total_weight must equal
    collision_reference_distance_m / distance (the per-obstacle weight divided
    by 1 for normalisation).
    """
    reference_distance_m = 100.0
    sensor = make_collision_sensor(
        self_position=np.zeros(3), reference_distance_m=reference_distance_m
    )
    hit_point = np.array([0.0, 50.0, 0.0])
    normal = np.array([0.0, -1.0, 0.0])
    sensor.obstacles = [make_obstacle(normal, hit_point)]

    _, total_weight = sensor.compute_repulsion()

    distance = np.linalg.norm(hit_point)
    expected_weight = reference_distance_m / distance
    assert total_weight == pytest.approx(expected_weight)


# ---------------------------------------------------------------------------
# Degenerate normal
# ---------------------------------------------------------------------------


def test_compute_repulsion_zero_normal_falls_back_to_obstacle_direction():
    """
    When the provided normal is nearly zero, compute_repulsion must fall back
    to the direction from self to the hit point as the repulsion normal.
    """
    sensor = make_collision_sensor(self_position=np.zeros(3))
    hit_point = np.array([0.0, 50.0, 0.0])
    degenerate_normal = np.zeros(3)
    sensor.obstacles = [make_obstacle(degenerate_normal, hit_point)]

    repulsion_vector, total_weight = sensor.compute_repulsion()

    expected_direction = hit_point / np.linalg.norm(hit_point)
    np.testing.assert_allclose(repulsion_vector, expected_direction, atol=1e-6)


# ---------------------------------------------------------------------------
# Two obstacles
# ---------------------------------------------------------------------------


def test_compute_repulsion_two_obstacles_weight_is_averaged():
    """
    With two obstacles the total_weight must be the average of the individual
    weights, not their sum.
    """
    reference_distance_m = 100.0
    sensor = make_collision_sensor(
        self_position=np.zeros(3), reference_distance_m=reference_distance_m
    )
    hit_a = np.array([50.0, 0.0, 0.0])
    hit_b = np.array([0.0, 100.0, 0.0])
    sensor.obstacles = [
        make_obstacle(np.array([-1.0, 0.0, 0.0]), hit_a),
        make_obstacle(np.array([0.0, -1.0, 0.0]), hit_b),
    ]

    _, total_weight = sensor.compute_repulsion()

    weight_a = reference_distance_m / np.linalg.norm(hit_a)
    weight_b = reference_distance_m / np.linalg.norm(hit_b)
    expected_average_weight = (weight_a + weight_b) / 2
    assert total_weight == pytest.approx(expected_average_weight)


def test_compute_repulsion_two_opposing_obstacles_cancel_vectors():
    """
    Two obstacles on exactly opposite sides with equal weights must produce a
    near-zero repulsion vector.
    """
    reference_distance_m = 100.0
    sensor = make_collision_sensor(
        self_position=np.zeros(3), reference_distance_m=reference_distance_m
    )
    hit_a = np.array([50.0, 0.0, 0.0])
    hit_b = np.array([-50.0, 0.0, 0.0])
    sensor.obstacles = [
        make_obstacle(np.array([-1.0, 0.0, 0.0]), hit_a),
        make_obstacle(np.array([1.0, 0.0, 0.0]), hit_b),
    ]

    repulsion_vector, _ = sensor.compute_repulsion()

    assert np.linalg.norm(repulsion_vector) == pytest.approx(0.0, abs=1e-6)
