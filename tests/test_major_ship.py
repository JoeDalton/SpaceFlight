from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from space_flight.actors.major_ship import (
    MAJOR_SHIP_CLASSES,
    CapitalShip,
    EscortShip,
    MajorShip,
    major_ship_class,
    make_major_ship,
)


def make_major_ship_without_init(
    max_health: float = 1000.0,
    current_health: float = 1000.0,
):
    """
    Build a MajorShip instance that bypasses __init__ so tests can exercise
    individual methods without requiring Panda3D or YAML assets.
    """
    major_ship = object.__new__(MajorShip)
    major_ship.max_health = max_health
    major_ship.health = current_health
    return major_ship


def make_major_ship_with_sub_systems(sub_systems: dict):
    """
    Build a MajorShip (bypassing __init__) with just what _spawn_mounted_bots
    reads: the config, team and controlling bot name.
    """
    major_ship = object.__new__(MajorShip)
    major_ship.game = SimpleNamespace()
    major_ship.team = 2
    major_ship.parent = SimpleNamespace(name="enemy_frigate_0")
    major_ship.conf = {"sub_systems": sub_systems}
    return major_ship


# ---------------------------
# _spawn_mounted_bots
# ---------------------------


def test_spawn_mounted_bots_spawns_a_turret_bot_from_config():
    """
    Each turret entry becomes a bot-controlled turret mounted on the ship, on
    the ship's team, with the mounting placement forwarded from the config.
    """
    major_ship = make_major_ship_with_sub_systems(
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
        bots = major_ship._spawn_mounted_bots(
            "turrets", bot_type="turret", model_key="turret_type"
        )

    mock_spawn_bot.assert_called_once()
    kwargs = mock_spawn_bot.call_args.kwargs
    assert kwargs["bot_type"] == "turret"
    assert kwargs["pawn_model"] == "test"
    assert kwargs["team"] == 2  # taken from the ship
    assert kwargs["parent_object"] is major_ship
    np.testing.assert_allclose(kwargs["base_position"], [0.0, 0.0, 20.0])
    assert kwargs["ini_yaw_deg"] == pytest.approx(10.0)
    assert kwargs["ini_pitch_deg"] == pytest.approx(45.0)
    assert bots == [mock_spawn_bot.return_value]


def test_spawn_mounted_bots_spawns_a_tractor_beam_from_config():
    """
    The same helper spawns tractor beams from their own config section, reading
    the projector model from the given model key.
    """
    major_ship = make_major_ship_with_sub_systems(
        {"tractor_beams": [{"tractor_beam_type": "test"}]}
    )

    with patch("space_flight.actors.bot.spawn_bot") as mock_spawn_bot:
        bots = major_ship._spawn_mounted_bots(
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
    major_ship = make_major_ship_with_sub_systems({})

    with patch("space_flight.actors.bot.spawn_bot") as mock_spawn_bot:
        bots = major_ship._spawn_mounted_bots(
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
    major_ship = make_major_ship_without_init(current_health=1000.0)

    major_ship.apply_damage(damage=200.0, damage_type="physical")

    assert major_ship.health == pytest.approx(800.0)


def test_apply_damage_physical_can_reduce_health_to_zero():
    """
    Physical damage equal to current health leaves health at exactly zero.
    """
    major_ship = make_major_ship_without_init(current_health=300.0)

    major_ship.apply_damage(damage=300.0, damage_type="physical")

    assert major_ship.health == pytest.approx(0.0)


def test_apply_damage_physical_can_drive_health_negative():
    """
    Overkill damage drives health below zero.
    """
    major_ship = make_major_ship_without_init(current_health=50.0)

    major_ship.apply_damage(damage=100.0, damage_type="physical")

    assert major_ship.health == pytest.approx(-50.0)


def test_apply_damage_physical_with_zero_damage_leaves_health_unchanged():
    """
    Applying zero damage does not modify health.
    """
    major_ship = make_major_ship_without_init(current_health=1000.0)

    major_ship.apply_damage(damage=0.0, damage_type="physical")

    assert major_ship.health == pytest.approx(1000.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    major_ship = make_major_ship_without_init()

    with pytest.raises(NotImplementedError):
        major_ship.apply_damage(damage=10.0, damage_type="energy")


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
    major_ship = make_major_ship_without_init(current_health=initial_health)

    major_ship.apply_damage(damage=damage, damage_type="physical")

    assert major_ship.health == pytest.approx(expected_health)


# ---------------------------
# ship_handle_health
# ---------------------------


def test_ship_handle_health_clamps_health_to_max():
    """
    ship_handle_health reduces health to max_health when it somehow exceeded
    the maximum.
    """
    major_ship = make_major_ship_without_init(max_health=1000.0, current_health=1500.0)

    major_ship.ship_handle_health()

    assert major_ship.health == pytest.approx(1000.0)


def test_ship_handle_health_leaves_health_unchanged_when_below_max():
    """
    ship_handle_health does not modify health when it is already within bounds.
    """
    major_ship = make_major_ship_without_init(max_health=1000.0, current_health=750.0)

    major_ship.ship_handle_health()

    assert major_ship.health == pytest.approx(750.0)


def test_ship_handle_health_does_not_raise_when_health_is_zero():
    """
    ship_handle_health handles a fully destroyed ship without raising.
    """
    major_ship = make_major_ship_without_init(max_health=1000.0, current_health=0.0)

    major_ship.ship_handle_health()

    assert major_ship.health == pytest.approx(0.0)


# ---------------------------
# Ship class selection (make_major_ship)
# ---------------------------


@pytest.mark.parametrize(
    "ship_type, expected_class",
    [("cr-90", EscortShip), ("gr-75", EscortShip), ("isd", CapitalShip)],
)
def test_major_ship_class_follows_the_ship_config(ship_type, expected_class):
    """
    Each shipped major-ship config picks its class with its ship_class key.
    """
    assert major_ship_class(ship_type) is expected_class


def test_major_ship_class_defaults_to_escort():
    """
    A config without ship_class builds an escort ship.
    """
    with patch(
        "space_flight.actors.major_ship.load_ship_configuration", return_value={}
    ):
        assert major_ship_class("anything") is EscortShip


def test_major_ship_class_rejects_unknown_classes():
    """
    An unknown ship_class is a config error.
    """
    with patch(
        "space_flight.actors.major_ship.load_ship_configuration",
        return_value={"ship_class": "dreadnought"},
    ):
        with pytest.raises(ValueError, match="dreadnought"):
            major_ship_class("anything")


def test_make_major_ship_builds_the_configured_class():
    """
    make_major_ship passes its arguments to the class the config picks.
    """
    capital_class = MagicMock()
    with (
        patch(
            "space_flight.actors.major_ship.load_ship_configuration",
            return_value={"ship_class": "capital"},
        ),
        patch.dict(MAJOR_SHIP_CLASSES, {"capital": capital_class}),
    ):
        ship = make_major_ship(game="game", parent="bot", ship_type="isd", team=2)

    assert ship is capital_class.return_value
    capital_class.assert_called_once_with(
        game="game", parent="bot", ship_type="isd", team=2
    )


@pytest.mark.parametrize("ship_class", [EscortShip, CapitalShip])
def test_escort_and_capital_ships_are_major_ships(ship_class):
    """
    Both kinds share the MajorShip machinery (subsystems, shield, ...).
    """
    assert issubclass(ship_class, MajorShip)
