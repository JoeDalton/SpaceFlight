import pytest

from space_flight.actors.turret import Turret


def make_turret_without_init(
    max_health: float = 150.0,
    current_health: float = 150.0,
):
    """
    Build a Turret instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    turret = object.__new__(Turret)
    turret.max_health = max_health
    turret.health = current_health
    return turret


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_health():
    """
    Physical damage is subtracted directly from the turret's health.
    """
    turret = make_turret_without_init(current_health=150.0)

    turret.apply_damage(damage=40.0, damage_type="physical")

    assert turret.health == pytest.approx(110.0)


def test_apply_damage_physical_can_reduce_health_to_zero():
    """
    Physical damage equal to the current health leaves health at exactly zero.
    """
    turret = make_turret_without_init(current_health=50.0)

    turret.apply_damage(damage=50.0, damage_type="physical")

    assert turret.health == pytest.approx(0.0)


def test_apply_damage_physical_can_drive_health_negative():
    """
    Overkill damage drives health below zero; the caller is responsible for
    checking the result.
    """
    turret = make_turret_without_init(current_health=10.0)

    turret.apply_damage(damage=30.0, damage_type="physical")

    assert turret.health == pytest.approx(-20.0)


def test_apply_damage_physical_with_zero_damage_leaves_health_unchanged():
    """
    Applying zero damage does not modify health.
    """
    turret = make_turret_without_init(current_health=150.0)

    turret.apply_damage(damage=0.0, damage_type="physical")

    assert turret.health == pytest.approx(150.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    turret = make_turret_without_init()

    with pytest.raises(NotImplementedError):
        turret.apply_damage(damage=10.0, damage_type="energy")


@pytest.mark.parametrize(
    "initial_health, damage, expected_health",
    [
        (150.0, 0.0, 150.0),  # no damage
        (150.0, 75.0, 75.0),  # half health removed
        (150.0, 150.0, 0.0),  # exactly depleted
        (150.0, 200.0, -50.0),  # overkill
        (0.0, 10.0, -10.0),  # already dead
    ],
)
def test_apply_damage_parametrized(initial_health, damage, expected_health):
    """
    Parametrised table covering the physical damage arithmetic.
    """
    turret = make_turret_without_init(current_health=initial_health)

    turret.apply_damage(damage=damage, damage_type="physical")

    assert turret.health == pytest.approx(expected_health)


# ---------------------------
# turret_handle_health
# ---------------------------


def test_turret_handle_health_clamps_health_to_max():
    """
    turret_handle_health reduces health to max_health when health somehow
    exceeds the maximum.
    """
    turret = make_turret_without_init(max_health=150.0, current_health=200.0)

    turret.turret_handle_health()

    assert turret.health == pytest.approx(150.0)


def test_turret_handle_health_leaves_health_unchanged_when_below_max():
    """
    turret_handle_health does not modify health when it is already within bounds.
    """
    turret = make_turret_without_init(max_health=150.0, current_health=100.0)

    turret.turret_handle_health()

    assert turret.health == pytest.approx(100.0)


def test_turret_handle_health_does_not_raise_when_health_is_zero():
    """
    turret_handle_health handles a fully depleted turret without raising.
    """
    turret = make_turret_without_init(max_health=150.0, current_health=0.0)

    turret.turret_handle_health()

    assert turret.health == pytest.approx(0.0)
