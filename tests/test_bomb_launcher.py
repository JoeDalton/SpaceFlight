"""
Unit tests for BombLauncher (space_flight.weapons.bomb_launcher).

BombLauncher.__init__ needs no Panda3D nodes, so it is constructed directly.
Bomb spawning inside launch() is monkeypatched out so the launch geometry can be
validated without a live render context.
"""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from space_flight.weapons.bomb_launcher import (
    BOMB_RANGE_M,
    BOMB_SPEED_MPS,
    BombLauncher,
)


@pytest.fixture
def bomb_launcher():
    """A BombLauncher with __init__ bypassed, aimed belly-down over the origin."""
    launcher = object.__new__(BombLauncher)
    launcher.range_m = BOMB_RANGE_M
    launcher.life_time_s = BOMB_RANGE_M / BOMB_SPEED_MPS
    launcher.power = 1500.0
    # Reload gate wide open by default (fires immediately).
    launcher.fire_delay = 0.0
    launcher.last_fire_time = 0.0
    launcher.parent = MagicMock()
    launcher.parent.id = uuid.uuid4()
    launcher.parent.up = np.array([0.0, 0.0, 1.0])
    launcher.parent.speed = np.array([0.0, 100.0, 0.0])
    launcher.parent_node = MagicMock()
    launcher.parent_node.get_pos.return_value = np.zeros(3)
    launcher.game = MagicMock()
    launcher.game.game_time.get_current_time.return_value = 100.0
    return launcher


def test_life_time_is_range_over_speed():
    """The bomb lifetime is range / base speed."""
    launcher = BombLauncher(game=MagicMock(), parent=MagicMock())

    assert launcher.life_time_s == pytest.approx(BOMB_RANGE_M / BOMB_SPEED_MPS)


def test_launch_spawns_a_bomb(bomb_launcher):
    """launch() spawns exactly one Bomb."""
    with patch("space_flight.weapons.bomb_launcher.Bomb") as mock_bomb:
        bomb_launcher.launch()

    mock_bomb.assert_called_once()


def test_launch_velocity_is_belly_down_plus_ship_speed(bomb_launcher):
    """
    The bomb's velocity is the ship's velocity minus base_speed along +Z (i.e.
    launched down the belly, carrying the ship's motion).
    """
    with patch("space_flight.weapons.bomb_launcher.Bomb") as mock_bomb:
        bomb_launcher.launch()

    speed = mock_bomb.call_args.kwargs["speed"]
    np.testing.assert_allclose(speed, [0.0, 100.0, -BOMB_SPEED_MPS])


def test_launch_passes_origin_power_and_lifetime(bomb_launcher):
    """launch() forwards the emitter, damage and lifetime to the Bomb."""
    with patch("space_flight.weapons.bomb_launcher.Bomb") as mock_bomb:
        bomb_launcher.launch()

    kwargs = mock_bomb.call_args.kwargs
    assert kwargs["origin_ship_id"] == bomb_launcher.parent.id
    assert kwargs["origin_ship"] is bomb_launcher.parent
    assert kwargs["power"] == pytest.approx(1500.0)
    assert kwargs["life_time_s"] == pytest.approx(BOMB_RANGE_M / BOMB_SPEED_MPS)


def test_launch_reports_success(bomb_launcher):
    """launch() returns True when a bomb is actually released."""
    with patch("space_flight.weapons.bomb_launcher.Bomb"):
        assert bomb_launcher.launch() is True


def test_launch_is_rate_limited(bomb_launcher):
    """
    A second launch inside the reload delay is refused (no bomb, returns False),
    then allowed again once the delay has elapsed.
    """
    bomb_launcher.fire_delay = 2.0
    bomb_launcher.last_fire_time = 0.0

    with patch("space_flight.weapons.bomb_launcher.Bomb") as mock_bomb:
        # t=2.0: 2.0s since the last fire (t=0) == reload -> allowed.
        bomb_launcher.game.game_time.get_current_time.return_value = 2.0
        assert bomb_launcher.launch() is True
        # t=3.0: only 1.0s since the last drop < 2.0s reload -> refused.
        bomb_launcher.game.game_time.get_current_time.return_value = 3.0
        assert bomb_launcher.launch() is False
        # t=4.0: 2.0s elapsed since the last drop -> allowed again.
        bomb_launcher.game.game_time.get_current_time.return_value = 4.0
        assert bomb_launcher.launch() is True

    assert mock_bomb.call_count == 2


def test_clean_clears_references(bomb_launcher):
    """clean() drops the upward references."""
    bomb_launcher.clean()

    assert bomb_launcher.parent is None
    assert bomb_launcher.game is None
