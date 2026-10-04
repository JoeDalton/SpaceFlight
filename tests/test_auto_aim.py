"""
Unit tests for AutoAim (space_flight.ai.auto_aim).

AutoAim.__init__ requires a live game object; all tests bypass it with
object.__new__() and set only the attributes consumed by each method under
test.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai.auto_aim import LEAD_SMOOTHING_TIME_S, AutoAim
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
    enabled: bool = True,
) -> AutoAim:
    """
    Build an AutoAim that bypasses __init__ with sensible defaults.

    :param target_lock_delay_s: seconds before target lock is confirmed
    :param acquisition_cone_angle_deg: half-angle of the acquisition cone
    :param max_assist_angle_deg: half-angle of the assist cone
    :param enabled: whether shots lead a locked target
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
    auto_aim.enabled = enabled
    auto_aim.lead_offset_m = None
    auto_aim.lead_target_id = None
    auto_aim.lead_update_time_s = None
    return auto_aim


# ---------------------------------------------------------------------------
# compute_acquisition — delegated to the target lock
# ---------------------------------------------------------------------------


def test_compute_acquisition_locks_through_the_target_lock():
    """
    compute_acquisition() updates the target lock and the smoothed lead;
    is_target_acquired and acquisition_elapsed_time_s report the lock's state
    (see test_target_lock.py for the lock's own behaviour).
    """
    auto_aim = make_auto_aim()
    auto_aim.target_lock = MagicMock(is_locked=True, elapsed_time_s=1.5)
    auto_aim.update_lead = MagicMock()

    auto_aim.compute_acquisition()

    auto_aim.target_lock.update.assert_called_once()
    auto_aim.update_lead.assert_called_once()
    assert auto_aim.is_target_acquired
    assert auto_aim.acquisition_elapsed_time_s == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# compute_shot_direction — no acquisition
# ---------------------------------------------------------------------------


def test_compute_shot_direction_without_acquisition_fires_forward():
    """
    When no target is acquired, the shot goes in the parent's forward direction.
    """
    auto_aim = make_auto_aim()  # starts unlocked (acquiring)
    forward = np.array([0.0, 1.0, 0.0])
    auto_aim.parent.forward = forward

    shot_dir = auto_aim.compute_shot_direction(np.zeros(3))

    np.testing.assert_allclose(shot_dir, forward, atol=1e-6)


def test_compute_shot_direction_returns_a_copy_of_forward():
    """
    The direction can be modified (e.g. deviated in place) without touching the
    parent's forward vector.
    """
    auto_aim = make_auto_aim()
    forward = np.array([0.0, 1.0, 0.0])
    auto_aim.parent.forward = forward

    shot_dir = auto_aim.compute_shot_direction(np.zeros(3))
    shot_dir *= 2.0

    np.testing.assert_array_equal(forward, [0.0, 1.0, 0.0])


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
# update_lead — smoothed lead offset
# ---------------------------------------------------------------------------


def _set_rel_velocity(auto_aim: AutoAim, rel_velocity: np.ndarray):
    auto_aim.game.interactions.rel_velocities[0, 1, :] = rel_velocity


def make_leading_auto_aim(rel_velocity: np.ndarray) -> AutoAim:
    """
    An AutoAim whose parent sits at the origin, its target 1 km straight ahead
    with the given relative velocity, the clock at 0.
    """
    auto_aim = make_auto_aim()
    auto_aim.parent.position = np.zeros(3)
    auto_aim.parent.target_id = "target"
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=rel_velocity,
    )
    return auto_aim


# Time of flight to the target 1 km ahead
_TOF_S = 1000.0 / LASER_SPEED_MPS


def test_update_lead_starts_from_the_raw_offset():
    """The first update on a target takes its raw lead offset as is."""
    auto_aim = make_leading_auto_aim(np.array([50.0, 0.0, 0.0]))

    auto_aim.update_lead()

    np.testing.assert_allclose(auto_aim.lead_offset_m, [50.0 * _TOF_S, 0.0, 0.0])
    assert auto_aim.lead_target_id == "target"


def test_update_lead_damps_a_velocity_kick():
    """
    A sudden velocity change (e.g. a hit) moves the lead offset only part of
    the way (first-order low-pass with LEAD_SMOOTHING_TIME_S), the predicted
    position following the smoothed offset.
    """
    auto_aim = make_leading_auto_aim(np.zeros(3))
    auto_aim.update_lead()

    _set_rel_velocity(auto_aim, np.array([100.0, 0.0, 0.0]))
    dt = 0.02
    auto_aim._clock.t = dt
    auto_aim.update_lead()

    alpha = dt / (LEAD_SMOOTHING_TIME_S + dt)
    expected_offset = alpha * 100.0 * _TOF_S
    assert auto_aim.lead_offset_m[0] == pytest.approx(expected_offset)
    np.testing.assert_allclose(
        auto_aim.predict_target_position(), [expected_offset, 1000.0, 0.0]
    )


def test_update_lead_converges_to_a_steady_velocity():
    """Held long enough, the smoothed lead reaches the raw one."""
    auto_aim = make_leading_auto_aim(np.zeros(3))
    auto_aim.update_lead()
    _set_rel_velocity(auto_aim, np.array([100.0, 0.0, 0.0]))

    for frame in range(1, 121):  # 2 s at 60 fps, 10 time constants
        auto_aim._clock.t = frame / 60.0
        auto_aim.update_lead()

    assert auto_aim.lead_offset_m[0] == pytest.approx(100.0 * _TOF_S, rel=1e-3)


def test_update_lead_restarts_on_a_new_target():
    """A new target's lead starts from its own raw offset, not the old one's."""
    auto_aim = make_leading_auto_aim(np.zeros(3))
    auto_aim.update_lead()

    auto_aim.parent.target_id = "other target"
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.array([0.0, 0.0, 80.0]),
    )
    auto_aim._clock.t = 0.02
    auto_aim.update_lead()

    np.testing.assert_allclose(auto_aim.lead_offset_m, [0.0, 0.0, 80.0 * _TOF_S])
    assert auto_aim.lead_target_id == "other target"


def test_update_lead_catches_up_after_a_gap_in_updates():
    """
    After a long gap in updates (e.g. a turret's fire control offline), the
    lead nearly catches up at once instead of sliding from a stale offset.
    """
    auto_aim = make_leading_auto_aim(np.zeros(3))
    auto_aim.update_lead()

    _set_rel_velocity(auto_aim, np.array([100.0, 0.0, 0.0]))
    auto_aim._clock.t = 20.0
    auto_aim.update_lead()

    assert auto_aim.lead_offset_m[0] == pytest.approx(100.0 * _TOF_S, rel=0.02)


def test_update_lead_forgets_a_vanished_target():
    """Without a target in the interactions, the filter is cleared."""
    auto_aim = make_leading_auto_aim(np.array([50.0, 0.0, 0.0]))
    auto_aim.update_lead()

    _set_up_interactions_for_prediction(  # the target has left the interactions
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.zeros(3),
        known_ids=("parent",),
    )
    auto_aim.update_lead()

    assert auto_aim.lead_offset_m is None
    assert auto_aim.lead_target_id is None


# ---------------------------------------------------------------------------
# compute_shot_direction — locked
# ---------------------------------------------------------------------------


def test_compute_shot_direction_locked_fires_at_the_predicted_position():
    """
    Once locked, a shot inside the assist cone goes straight at the predicted
    position.
    """
    auto_aim = make_auto_aim(max_assist_angle_deg=45.0)
    auto_aim.target_lock = MagicMock(is_locked=True)
    parent_position = np.array([100.0, 0.0, 0.0])
    auto_aim.parent.position = parent_position
    auto_aim.parent.forward = np.array([0.0, 1.0, 0.0])
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=np.array([0.0, 1.0, 0.0]),
        rel_velocity=np.array([50.0, 0.0, 0.0]),
    )

    shot_dir = auto_aim.compute_shot_direction(parent_position)

    aim = auto_aim.predict_target_position() - parent_position
    np.testing.assert_allclose(shot_dir, aim / np.linalg.norm(aim), atol=1e-6)


def test_compute_shot_direction_locked_on_a_vanished_target_fires_forward():
    """
    A lock whose target has just left the interactions fires straight ahead.
    """
    auto_aim = make_auto_aim()
    auto_aim.target_lock = MagicMock(is_locked=True)
    forward = np.array([0.0, 1.0, 0.0])
    auto_aim.parent.forward = forward
    _set_up_interactions_for_prediction(
        auto_aim,
        distance_m=1000.0,
        direction=forward,
        rel_velocity=np.zeros(3),
        known_ids=("parent",),
    )

    shot_dir = auto_aim.compute_shot_direction(np.zeros(3))

    np.testing.assert_allclose(shot_dir, forward, atol=1e-6)


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


def test_configure_sets_enabled():
    """configure() stores the enabled flag, on unless told otherwise."""
    auto_aim = make_auto_aim()

    auto_aim.configure(enabled=False)
    assert auto_aim.enabled is False

    auto_aim.configure()
    assert auto_aim.enabled is True


# ---------------------------------------------------------------------------
# enabled — auto-aim switched off
# ---------------------------------------------------------------------------


def test_disabled_auto_aim_never_reports_a_lock():
    """
    Even if the target lock were confirmed, a disabled auto-aim reports no lock
    (so the crosshair never shows one).
    """
    auto_aim = make_auto_aim(enabled=False)
    auto_aim.target_lock = MagicMock(is_locked=True)

    assert not auto_aim.is_target_acquired


def test_disabled_auto_aim_skips_the_lock_but_updates_the_lead():
    """
    A disabled auto-aim does not run the target lock, but still smooths the lead
    the lead indicator shows.
    """
    auto_aim = make_auto_aim(enabled=False)
    auto_aim.target_lock = MagicMock(is_locked=False)
    auto_aim.update_lead = MagicMock()

    auto_aim.compute_acquisition()

    auto_aim.target_lock.update.assert_not_called()
    auto_aim.update_lead.assert_called_once()


def test_disabled_auto_aim_fires_forward_even_when_locked():
    """A disabled auto-aim never bends shots toward the target."""
    auto_aim = make_auto_aim(enabled=False)
    auto_aim.target_lock = MagicMock(is_locked=True)
    auto_aim.predict_target_position = MagicMock(
        return_value=np.array([10.0, 1000.0, 0.0])
    )
    forward = np.array([0.0, 1.0, 0.0])
    auto_aim.parent.forward = forward

    shot_dir = auto_aim.compute_shot_direction(np.zeros(3))

    np.testing.assert_allclose(shot_dir, forward, atol=1e-6)
    auto_aim.predict_target_position.assert_not_called()


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
