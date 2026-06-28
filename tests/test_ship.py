import numpy as np

from space_flight.actors.ship import Ship


def make_ship_without_init():
    """
    Build a Ship instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    ship = object.__new__(Ship)
    ship.impact_force_n = np.zeros(3)
    return ship


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
