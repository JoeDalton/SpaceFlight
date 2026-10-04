"""
Unit tests for TargetLock (space_flight.ai.target_lock): the cone-and-delay
lock shared by the laser auto-aim and the missile launchers.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai.target_lock import TargetLock


class _Clock:
    """A controllable time source for the lock state machine."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_target_lock(
    lock_delay_s: float = 1.0, cone_angle_deg: float = 30.0
) -> TargetLock:
    """
    Build a TargetLock on a mocked game and parent, driven by a controllable
    clock (exposed as ``_clock``).

    :param lock_delay_s: seconds before the lock is confirmed
    :param cone_angle_deg: half-angle of the lock cone
    :return: a TargetLock whose methods can be tested in isolation
    """
    clock = _Clock()
    game = MagicMock()
    game.game_time.get_current_time.side_effect = clock
    target_lock = TargetLock(
        game=game,
        parent=MagicMock(),
        lock_delay_s=lock_delay_s,
        cone_angle_deg=cone_angle_deg,
    )
    target_lock._clock = clock
    return target_lock


def _set_up_interactions(
    target_lock: TargetLock,
    alignment: float,
    self_index: int = 0,
    target_index: int = 1,
):
    """
    Configure the mocked interactions so that update can look up the
    alignment of the target with the parent's nose.

    :param target_lock: the TargetLock instance under test
    :param alignment: cosine of the angle between the parent's nose and the
        direction to the target
    :param self_index: slot index assigned to the parent actor
    :param target_index: slot index assigned to the target actor
    """
    alignments = np.zeros((4, 4))
    alignments[self_index, target_index] = alignment

    def mock_get_index(actor_id):
        if actor_id == target_lock.parent.id:
            return self_index
        if actor_id == target_lock.parent.target_id:
            return target_index
        raise ValueError(f"Unknown actor_id: {actor_id}")

    target_lock.game.interactions.get_actor_index_from_id.side_effect = mock_get_index
    target_lock.game.interactions.alignments = alignments


# ---------------------------------------------------------------------------
# update — no target
# ---------------------------------------------------------------------------


def test_update_no_target_id_stays_unlocked():
    """
    When the parent has no target (target_id is falsy), update
    must set is_locked to False and clear previous_target_id.
    """
    target_lock = make_target_lock()
    target_lock.parent.target_id = None

    target_lock.update()

    assert not target_lock.is_locked
    assert target_lock.previous_target_id is None
    assert target_lock.elapsed_time_s == pytest.approx(0.0)


def test_update_no_target_resets_elapsed_time():
    """
    A previously-accumulating elapsed time is reset when the parent loses its
    target.
    """
    target_lock = make_target_lock()
    target_lock._clock.t = 0.8  # some acquisition progress
    target_lock.parent.target_id = None

    target_lock.update()

    assert target_lock.elapsed_time_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# update — target changed
# ---------------------------------------------------------------------------


def test_update_new_target_resets_elapsed_time():
    """
    When the parent acquires a new target (different from the previous one),
    the elapsed lock time is reset to zero.
    """
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    target_lock = make_target_lock()
    target_lock.previous_target_id = old_id
    target_lock.parent.target_id = new_id
    target_lock._clock.t = 0.9  # some progress on the old target

    target_lock.update()

    assert not target_lock.is_locked
    assert target_lock.elapsed_time_s == pytest.approx(0.0)
    assert target_lock.previous_target_id == new_id


def test_update_new_target_updates_previous_target_id():
    """
    After a target change, previous_target_id must be updated to the new
    target id so the next call recognises it as the same target.
    """
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()
    target_lock = make_target_lock()
    target_lock.previous_target_id = old_id
    target_lock.parent.target_id = new_id

    target_lock.update()

    assert target_lock.previous_target_id == new_id


# ---------------------------------------------------------------------------
# update — same target, inside cone
# ---------------------------------------------------------------------------


def test_update_target_in_cone_not_yet_locked_after_short_time():
    """
    When the target is inside the cone but the elapsed time is less than the
    lock delay, the target must not be locked.
    """
    target_id = uuid.uuid4()
    target_lock = make_target_lock(lock_delay_s=2.0)
    target_lock.parent.target_id = target_id
    target_lock.previous_target_id = target_id
    target_lock._clock.t = 0.5  # held for 0.5s, below the 2.0s lock delay

    _set_up_interactions(target_lock, alignment=1.0)

    target_lock.update()

    assert not target_lock.is_locked
    assert target_lock.elapsed_time_s == pytest.approx(0.5)


def test_update_target_in_cone_locked_after_sufficient_time():
    """
    When the target is inside the cone and the elapsed time reaches the lock
    delay, is_locked becomes True.
    """
    target_id = uuid.uuid4()
    target_lock = make_target_lock(lock_delay_s=1.0)
    target_lock.parent.target_id = target_id
    target_lock.previous_target_id = target_id
    target_lock._clock.t = 1.3  # held past the 1.0s lock delay

    _set_up_interactions(target_lock, alignment=1.0)

    target_lock.update()

    assert target_lock.is_locked


# ---------------------------------------------------------------------------
# update — same target, outside cone
# ---------------------------------------------------------------------------


def test_update_target_outside_cone_resets_elapsed_time():
    """
    When the target is outside the cone, elapsed time resets to
    zero and the target is not locked.
    """
    target_id = uuid.uuid4()
    target_lock = make_target_lock(cone_angle_deg=5.0)
    target_lock.parent.target_id = target_id
    target_lock.previous_target_id = target_id
    target_lock._clock.t = 0.9  # some progress before it drifts out of the cone

    _set_up_interactions(
        target_lock,
        alignment=0.0,  # 90° to the side, well outside a 5° cone
    )

    target_lock.update()

    assert not target_lock.is_locked
    assert target_lock.elapsed_time_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_drops_the_lock_and_forgets_the_target():
    """
    reset() drops a confirmed lock and forgets the target, so the next update
    sees it as a new target and restarts the delay.
    """
    target_id = uuid.uuid4()
    target_lock = make_target_lock(lock_delay_s=1.0)
    target_lock.parent.target_id = target_id
    target_lock.previous_target_id = target_id
    _set_up_interactions(target_lock, alignment=1.0)
    target_lock._clock.t = 1.3
    target_lock.update()
    assert target_lock.is_locked

    target_lock.reset()

    assert not target_lock.is_locked
    assert target_lock.previous_target_id is None
    assert target_lock.elapsed_time_s == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# configure / clean
# ---------------------------------------------------------------------------


def test_configure_recomputes_the_cone_threshold():
    """configure() stores the delay and recomputes the cone's cosine."""
    target_lock = make_target_lock()

    target_lock.configure(lock_delay_s=0.5, cone_angle_deg=45.0)

    assert target_lock.lock_delay_s == pytest.approx(0.5)
    assert target_lock.min_alignment == pytest.approx(np.cos(np.deg2rad(45.0)))


def test_clean_releases_game_and_parent():
    """clean() releases the references to the game and the parent."""
    target_lock = make_target_lock()

    target_lock.clean()

    assert target_lock.game is None
    assert target_lock.parent is None
