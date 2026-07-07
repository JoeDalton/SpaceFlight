from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
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


def make_capital_ship_with_sub_systems(sub_systems: dict):
    """
    Build a CapitalShip (bypassing __init__) with just what _spawn_mounted_bots
    reads: the config, team and controlling bot name.
    """
    capital_ship = object.__new__(CapitalShip)
    capital_ship.game = SimpleNamespace()
    capital_ship.team = 2
    capital_ship.parent = SimpleNamespace(name="enemy_frigate_0")
    capital_ship.conf = {"sub_systems": sub_systems}
    return capital_ship


# ---------------------------
# _spawn_mounted_bots
# ---------------------------


def test_spawn_mounted_bots_spawns_a_turret_bot_from_config():
    """
    Each turret entry becomes a bot-controlled turret mounted on the ship, on
    the ship's team, with the mounting placement forwarded from the config.
    """
    capital_ship = make_capital_ship_with_sub_systems(
        {
            "turrets": [
                {
                    "turret_type": "test",
                    "base_position": [0.0, 0.0, 20.0],
                    "base_orientation": [1.0, 0.0, 0.0, 0.0],
                    "ini_yaw_deg": 10.0,
                    "ini_pitch_deg": 45.0,
                }
            ]
        }
    )

    with patch("space_flight.actors.bot.spawn_bot") as mock_spawn_bot:
        bots = capital_ship._spawn_mounted_bots(
            "turrets", bot_type="turret", model_key="turret_type"
        )

    mock_spawn_bot.assert_called_once()
    kwargs = mock_spawn_bot.call_args.kwargs
    assert kwargs["bot_type"] == "turret"
    assert kwargs["pawn_model"] == "test"
    assert kwargs["team"] == 2  # taken from the ship
    assert kwargs["parent_object"] is capital_ship
    np.testing.assert_allclose(kwargs["base_position"], [0.0, 0.0, 20.0])
    assert kwargs["ini_yaw_deg"] == pytest.approx(10.0)
    assert kwargs["ini_pitch_deg"] == pytest.approx(45.0)
    assert bots == [mock_spawn_bot.return_value]


def test_spawn_mounted_bots_spawns_a_tractor_beam_from_config():
    """
    The same helper spawns tractor beams from their own config section, reading
    the projector model from the given model key.
    """
    capital_ship = make_capital_ship_with_sub_systems(
        {"tractor_beams": [{"tractor_beam_type": "test"}]}
    )

    with patch("space_flight.actors.bot.spawn_bot") as mock_spawn_bot:
        bots = capital_ship._spawn_mounted_bots(
            "tractor_beams", bot_type="tractor_beam", model_key="tractor_beam_type"
        )

    mock_spawn_bot.assert_called_once()
    kwargs = mock_spawn_bot.call_args.kwargs
    assert kwargs["bot_type"] == "tractor_beam"
    assert kwargs["pawn_model"] == "test"
    assert bots == [mock_spawn_bot.return_value]


def test_spawn_mounted_bots_with_none_declared_returns_empty():
    """
    A ship declaring no mounts of the requested kind spawns none.
    """
    capital_ship = make_capital_ship_with_sub_systems({})

    with patch("space_flight.actors.bot.spawn_bot") as mock_spawn_bot:
        bots = capital_ship._spawn_mounted_bots(
            "turrets", bot_type="turret", model_key="turret_type"
        )

    mock_spawn_bot.assert_not_called()
    assert bots == []


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
