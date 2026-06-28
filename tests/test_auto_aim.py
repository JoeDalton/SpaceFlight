"""
Unit tests for AutoAim (space_flight.ai.auto_aim).

AutoAim.__init__ requires a live game object; all tests bypass it with
object.__new__() and set only the attributes consumed by each method under
test.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai.auto_aim import AutoAim


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
    auto_aim.previous_target_id = None
    auto_aim.is_target_acquired = False
    auto_aim.target_lock_delay_s = target_lock_delay_s
    auto_aim.acquisition_elapsed_time_s = 0.0
    auto_aim.min_acquisition_alignment = np.cos(np.deg2rad(acquisition_cone_angle_deg))
    auto_aim.min_assist_alignment = np.cos(np.deg2rad(max_assist_angle_deg))
    auto_aim.inv_max_assist_tan_angle = 1.0 / np.tan(np.deg2rad(max_assist_angle_deg))
    auto_aim.max_assist_distance_m = 1000.0
    return auto_aim


def _set_up_interactions_for_acquisition(
    auto_aim: AutoAim,
    target_direction: np.ndarray,
    self_index: int = 0,
    target_index: int = 1,
):
    """
    Configure the mocked interactions so that compute_acquisition can look up
    the direction from self to target.

    :param auto_aim: the AutoAim instance under test
    :param target_direction: unit direction vector from self to target
    :param self_index: slot index assigned to the parent actor
    :param target_index: slot index assigned to the target actor
    """
    directions = np.zeros((4, 4, 3))
    directions[self_index, target_index, :] = target_direction

    def mock_get_index(actor_id):
        if actor_id == auto_aim.parent.id:
            return self_index
        if actor_id == auto_aim.parent.target_id:
            return target_index
        raise ValueError(f"Unknown actor_id: {actor_id}")

    auto_aim.game.interactions.get_actor_index_from_id.side_effect = mock_get_index
    auto_aim.game.interactions.directions = directions


# ---------------------------------------------------------------------------
# compute_acquisition — no target
# ---------------------------------------------------------------------------


def test_compute_acquisition_no_target_id_stays_unacquired():
    """
    When the parent has no target (target_id is falsy), compute_acquisition
    must set is_target_acquired to False and clear previous_target_id.
    """
    auto_aim = make_auto_aim()
    auto_aim.parent.target_id = None

    auto_aim.compute_acquisition()

    assert not auto_aim.is_target_acquired
    assert auto_aim.previous_target_id is None
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(0.0)


def test_compute_acquisition_no_target_resets_elapsed_time():
    """
    A previously-accumulating elapsed time is reset when the parent loses its
    target.
    """
    auto_aim = make_auto_aim()
    auto_aim.acquisition_elapsed_time_s = 0.8
    auto_aim.parent.target_id = None

    auto_aim.compute_acquisition()

    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_acquisition — target changed
# ---------------------------------------------------------------------------


def test_compute_acquisition_new_target_resets_elapsed_time():
    """
    When the parent acquires a new target (different from the previous one),
    the elapsed acquisition time is reset to zero.
    """
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    auto_aim = make_auto_aim()
    auto_aim.previous_target_id = old_id
    auto_aim.parent.target_id = new_id
    auto_aim.acquisition_elapsed_time_s = 0.9

    auto_aim.compute_acquisition()

    assert not auto_aim.is_target_acquired
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(0.0)
    assert auto_aim.previous_target_id == new_id


def test_compute_acquisition_new_target_updates_previous_target_id():
    """
    After a target change, previous_target_id must be updated to the new
    target id so the next call recognises it as the same target.
    """
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    auto_aim = make_auto_aim()
    auto_aim.previous_target_id = old_id
    auto_aim.parent.target_id = new_id

    auto_aim.compute_acquisition()

    assert auto_aim.previous_target_id == new_id


# ---------------------------------------------------------------------------
# compute_acquisition — same target, inside cone
# ---------------------------------------------------------------------------


def test_compute_acquisition_target_in_cone_not_yet_acquired_after_short_time():
    """
    When the target is inside the cone but the elapsed time is less than the
    lock delay, the target must not be acquired.
    """
    target_id = uuid.uuid4()
    auto_aim = make_auto_aim(target_lock_delay_s=2.0)
    auto_aim.parent.target_id = target_id
    auto_aim.previous_target_id = target_id
    auto_aim.parent.forward = np.array([0.0, 1.0, 0.0])
    auto_aim.game.game_time.get_time_step.return_value = 0.5

    _set_up_interactions_for_acquisition(
        auto_aim, target_direction=np.array([0.0, 1.0, 0.0])
    )

    auto_aim.compute_acquisition()

    assert not auto_aim.is_target_acquired
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(0.5)


def test_compute_acquisition_target_in_cone_acquired_after_sufficient_time():
    """
    When the target is inside the cone and the elapsed time reaches the lock
    delay, is_target_acquired becomes True.
    """
    target_id = uuid.uuid4()
    auto_aim = make_auto_aim(target_lock_delay_s=1.0)
    auto_aim.parent.target_id = target_id
    auto_aim.previous_target_id = target_id
    auto_aim.acquisition_elapsed_time_s = 0.8
    auto_aim.parent.forward = np.array([0.0, 1.0, 0.0])
    auto_aim.game.game_time.get_time_step.return_value = 0.5

    _set_up_interactions_for_acquisition(
        auto_aim, target_direction=np.array([0.0, 1.0, 0.0])
    )

    auto_aim.compute_acquisition()

    assert auto_aim.is_target_acquired


# ---------------------------------------------------------------------------
# compute_acquisition — same target, outside cone
# ---------------------------------------------------------------------------


def test_compute_acquisition_target_outside_cone_resets_elapsed_time():
    """
    When the target is outside the acquisition cone, elapsed time resets to
    zero and the target is not acquired.
    """
    target_id = uuid.uuid4()
    auto_aim = make_auto_aim(acquisition_cone_angle_deg=5.0)
    auto_aim.parent.target_id = target_id
    auto_aim.previous_target_id = target_id
    auto_aim.acquisition_elapsed_time_s = 0.9
    # Target is 90° to the side — well outside a 5° cone
    auto_aim.parent.forward = np.array([0.0, 1.0, 0.0])
    auto_aim.game.game_time.get_time_step.return_value = 0.1

    _set_up_interactions_for_acquisition(
        auto_aim, target_direction=np.array([1.0, 0.0, 0.0])
    )

    auto_aim.compute_acquisition()

    assert not auto_aim.is_target_acquired
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_shot_speed — no acquisition
# ---------------------------------------------------------------------------


def test_compute_shot_speed_without_acquisition_fires_forward():
    """
    When no target is acquired, the shot must travel in the parent's forward
    direction plus the parent's speed.
    """
    from space_flight.actors.laser_cannon import LASER_SPEED_MPS

    auto_aim = make_auto_aim()
    auto_aim.is_target_acquired = False
    forward = np.array([0.0, 1.0, 0.0])
    parent_speed = np.array([10.0, 0.0, 0.0])
    auto_aim.parent.forward = forward
    auto_aim.parent.speed = parent_speed

    start_position = np.zeros(3)
    shot_speed = auto_aim.compute_shot_speed(start_position)

    expected = LASER_SPEED_MPS * forward + parent_speed
    np.testing.assert_allclose(shot_speed, expected, atol=1e-6)


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_clean_sets_game_to_none():
    """
    clean() must release the reference to the game object.
    """
    auto_aim = make_auto_aim()

    auto_aim.clean()

    assert auto_aim.game is None


def test_clean_sets_ship_to_none():
    """
    clean() must release the 'ship' reference (the attribute written by
    clean(), not 'parent').
    """
    auto_aim = make_auto_aim()
    auto_aim.ship = MagicMock()

    auto_aim.clean()

    assert auto_aim.ship is None
