"""
Unit tests for the generic TrackingMount base
(space_flight.actors.capital_ship.tracking_mount).

Instances are built with object.__new__ so move()'s aim integration can be
exercised without Panda3D assets. move() is fed a mocked integrator and model.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.capital_ship.tracking_mount import TrackingMount


def make_tracking_mount_without_init(
    yaw_deg: float = 0.0, pitch_deg: float = 30.0, new_state=None
):
    """
    Build a TrackingMount that bypasses __init__ with the minimum needed by
    move(): aim state/agility, a mocked integrator returning ``new_state``, a
    mocked swivelling model, and mocked node quats.
    """
    mount = object.__new__(TrackingMount)
    mount.conf = {"min_pitch_deg": 5.0, "max_pitch_deg": 70.0}
    mount.max_yaw_rate_degps = 30.0
    mount.max_pitch_rate_degps = 30.0
    mount.physics_filter_time_s = 0.3
    mount.state = np.array([yaw_deg, pitch_deg])
    mount.state_derivative = np.zeros(2)

    mount.set_yaw = MagicMock()
    mount.set_pitch = MagicMock()

    mount.turret_model = MagicMock()
    mount.turret_model.cannon_node.getQuat.return_value = (1.0, 0.0, 0.0, 0.0)

    mount.node = MagicMock()
    mount.node.getQuat.return_value = (1.0, 0.0, 0.0, 0.0)

    mount.game = MagicMock()
    mount.game.game_time.get_time_step.return_value = 0.1
    if new_state is None:
        new_state = np.array([yaw_deg, pitch_deg])
    mount.game.integrator.first_order_euler_step.return_value = np.array(
        new_state, dtype=float
    )
    return mount


def test_move_clips_pitch_to_config_bounds():
    """
    move() clips the integrated pitch to the mount's [min, max] pitch bounds.
    """
    mount = make_tracking_mount_without_init(new_state=[0.0, 200.0])

    mount.move(yaw_rate=0.0, pitch_rate=1.0)

    # Pitch integrated to 200 deg but the mount can only reach 70.
    assert mount.state[1] == pytest.approx(70.0)


def test_move_drives_the_model_with_the_new_angles():
    """
    move() pushes the freshly integrated yaw and pitch onto the model.
    """
    mount = make_tracking_mount_without_init(new_state=[12.0, 34.0])

    mount.move(yaw_rate=0.5, pitch_rate=0.5)

    mount.set_yaw.assert_called_with(pytest.approx(12.0))
    mount.set_pitch.assert_called_with(pytest.approx(34.0))


def test_move_refreshes_forward_direction():
    """
    move() recomputes the barrel/antenna forward direction (identity quat aims
    the cannon down +Y).
    """
    mount = make_tracking_mount_without_init()

    mount.move(yaw_rate=0.0, pitch_rate=0.0)

    np.testing.assert_allclose(mount.forward, [0.0, 1.0, 0.0], atol=1e-6)


def test_move_runs_the_operate_hook():
    """
    move() calls the subclass action hook once, after aiming.
    """
    mount = make_tracking_mount_without_init()
    mount._operate = MagicMock()

    mount.move(yaw_rate=0.0, pitch_rate=0.0)

    mount._operate.assert_called_once()


def test_base_operate_is_a_noop():
    """
    The base _operate does nothing (subclasses provide the action).
    """
    mount = object.__new__(TrackingMount)

    # Should not raise
    assert mount._operate() is None


def test_speed_property_returns_host_ship_speed():
    """
    A mount reports its host ship's velocity live, so its death explosion (fired
    by its Bot, which reads pawn.speed) carries the ship's motion rather than zero.
    """
    mount = object.__new__(TrackingMount)
    mount.mounted_on = SimpleNamespace(speed=np.array([12.0, -3.0, 0.0]))

    np.testing.assert_allclose(mount.speed, [12.0, -3.0, 0.0])


def test_speed_property_is_zero_once_detached():
    """
    Once detached (cleaned, mounted_on is None), the mount reports zero velocity
    rather than raising.
    """
    mount = object.__new__(TrackingMount)
    mount.mounted_on = None

    np.testing.assert_array_equal(mount.speed, np.zeros(3))
