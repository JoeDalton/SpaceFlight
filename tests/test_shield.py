"""
Unit tests for the Shield's strength/enable logic and geometry dispatch.

Instances bypass ``__init__`` so the pure logic is testable without a loader or
scene graph.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from space_flight.actors.capital_ship.shield import Shield


def make_shield_without_init(
    generator=None,
    max_health: float = 1000.0,
    current_health: float = 1000.0,
    regen_rate: float = 0.0,
):
    """
    Build a Shield that bypasses __init__ for isolated method testing.
    """
    shield = object.__new__(Shield)
    shield.generator = generator
    shield.max_health = max_health
    shield.health = current_health
    shield.regen_rate = regen_rate
    shield.is_enabled = True
    shield.is_dead = False
    shield.is_clean = False
    shield.node = MagicMock()
    return shield


# ---------------------------
# apply_damage / take_hit
# ---------------------------


def test_apply_damage_reduces_strength():
    """
    Physical damage is subtracted from the shield's strength pool.
    """
    shield = make_shield_without_init(current_health=1000.0)

    shield.apply_damage(damage=250.0, damage_type="physical")

    assert shield.health == pytest.approx(750.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    shield = make_shield_without_init()

    with pytest.raises(NotImplementedError):
        shield.apply_damage(damage=10.0, damage_type="energy")


def test_take_hit_absorbs_into_strength():
    """
    take_hit funnels into physical apply_damage, ignoring the impact normal.
    """
    shield = make_shield_without_init(current_health=500.0)

    shield.take_hit(damage=200.0, normal_world_vector=[1.0, 0.0, 0.0])

    assert shield.health == pytest.approx(300.0)


# ---------------------------
# update behaviour
# ---------------------------


def test_update_regenerates_while_generator_lives():
    """
    While the generator lives, the strength pool regenerates at regen_rate.
    """
    generator = SimpleNamespace(is_dead=False)
    shield = make_shield_without_init(
        generator=generator, max_health=1000.0, current_health=100.0, regen_rate=10.0
    )
    shield.game = MagicMock()
    shield.game.game_time.get_time_step.return_value = 0.5

    shield.update()

    assert shield.health == pytest.approx(105.0)  # 100 + 10 * 0.5
    assert shield.is_enabled is True
    shield.node.show.assert_called_once()


def test_update_disables_when_depleted():
    """
    A depleted shield is disabled and hidden.
    """
    generator = SimpleNamespace(is_dead=False)
    shield = make_shield_without_init(
        generator=generator, current_health=0.0, regen_rate=0.0
    )
    shield.game = MagicMock()

    shield.update()

    assert shield.is_enabled is False
    shield.node.hide.assert_called_once()


def test_update_noop_when_generator_dead():
    """
    Once the generator is dead the shield does nothing (it is about to be cleaned).
    """
    generator = SimpleNamespace(is_dead=True)
    shield = make_shield_without_init(
        generator=generator, current_health=500.0, regen_rate=10.0
    )
    shield.game = MagicMock()

    shield.update()

    assert shield.health == pytest.approx(500.0)  # untouched
    shield.node.show.assert_not_called()
    shield.node.hide.assert_not_called()


# ---------------------------
# get_health: tied to the generator
# ---------------------------


def test_get_health_positive_while_generator_lives():
    """
    A shield is alive (as a Destructible) as long as its generator lives.
    """
    shield = make_shield_without_init(generator=SimpleNamespace(is_dead=False))

    assert shield.get_health() > 0.0


def test_get_health_zero_when_generator_dead():
    """
    Destroying the generator makes the shield report dead, so it is cleaned up.
    """
    shield = make_shield_without_init(generator=SimpleNamespace(is_dead=True))

    assert shield.get_health() == pytest.approx(0.0)


def test_get_health_zero_when_generator_gone():
    """
    A missing generator reference also reports the shield as dead.
    """
    shield = make_shield_without_init(generator=None)

    assert shield.get_health() == pytest.approx(0.0)


def test_depleted_shield_stays_alive_while_generator_lives():
    """
    Depleting the strength pool disables the shield but does not kill it: its life
    tracks the generator, not the strength.
    """
    generator = SimpleNamespace(is_dead=False)
    shield = make_shield_without_init(generator=generator, current_health=0.0)

    assert shield.get_health() > 0.0  # still alive despite zero strength


# ---------------------------
# geometry dispatch
# ---------------------------


def test_build_geometry_rejects_unknown_shape():
    """
    An unrecognised primitive shape type is rejected before any geometry is built.
    """
    shield = object.__new__(Shield)

    with pytest.raises(ValueError):
        shield._build_geometry(
            shape={"type": "pyramid"}, model=None, color=(1.0, 1.0, 1.0, 1.0)
        )
