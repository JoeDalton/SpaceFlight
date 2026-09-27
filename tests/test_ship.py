import numpy as np
import pytest
import quaternion

from space_flight import RIGHT_BODY, UP_BODY
from space_flight.actors.ship import Ship
from space_flight.utils import cross3, magnitude, rotate_single_vector


def make_ship_without_init():
    """
    Build a Ship instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    ship = object.__new__(Ship)
    ship.impact_force_n = np.zeros(3)
    ship.external_force_n = np.zeros(3)
    return ship


# ---------------------------
# external forces (tractor beam and friends)
# ---------------------------


def test_apply_external_force_accumulates():
    """
    apply_external_force sums the forces applied this frame, so several sources
    (e.g. two tractor beams) add up.
    """
    ship = make_ship_without_init()

    ship.apply_external_force(np.array([10.0, 0.0, 0.0]))
    ship.apply_external_force(np.array([0.0, -5.0, 2.0]))

    np.testing.assert_allclose(ship.external_force_n, [10.0, -5.0, 2.0])


def test_compute_derivatives_consumes_and_zeroes_external_force():
    """
    compute_derivatives feeds the external force into the acceleration (F / m)
    and then clears it, so the force disappears the moment nothing re-applies it.
    """

    class ConcreteShip(Ship):
        def apply_damage(self, damage, damage_type):
            pass

        def ship_handle_health(self):
            pass

    ship = object.__new__(ConcreteShip)
    ship.state = np.zeros(10)
    ship.state[3:7] = np.array([1.0, 0.0, 0.0, 0.0])
    ship.state_dot = np.zeros(10)
    ship.state_dot_previous = np.zeros(10)
    ship.speed = np.zeros(3)  # no drag/lift at rest, whatever the flight model
    ship.orientation = np.array([1.0, 0.0, 0.0, 0.0])
    ship.pqr = np.zeros(3)
    ship.scalar_thrust_n = 0.0
    ship.mass_kg = 2.0
    ship.additional_force_n = np.zeros(3)
    ship.impact_force_n = np.zeros(3)
    ship.external_force_n = np.array([10.0, 0.0, 0.0])
    ship.drag_factor = 0.0
    ship.lift_factor = 0.0
    ship.lateral_lift_factor = 0.0
    ship.max_thrust_n = 1000.0

    ship.compute_derivatives()

    # F / m ended up in the linear acceleration slots of the state derivative...
    np.testing.assert_allclose(ship.state_dot[7:10], [5.0, 0.0, 0.0])
    # ... and the external force was consumed so it does not persist.
    np.testing.assert_array_equal(ship.external_force_n, np.zeros(3))


# ---------------------------
# remove_hit_force
# ---------------------------


def test_remove_hit_force_subtracts_force_from_impact():
    """
    remove_hit_force subtracts the given force vector from impact_force_n.
    """
    ship = make_ship_without_init()
    ship.impact_force_n = np.array([10.0, 5.0, -3.0])
    applied_force = np.array([3.0, 2.0, -1.0])

    ship.remove_hit_force(applied_force)

    np.testing.assert_array_almost_equal(
        ship.impact_force_n, np.array([7.0, 3.0, -2.0])
    )


def test_remove_hit_force_accumulates_multiple_removals():
    """
    Calling remove_hit_force twice correctly removes both contributions.
    """
    ship = make_ship_without_init()
    ship.impact_force_n = np.array([20.0, 0.0, 0.0])
    force_a = np.array([5.0, 0.0, 0.0])
    force_b = np.array([3.0, 0.0, 0.0])

    ship.remove_hit_force(force_a)
    ship.remove_hit_force(force_b)

    np.testing.assert_array_almost_equal(
        ship.impact_force_n, np.array([12.0, 0.0, 0.0])
    )


def test_remove_hit_force_with_zero_vector_leaves_impact_unchanged():
    """
    Removing a zero-force vector leaves impact_force_n unchanged.
    """
    ship = make_ship_without_init()
    initial_force = np.array([4.0, -2.0, 1.0])
    ship.impact_force_n = initial_force.copy()

    ship.remove_hit_force(np.zeros(3))

    np.testing.assert_array_almost_equal(ship.impact_force_n, initial_force)


# ---------------------------
# push (pure-state fields)
# ---------------------------


def test_push_stores_velocity_and_position_corrections():
    """
    push() writes the given correction vectors into the ship's correction fields
    without modifying any other attribute.

    apply_damage is abstract in Ship, so we supply a concrete override.
    """

    class ConcreteShip(Ship):
        def apply_damage(self, damage, damage_type):
            self.last_damage = damage

        def ship_handle_health(self):
            pass

    concrete = object.__new__(ConcreteShip)
    concrete.impact_force_n = np.zeros(3)
    concrete.velocity_correction = np.zeros(3)
    concrete.position_correction = np.zeros(3)
    concrete.last_damage = 0.0

    velocity_correction = np.array([1.0, 2.0, 3.0])
    position_correction = np.array([-1.0, 0.5, 0.0])

    concrete.push(
        damage=10.0,
        velocity_correction=velocity_correction,
        position_correction=position_correction,
    )

    np.testing.assert_array_equal(concrete.velocity_correction, velocity_correction)
    np.testing.assert_array_equal(concrete.position_correction, position_correction)
    assert concrete.last_damage == 10.0


# ---------------------------
# compute_derivatives: rotation matrix vs the original per-vector rotations
# ---------------------------


class _DerivativesShip(Ship):
    def apply_damage(self, damage, damage_type):
        pass

    def ship_handle_health(self):
        pass


def _make_flying_ship(rng, quaternion_norm=1.0, speed_mps=200.0, lift_factor=0.01):
    """A ship with a random attitude, rates, speed and forces."""
    ship = object.__new__(_DerivativesShip)
    orientation = rng.normal(size=4)
    orientation *= quaternion_norm / np.linalg.norm(orientation)
    ship.state = np.zeros(10)
    ship.state_dot = rng.normal(size=10)
    ship.state_dot_previous = np.zeros(10)
    ship.orientation = orientation
    ship.speed = speed_mps * rng.normal(size=3) / np.sqrt(3.0)
    ship.pqr = rng.uniform(-2.0, 2.0, size=3)
    ship.scalar_thrust_n = 5000.0
    ship.mass_kg = 1000.0
    ship.additional_force_n = rng.normal(size=3)
    ship.impact_force_n = rng.normal(size=3)
    ship.external_force_n = rng.normal(size=3)
    ship.drag_factor = 0.02
    ship.lift_factor = lift_factor
    ship.lateral_lift_factor = 0.5 * lift_factor
    ship.max_thrust_n = 20000.0
    return ship


def _reference_compute_derivatives(ship):
    """The original implementation (one rotate_single_vector per vector)."""
    ship.state_dot_previous = ship.state_dot.copy()
    ship.state_dot[0:3] = ship.speed.copy()
    quat = np.quaternion(*ship.orientation)
    quat_pqr = np.quaternion(0, *ship.pqr)
    ship.state_dot[3:7] = quaternion.as_float_array(0.5 * quat * quat_pqr)
    ship.forward = rotate_single_vector(quat, np.array([0.0, 1.0, 0.0]))
    ship.right = rotate_single_vector(quat, RIGHT_BODY)
    ship.up = rotate_single_vector(quat, UP_BODY)
    ship.thrust_n = ship.scalar_thrust_n * ship.forward
    speed_norm = magnitude(ship.speed)
    if np.isnan(speed_norm) or (speed_norm <= 1e-4):
        ship.drag_n = np.zeros(3)
        ship.lift_n = np.zeros(3)
        ship.lift_body_n = np.zeros(3)
    else:
        ship.drag_n = -ship.drag_factor * speed_norm * ship.speed
        airflow_speed_body = -rotate_single_vector(quat.conjugate(), ship.speed)
        airflow_direction_body = airflow_speed_body / speed_norm
        angle_of_attack_deg = -np.rad2deg(
            np.arctan2(-airflow_speed_body[2], -airflow_speed_body[1])
        )
        side_slip_angle_deg = np.rad2deg(
            np.arcsin(np.clip(airflow_speed_body[0] / speed_norm, -1.0, 1.0))
        )
        ship.lift_body_n = ship.lift_factor * speed_norm**2 * angle_of_attack_deg * (
            cross3(airflow_direction_body, RIGHT_BODY)
        ) + ship.lateral_lift_factor * speed_norm**2 * side_slip_angle_deg * cross3(
            UP_BODY, airflow_direction_body
        )
        ship.lift_n = rotate_single_vector(quat, ship.lift_body_n)
        lift_norm_n = magnitude(ship.lift_n)
        if lift_norm_n > ship.max_thrust_n:
            ship.lift_n /= lift_norm_n
            ship.lift_n *= ship.max_thrust_n
    ship.acceleration_mps2 = (
        ship.thrust_n
        + ship.drag_n
        + ship.lift_n
        + ship.additional_force_n
        + ship.impact_force_n
        + ship.external_force_n
    ) / ship.mass_kg
    ship.state_dot[7:10] = ship.acceleration_mps2
    ship.external_force_n = np.zeros(3)


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize(
    "case",
    [
        dict(),  # typical flight
        dict(quaternion_norm=0.99),  # orientation drifted off unit norm
        dict(speed_mps=0.0),  # at rest: no lift nor drag
        dict(lift_factor=10.0),  # lift clipped to max thrust
    ],
)
def test_compute_derivatives_matches_per_vector_rotations(seed, case):
    reference = _make_flying_ship(np.random.default_rng(seed), **case)
    ship = _make_flying_ship(np.random.default_rng(seed), **case)

    _reference_compute_derivatives(reference)
    ship.compute_derivatives()

    for name in (
        "state_dot",
        "state_dot_previous",
        "forward",
        "right",
        "up",
        "thrust_n",
        "drag_n",
        "lift_body_n",
        "lift_n",
        "acceleration_mps2",
        "external_force_n",
    ):
        np.testing.assert_allclose(
            getattr(ship, name), getattr(reference, name), rtol=1e-10, atol=1e-9
        )
