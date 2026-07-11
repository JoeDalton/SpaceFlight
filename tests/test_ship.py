import numpy as np

from space_flight.actors.ship import Ship


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
