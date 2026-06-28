import pytest

from space_flight.actors.capital_ship import CapitalShip


def make_capital_ship_without_init(
    max_health: float = 1000.0,
    current_health: float = 1000.0,
):
    """
    Build a CapitalShip instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    capital_ship = object.__new__(CapitalShip)
    capital_ship.max_health = max_health
    capital_ship.health = current_health
    return capital_ship


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_health():
    """
    Physical damage is subtracted directly from the capital ship's health.
    """
    capital_ship = make_capital_ship_without_init(current_health=1000.0)

    capital_ship.apply_damage(damage=200.0, damage_type="physical")

    assert capital_ship.health == pytest.approx(800.0)


def test_apply_damage_physical_can_reduce_health_to_zero():
    """
    Physical damage equal to current health leaves health at exactly zero.
    """
    capital_ship = make_capital_ship_without_init(current_health=300.0)

    capital_ship.apply_damage(damage=300.0, damage_type="physical")

    assert capital_ship.health == pytest.approx(0.0)


def test_apply_damage_physical_can_drive_health_negative():
    """
    Overkill damage drives health below zero.
    """
    capital_ship = make_capital_ship_without_init(current_health=50.0)

    capital_ship.apply_damage(damage=100.0, damage_type="physical")

    assert capital_ship.health == pytest.approx(-50.0)


def test_apply_damage_physical_with_zero_damage_leaves_health_unchanged():
    """
    Applying zero damage does not modify health.
    """
    capital_ship = make_capital_ship_without_init(current_health=1000.0)

    capital_ship.apply_damage(damage=0.0, damage_type="physical")

    assert capital_ship.health == pytest.approx(1000.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    capital_ship = make_capital_ship_without_init()

    with pytest.raises(NotImplementedError):
        capital_ship.apply_damage(damage=10.0, damage_type="energy")


@pytest.mark.parametrize(
    "initial_health, damage, expected_health",
    [
        (1000.0, 0.0, 1000.0),  # no damage
        (1000.0, 500.0, 500.0),  # half health removed
        (1000.0, 1000.0, 0.0),  # exactly depleted
        (1000.0, 1200.0, -200.0),  # overkill
        (0.0, 50.0, -50.0),  # already destroyed
    ],
)
def test_apply_damage_parametrized(initial_health, damage, expected_health):
    """
    Parametrised table covering the physical damage arithmetic.
    """
    capital_ship = make_capital_ship_without_init(current_health=initial_health)

    capital_ship.apply_damage(damage=damage, damage_type="physical")

    assert capital_ship.health == pytest.approx(expected_health)


# ---------------------------
# ship_handle_health
# ---------------------------


def test_ship_handle_health_clamps_health_to_max():
    """
    ship_handle_health reduces health to max_health when it somehow exceeded
    the maximum.
    """
    capital_ship = make_capital_ship_without_init(
        max_health=1000.0, current_health=1500.0
    )

    capital_ship.ship_handle_health()

    assert capital_ship.health == pytest.approx(1000.0)


def test_ship_handle_health_leaves_health_unchanged_when_below_max():
    """
    ship_handle_health does not modify health when it is already within bounds.
    """
    capital_ship = make_capital_ship_without_init(
        max_health=1000.0, current_health=750.0
    )

    capital_ship.ship_handle_health()

    assert capital_ship.health == pytest.approx(750.0)


def test_ship_handle_health_does_not_raise_when_health_is_zero():
    """
    ship_handle_health handles a fully destroyed ship without raising.
    """
    capital_ship = make_capital_ship_without_init(max_health=1000.0, current_health=0.0)

    capital_ship.ship_handle_health()

    assert capital_ship.health == pytest.approx(0.0)
