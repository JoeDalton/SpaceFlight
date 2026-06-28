from unittest.mock import MagicMock

import pytest

from space_flight.actors.fighter import Fighter


def make_fighter_without_init(
    max_health: float = 200.0,
    current_health: float = 200.0,
    max_shield: float = 100.0,
    current_shield: float = 100.0,
    shield_regen_rate: float = 10.0,
):
    """
    Build a Fighter instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    fighter = object.__new__(Fighter)
    fighter.max_health = max_health
    fighter.health = current_health
    fighter.max_shield = max_shield
    fighter.shield = current_shield
    fighter.shield_regen_rate = shield_regen_rate
    return fighter


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_shield_first():
    """
    Physical damage is absorbed by the shield before touching health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=100.0)

    fighter.apply_damage(damage=40.0, damage_type="physical")

    assert fighter.shield == pytest.approx(60.0)
    assert fighter.health == pytest.approx(200.0)


def test_apply_damage_physical_overflow_carries_to_health():
    """
    When damage exceeds the remaining shield, the overflow reduces health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=30.0)

    fighter.apply_damage(damage=50.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(180.0)


def test_apply_damage_physical_with_zero_shield_only_reduces_health():
    """
    When the shield is already depleted, all physical damage hits health directly.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=0.0)

    fighter.apply_damage(damage=25.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(175.0)


def test_apply_damage_physical_exact_shield_depletion():
    """
    Damage exactly equal to the remaining shield brings it to zero without
    touching health.
    """
    fighter = make_fighter_without_init(current_health=200.0, current_shield=50.0)

    fighter.apply_damage(damage=50.0, damage_type="physical")

    assert fighter.shield == pytest.approx(0.0)
    assert fighter.health == pytest.approx(200.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    fighter = make_fighter_without_init()

    with pytest.raises(NotImplementedError):
        fighter.apply_damage(damage=10.0, damage_type="energy")


@pytest.mark.parametrize(
    "initial_shield, initial_health, damage, expected_shield, expected_health",
    [
        (100.0, 200.0, 80.0, 20.0, 200.0),  # damage < shield
        (100.0, 200.0, 100.0, 0.0, 200.0),  # damage == shield
        (100.0, 200.0, 150.0, 0.0, 150.0),  # damage > shield
        (0.0, 200.0, 30.0, 0.0, 170.0),  # no shield at all
        (50.0, 200.0, 0.0, 50.0, 200.0),  # zero damage
    ],
)
def test_apply_damage_parametrized(
    initial_shield,
    initial_health,
    damage,
    expected_shield,
    expected_health,
):
    """
    Parametrised table covering the full shield/health damage distribution logic.
    """
    fighter = make_fighter_without_init(
        current_health=initial_health, current_shield=initial_shield
    )

    fighter.apply_damage(damage=damage, damage_type="physical")

    assert fighter.shield == pytest.approx(expected_shield)
    assert fighter.health == pytest.approx(expected_health)


# ---------------------------
# ship_handle_health
# ---------------------------


def make_fighter_with_game(
    current_shield: float,
    max_shield: float,
    current_health: float,
    max_health: float,
    shield_regen_rate: float,
    time_step_s: float,
):
    """
    Build a Fighter with a mocked game for ship_handle_health tests.
    """
    fighter = make_fighter_without_init(
        max_health=max_health,
        current_health=current_health,
        max_shield=max_shield,
        current_shield=current_shield,
        shield_regen_rate=shield_regen_rate,
    )
    mock_game = MagicMock()
    mock_game.game_time.get_time_step.return_value = time_step_s
    fighter.game = mock_game
    return fighter


def test_ship_handle_health_regenerates_shield_by_rate_times_dt():
    """
    ship_handle_health increases shield by shield_regen_rate * dt.
    """
    fighter = make_fighter_with_game(
        current_shield=80.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=5.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(85.0)


def test_ship_handle_health_does_not_regenerate_shield_above_max():
    """
    ship_handle_health clamps shield to max_shield.
    """
    fighter = make_fighter_with_game(
        current_shield=98.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=5.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(100.0)


def test_ship_handle_health_clamps_health_to_max():
    """
    ship_handle_health clamps health to max_health even if it somehow exceeded it.
    """
    fighter = make_fighter_with_game(
        current_shield=100.0,
        max_shield=100.0,
        current_health=250.0,  # artificially above max
        max_health=200.0,
        shield_regen_rate=0.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.health == pytest.approx(200.0)


def test_ship_handle_health_shield_stays_zero_when_fully_depleted_and_no_regen():
    """
    A fully depleted shield remains at zero when shield_regen_rate is zero.
    """
    fighter = make_fighter_with_game(
        current_shield=0.0,
        max_shield=100.0,
        current_health=200.0,
        max_health=200.0,
        shield_regen_rate=0.0,
        time_step_s=1.0,
    )

    fighter.ship_handle_health()

    assert fighter.shield == pytest.approx(0.0)
