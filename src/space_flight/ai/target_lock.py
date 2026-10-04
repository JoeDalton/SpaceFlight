from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.utils.state_machine import StateMachine

if TYPE_CHECKING:
    from space_flight.actors.capital_ship.turret import Turret
    from space_flight.actors.fighter import Fighter
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()

# Target-lock states.
_ACQUIRING = "acquiring"  # holding the target in the cone, not yet locked
_LOCKED = "locked"  # held long enough


class TargetLock:
    """
    A lock on the parent's target: the target must stay inside a cone around
    the parent's nose for a delay before it locks. Any disturbance (no target,
    target changed or gone, target out of the cone) restarts the delay, so a
    lock requires *continuous* alignment.

    Used by the laser auto-aim (see :class:`~space_flight.ai.auto_aim.AutoAim`)
    and by missile launchers, each with its own tuning.
    """

    def __init__(
        self,
        game: FlightState,
        parent: Fighter | Turret,
        lock_delay_s: float = 1.0,
        cone_angle_deg: float = 30.0,
    ):
        self.game = game
        self.parent = parent
        self.previous_target_id = None
        # Target lock is a two-state machine: the target must stay in the cone for
        # lock_delay_s (time-in-state of "acquiring") before it "locks".
        self.lock_sm = StateMachine(
            initial_state=_ACQUIRING,
            clock=self.game.game_time.get_current_time,
        )
        self.configure(lock_delay_s=lock_delay_s, cone_angle_deg=cone_angle_deg)

    def configure(self, lock_delay_s: float = 1.0, cone_angle_deg: float = 30.0):
        """
        Sets the lock tuning parameters, recomputing the derived threshold.

        :param lock_delay_s: Time the target must stay in the cone before it locks
        :param cone_angle_deg: Half-angle of the cone the target must stay in
        """
        self.lock_delay_s = lock_delay_s
        self.min_alignment = np.cos(np.deg2rad(cone_angle_deg))

    @property
    def is_locked(self) -> bool:
        """Whether the target lock is confirmed."""
        return self.lock_sm.state == _LOCKED

    @property
    def elapsed_time_s(self) -> float:
        """How long the current target has been continuously held in the cone."""
        return self.lock_sm.time_in_state_s

    def _restart(self):
        """
        Drop any lock and restart the acquiring delay.
        """
        if self.lock_sm.state == _LOCKED:
            self.lock_sm.request(_ACQUIRING, force=True)
        else:
            self.lock_sm.reset_timer()

    def reset(self):
        """
        Drop any lock and forget the target, e.g. while the lock is not in use
        (a missile launcher that is not selected).
        """
        self.previous_target_id = None
        self._restart()

    def update(self):
        """
        Identifies the parent's target and determines whether it is locked
        """
        if not self.parent.target_id:
            # Parent has no target => Nothing to lock
            self.reset()
            return
        if self.parent.target_id != self.previous_target_id:
            # Target has changed since last frame => Not locked yet
            self.previous_target_id = self.parent.target_id
            self._restart()
            return

        # Target should exist and is the same as last time.
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.parent.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                self.parent.target_id
            )
        except ValueError:
            # Target gone => Nothing to lock
            self.reset()
            return

        # Is the target inside the cone ?
        alignment = self.game.interactions.alignments[
            my_actor_index, target_actor_index
        ]
        if alignment < self.min_alignment:
            # Not aligned enough => restart the delay
            self._restart()
            return

        # Aligned: lock once the target has been held in the cone long enough.
        if self.lock_sm.state != _LOCKED and self.elapsed_time_s >= self.lock_delay_s:
            self.lock_sm.request(_LOCKED, force=True)

    def clean(self):
        """
        Cleans the TargetLock object
        """
        self.game = None
        self.parent = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned target lock")
