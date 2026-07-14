"""
Unit tests for LaserCannon (space_flight.weapons.laser_cannon).

LaserCannon.__init__ requires live Panda3D nodes and asset pools, so tests
that exercise post-construction logic use object.__new__() to bypass it and
manually set the minimal attributes needed by each method under test.

LaserShot creation inside fire() is monkeypatched out so that the cannon
cycling and rate-limiting logic can be validated without a live render context.
"""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from panda3d.core import Vec3

from space_flight.weapons.laser_cannon import LaserCannon

FIRE_DELAY_S = 0.5
N_CANNONS = 2


@pytest.fixture
def laser_cannon():
    """
    A LaserCannon instance with __init__ bypassed and all necessary attributes
    set to sensible defaults for testing.
    """
    cannon = object.__new__(LaserCannon)
    cannon.fire_delay = FIRE_DELAY_S
    cannon.last_fire_time = 0.0
    cannon.current_next_cannon_idx = 0
    cannon.n_cannon = N_CANNONS
    cannon.cannon_nodes = [MagicMock(name=f"cannon_node_{i}") for i in range(N_CANNONS)]
    cannon.shot_power = 10.0
    cannon.life_time_s = 1.0
    cannon.light_color = (1.0, 0.0, 0.0, 1.0)
    cannon.laser_color_rgb = Vec3(1.0, 0.05, 0.05)
    cannon.sound_pool = MagicMock()

    # Parent ship stub: no auto_aim so fire() falls back to speed + forward
    cannon.parent = MagicMock()
    del cannon.parent.auto_aim  # ensure AttributeError path is taken
    cannon.parent.forward = np.array([0.0, 1.0, 0.0])
    cannon.parent.speed = np.zeros(3)
    cannon.parent.id = uuid.uuid4()

    cannon.game = MagicMock()
    cannon.game.game_time.get_current_time.return_value = 0.0

    return cannon


# ---------------------------
# fire() – rate limiting
# ---------------------------


def test_fire_does_not_proceed_before_cooldown_expires(laser_cannon):
    """
    fire() returns immediately without spawning a shot when the elapsed time
    since the last shot is shorter than fire_delay.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S * 0.5
    )

    laser_cannon.fire()

    # get_pos on any cannon node is only called when a shot is actually fired
    for node in laser_cannon.cannon_nodes:
        node.get_pos.assert_not_called()


def test_fire_proceeds_exactly_at_cooldown_boundary(laser_cannon):
    """
    fire() spawns a shot when elapsed time equals exactly fire_delay.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S
    )

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    mock_laser_shot.assert_called_once()


def test_fire_proceeds_after_cooldown_expires(laser_cannon):
    """
    fire() spawns a shot when sufficient time has passed since the last shot.
    """
    laser_cannon.game.game_time.get_current_time.return_value = (
        laser_cannon.last_fire_time + FIRE_DELAY_S * 2
    )

    with patch("space_flight.weapons.laser_cannon.LaserShot") as mock_laser_shot:
        laser_cannon.fire()

    mock_laser_shot.assert_called_once()


# ---------------------------
# fire() – cannon index cycling
# ---------------------------


def test_fire_advances_cannon_index_after_shot(laser_cannon):
    """
    fire() increments current_next_cannon_idx by one after a successful shot.
    """
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.current_next_cannon_idx == 1


def test_fire_wraps_cannon_index_around_after_last_cannon(laser_cannon):
    """
    After the last cannon fires, current_next_cannon_idx wraps back to zero.
    """
    laser_cannon.current_next_cannon_idx = N_CANNONS - 1
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.current_next_cannon_idx == 0


def test_fire_uses_current_cannon_node_for_shot_origin(laser_cannon):
    """
    fire() calls get_pos on the cannon node at current_next_cannon_idx.
    """
    laser_cannon.current_next_cannon_idx = 1
    laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    laser_cannon.cannon_nodes[1].get_pos.assert_called_once_with(
        laser_cannon.game.root_node
    )
    laser_cannon.cannon_nodes[0].get_pos.assert_not_called()


def test_fire_updates_last_fire_time(laser_cannon):
    """
    fire() records the current time as last_fire_time after a successful shot.
    """
    fire_time = 7.3
    laser_cannon.game.game_time.get_current_time.return_value = fire_time

    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        laser_cannon.fire()

    assert laser_cannon.last_fire_time == pytest.approx(fire_time)


def test_fire_does_not_update_last_fire_time_when_on_cooldown(laser_cannon):
    """
    fire() does not change last_fire_time when the cooldown has not expired.
    """
    initial_last_fire_time = laser_cannon.last_fire_time
    laser_cannon.game.game_time.get_current_time.return_value = (
        initial_last_fire_time + FIRE_DELAY_S * 0.1
    )

    laser_cannon.fire()

    assert laser_cannon.last_fire_time == pytest.approx(initial_last_fire_time)


# ---------------------------
# fire() – consecutive calls cycle through all cannons
# ---------------------------


def test_fire_cycles_through_all_cannon_indices(laser_cannon):
    """
    Firing once per cannon cycles through indices 0 → 1 → 0 for a two-cannon
    configuration.
    """
    with patch("space_flight.weapons.laser_cannon.LaserShot"):
        for shot_number in range(N_CANNONS * 2):
            laser_cannon.last_fire_time = 0.0
            laser_cannon.game.game_time.get_current_time.return_value = FIRE_DELAY_S
            expected_index_before = shot_number % N_CANNONS
            assert laser_cannon.current_next_cannon_idx == expected_index_before
            laser_cannon.fire()


# ---------------------------
# clean()
# ---------------------------


def test_clean_calls_remove_node_on_all_cannon_nodes(laser_cannon):
    """
    clean() calls remove_node() on every cannon node.
    """
    laser_cannon.clean()

    for node in laser_cannon.cannon_nodes:
        node.remove_node.assert_called_once()


def test_clean_empties_cannon_nodes_list(laser_cannon):
    """
    clean() replaces cannon_nodes with an empty list.
    """
    laser_cannon.clean()

    assert laser_cannon.cannon_nodes == []


def test_clean_clears_parent_reference(laser_cannon):
    """
    clean() sets parent to None so the cannon holds no upward reference.
    """
    laser_cannon.clean()

    assert laser_cannon.parent is None


def test_clean_clears_game_reference(laser_cannon):
    """
    clean() sets game to None.
    """
    laser_cannon.clean()

    assert laser_cannon.game is None


def test_clean_clears_laser_color_reference(laser_cannon):
    """
    clean() sets laser_color_rgb to None.
    """
    laser_cannon.clean()

    assert laser_cannon.laser_color_rgb is None
