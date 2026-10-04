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
from space_flight.weapons.laser_cannon import LASER_SPEED_MPS


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
    auto_aim = make_auto_aim()  # starts unlocked (acquiring)
    forward = np.array([0.0, 1.0, 0.0])
    parent_speed = np.array([10.0, 0.0, 0.0])
    auto_aim.parent.forward = forward
    auto_aim.parent.speed = parent_speed

    start_position = np.zeros(3)
    shot_speed = auto_aim.compute_shot_speed(start_position)

    expected = LASER_SPEED_MPS * forward + parent_speed
    np.testing.assert_allclose(shot_speed, expected, atol=1e-6)


def _set_up_interactions_for_prediction(
    auto_aim: AutoAim,
    distance_m: float,
    direction: np.ndarray,
    rel_velocity: np.ndarray,
    known_ids: tuple = ("parent", "target"),
):
    """
    Configure the mocked interactions so that predict_target_position can look
    up the parent-to-target distance, direction and relative velocity.

    :param auto_aim: the AutoAim instance under test
    :param distance_m: distance from the parent to its target
    :param direction: unit direction from the parent to its target
    :param rel_velocity: the target's velocity relative to the parent
    :param known_ids: which of "parent" / "target" the interactions know of
    """
    interactions = auto_aim.game.interactions
    interactions.distances = np.zeros((2, 2))
    interactions.directions = np.zeros((2, 2, 3))
    interactions.rel_velocities = np.zeros((2, 2, 3))
    interactions.distances[0, 1] = distance_m
    interactions.directions[0, 1, :] = direction
    interactions.rel_velocities[0, 1, :] = rel_velocity

    def mock_get_index(actor_id):
        if "parent" in known_ids and actor_id == auto_aim.parent.id:
            return 0
        if "target" in known_ids and actor_id == auto_aim.parent.target_id:
            return 1
        raise ValueError(f"Unknown actor_id: {actor_id}")

    interactions.get_actor_index_from_id.side_effect = mock_get_index


# ---------------------------------------------------------------------------
# predict_target_position
# ---------------------------------------------------------------------------


def test_predict_target_position_leads_by_relative_velocity_over_time_of_flight():
    """
    The target is moved by its velocity relative to the parent (bolts inherit
    the parent's velocity) over the laser's time of flight. The parent's own
    velocity must not leak into the prediction.
    """
    auto_aim = make_auto_aim()
    auto_aim.parent.position = np.array([100.0, 0.0, 0.0])
    auto_aim.parent.speed = np.array([0.0, 200.0, 0.0])
    distance_m = 1000.0
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=distance_m,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.array([50.0, 0.0, 0.0]),
    )

    predicted = auto_aim.predict_target_position()

    time_of_flight_s = distance_m / LASER_SPEED_MPS
    expected = np.array([100.0 + 50.0 * time_of_flight_s, 1000.0, 0.0])
    np.testing.assert_allclose(predicted, expected, atol=1e-9)


@pytest.mark.parametrize("known_ids", [("parent",), ("target",)])
def test_predict_target_position_is_none_when_an_actor_is_missing(known_ids):
    """
    No prediction when the parent (died this frame) or its target (none, or
    gone) is not in the interactions.
    """
    auto_aim = make_auto_aim()
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.zeros(3),
        known_ids=known_ids,
    )

    assert auto_aim.predict_target_position() is None


# ---------------------------------------------------------------------------
# compute_shot_speed — locked
# ---------------------------------------------------------------------------


def test_compute_shot_speed_locked_fires_at_the_predicted_position():
    """
    Once locked, a shot inside the assist cone goes straight at the predicted
    position, plus the parent's velocity.
    """
    auto_aim = make_auto_aim(max_assist_angle_deg=45.0)
    auto_aim.target_lock = MagicMock(is_locked=True)
    parent_position = np.array([100.0, 0.0, 0.0])
    parent_speed = np.array([0.0, 200.0, 0.0])
    auto_aim.parent.position = parent_position
    auto_aim.parent.speed = parent_speed
    auto_aim.parent.forward = np.array([0.0, 1.0, 0.0])
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.array([50.0, 0.0, 0.0]),
    )

    shot_speed = auto_aim.compute_shot_speed(parent_position)

    aim = auto_aim.predict_target_position() - parent_position
    expected = LASER_SPEED_MPS * aim / np.linalg.norm(aim) + parent_speed
    np.testing.assert_allclose(shot_speed, expected, atol=1e-6)


def test_compute_shot_speed_locked_on_a_vanished_target_fires_forward():
    """
    A lock whose target has just left the interactions fires straight ahead.
    """
    auto_aim = make_auto_aim()
    auto_aim.target_lock = MagicMock(is_locked=True)
    forward = np.array([0.0, 1.0, 0.0])
    parent_speed = np.array([10.0, 0.0, 0.0])
    auto_aim.parent.forward = forward
    auto_aim.parent.speed = parent_speed
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=forward,
        rel_velocity=np.zeros(3),
        known_ids=("parent",),
    )

    shot_speed = auto_aim.compute_shot_speed(np.zeros(3))

    np.testing.assert_allclose(
        shot_speed, LASER_SPEED_MPS * forward + parent_speed, atol=1e-6
    )


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
