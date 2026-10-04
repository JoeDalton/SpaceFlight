"""
Unit tests for AutoAim (space_flight.ai.auto_aim).

AutoAim.__init__ requires a live game object; all tests bypass it with
object.__new__() and set only the attributes consumed by each method under
test.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai.auto_aim import AutoAim
from space_flight.ai.target_lock import TargetLock


class _Clock:
    """A controllable time source for the target lock's state machine."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_auto_aim(
    target_lock_delay_s: float = 1.0,
    acquisition_cone_angle_deg: float = 30.0,
    max_assist_angle_deg: float = 5.0,
) -> AutoAim:
    """
    Build an AutoAim that bypasses __init__ with sensible defaults.

    :param target_lock_delay_s: seconds before target lock is confirmed
    :param acquisition_cone_angle_deg: half-angle of the acquisition cone
    :param max_assist_angle_deg: half-angle of the assist cone
    :return: an AutoAim whose methods can be tested in isolation
    """
    auto_aim = object.__new__(AutoAim)
    auto_aim.game = MagicMock()
    auto_aim.parent = MagicMock()
    clock = _Clock()
    auto_aim._clock = clock
    auto_aim.game.game_time.get_current_time.side_effect = clock
    auto_aim.target_lock = TargetLock(
        game=auto_aim.game,
        parent=auto_aim.parent,
        lock_delay_s=target_lock_delay_s,
        cone_angle_deg=acquisition_cone_angle_deg,
    )
    auto_aim.min_assist_alignment = np.cos(np.deg2rad(max_assist_angle_deg))
    auto_aim.inv_max_assist_tan_angle = 1.0 / np.tan(np.deg2rad(max_assist_angle_deg))
    auto_aim.max_assist_distance_m = 1000.0
    return auto_aim


# ---------------------------------------------------------------------------
# compute_acquisition — delegated to the target lock
# ---------------------------------------------------------------------------


def test_compute_acquisition_locks_through_the_target_lock():
    """
    compute_acquisition() updates the target lock; is_target_acquired and
    acquisition_elapsed_time_s report its state (see test_target_lock.py for
    the lock's own behaviour).
    """
    auto_aim = make_auto_aim()
    auto_aim.target_lock = MagicMock(is_locked=True, elapsed_time_s=1.5)

    auto_aim.compute_acquisition()

    auto_aim.target_lock.update.assert_called_once()
    assert auto_aim.is_target_acquired
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# compute_shot_speed — no acquisition
# ---------------------------------------------------------------------------


def test_compute_shot_speed_without_acquisition_fires_forward():
    """
    When no target is acquired, the shot must travel in the parent's forward
    direction plus the parent's speed.
    """
    from space_flight.weapons.laser_cannon import LASER_SPEED_MPS

    auto_aim = make_auto_aim()  # starts unlocked (acquiring)
    forward = np.array([0.0, 1.0, 0.0])
    parent_speed = np.array([10.0, 0.0, 0.0])
    auto_aim.parent.forward = forward
    auto_aim.parent.speed = parent_speed

    start_position = np.zeros(3)
    shot_speed = auto_aim.compute_shot_speed(start_position)

    expected = LASER_SPEED_MPS * forward + parent_speed
    np.testing.assert_allclose(shot_speed, expected, atol=1e-6)


# ---------------------------------------------------------------------------
# configure — runtime retuning
# ---------------------------------------------------------------------------


def test_configure_recomputes_derived_thresholds():
    """
    configure() recomputes the cached alignment/assist thresholds from the given
    angles, so a targeting system can retune the assist quality at runtime.
    """
    auto_aim = make_auto_aim()

    auto_aim.configure(
        target_lock_delay_s=0.5,
        acquisition_cone_angle_deg=45.0,
        max_assist_angle_deg=10.0,
        max_assist_distance_m=1500.0,
    )

    assert auto_aim.target_lock.lock_delay_s == pytest.approx(0.5)
    assert auto_aim.max_assist_distance_m == pytest.approx(1500.0)
    assert auto_aim.target_lock.min_alignment == pytest.approx(np.cos(np.deg2rad(45.0)))
    assert auto_aim.min_assist_alignment == pytest.approx(np.cos(np.deg2rad(10.0)))
    assert auto_aim.inv_max_assist_tan_angle == pytest.approx(
        1.0 / np.tan(np.deg2rad(10.0))
    )


def test_configure_tighter_assist_raises_alignment_threshold():
    """
    A smaller assist angle (tighter aim) demands closer alignment before the
    shot is clamped, i.e. a higher min_assist_alignment.
    """
    auto_aim = make_auto_aim()

    auto_aim.configure(max_assist_angle_deg=3.0)
    tight = auto_aim.min_assist_alignment
    auto_aim.configure(max_assist_angle_deg=10.0)
    loose = auto_aim.min_assist_alignment

    assert tight > loose


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_clean_sets_game_to_none():
    """
    clean() must release the reference to the game object, and clean the
    target lock.
    """
    auto_aim = make_auto_aim()
    target_lock = auto_aim.target_lock

    auto_aim.clean()

    assert auto_aim.game is None
    assert target_lock.game is None


def test_clean_sets_ship_to_none():
    """
    clean() must release the 'ship' reference (the attribute written by
    clean(), not 'parent').
    """
    auto_aim = make_auto_aim()
    auto_aim.ship = MagicMock()

    auto_aim.clean()

    assert auto_aim.ship is None
