from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai.target_lock import TargetLock
from space_flight.utils import (
    low_pass_filter_first_order,
    magnitude,
    rotate_single_vector,
)
from space_flight.weapons.laser_cannon import LASER_SPEED_MPS

if TYPE_CHECKING:
    from space_flight.actors.capital_ship.turret import Turret
    from space_flight.actors.fighter import Fighter
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()

# Time constant of the low-pass filter on the lead offset (see update_lead):
# damps the velocity kicks of hits, which would make the lead jump around.
LEAD_SMOOTHING_TIME_S = 0.2


class AutoAim:
    """
    Auto-aim for laser cannons: shots go straight ahead, unless the parent's
    target is locked, in which case they are bent (within the assist cone)
    toward its predicted position.
    """

    def __init__(
        self,
        game: FlightState,
        parent: Fighter | Turret,
        target_lock_delay_s: float = 1.0,
        acquisition_cone_angle_deg: float = 30.0,
        max_assist_angle_deg: float = 5.0,
        max_assist_distance_m: float = 1000.0,
    ):
        self.game = game
        self.parent = parent
        # Shots lead the target once it is locked (see TargetLock)
        self.target_lock = TargetLock(game=self.game, parent=self.parent)
        # Smoothed lead offset on lead_target_id (see update_lead)
        self.lead_offset_m = None
        self.lead_target_id = None
        self.lead_update_time_s = None
        self.configure(
            target_lock_delay_s=target_lock_delay_s,
            acquisition_cone_angle_deg=acquisition_cone_angle_deg,
            max_assist_angle_deg=max_assist_angle_deg,
            max_assist_distance_m=max_assist_distance_m,
        )

    def configure(
        self,
        target_lock_delay_s: float = 1.0,
        acquisition_cone_angle_deg: float = 30.0,
        max_assist_angle_deg: float = 5.0,
        max_assist_distance_m: float = 1000.0,
    ):
        """
        Sets the auto-aim tuning parameters, recomputing the derived thresholds.

        Splitting this out of __init__ lets the assist quality be retuned at
        runtime: a turret reconfigures its auto-aim from the parameters of the
        targeting system currently boosting it, so a better targeting system
        yields a tighter firing solution.

        :param target_lock_delay_s: Time the target must stay in the acquisition
            cone before shots start leading it
        :param acquisition_cone_angle_deg: Half-angle of the cone within which a
            target can be acquired
        :param max_assist_angle_deg: Maximum angle a shot may be bent away from
            the barrel toward the predicted intercept (higher = tighter aim)
        :param max_assist_distance_m: Range beyond which the assist is meant not to
            apply (stored but currently unused: no range cut-off is applied)
        """
        self.target_lock.configure(
            lock_delay_s=target_lock_delay_s,
            cone_angle_deg=acquisition_cone_angle_deg,
        )
        self.min_assist_alignment = np.cos(np.deg2rad(max_assist_angle_deg))
        self.inv_max_assist_tan_angle = 1 / np.tan(np.deg2rad(max_assist_angle_deg))
        self.max_assist_distance_m = max_assist_distance_m

    def _target_kinematics(self) -> tuple[np.ndarray, np.ndarray] | None:
        """
        :return: The target's current position, and its raw lead offset: how far
            it moves, relative to the parent (bolts inherit the parent's
            velocity), during a bolt's time of flight. None if the parent or its
            target is not in the interactions.
        """
        try:
            my_actor_index = self.game.interactions.get_actor_index_from_id(
                self.parent.id
            )
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                self.parent.target_id
            )
        except ValueError:
            # Parent has died during this frame, or has no target
            return None

        # TODO Same pair lookup and target reconstruction as in
        #  FighterNavigator and TrackingMountNavigator: share one interactions helper
        #  returning the target's position and absolute velocity for an
        #  (actor, target) pair.
        distance_m = self.game.interactions.distances[
            my_actor_index, target_actor_index
        ]
        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed_vector = self.game.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]

        # Impact time is assumed to be the distance between target and self
        # divided by laser speed
        impact_time_s = distance_m / LASER_SPEED_MPS
        target_current_position = self.parent.position + distance_m * direction
        return target_current_position, relative_speed_vector * impact_time_s

    def update_lead(self):
        """
        Low-pass filter the lead offset, once per frame. Filtering the offset
        rather than the predicted position keeps the lead on the target.

        The filter restarts on a new target. Its time step is the time since its
        last update, so it catches up at once after a gap in updates (e.g. a
        turret's fire control offline).
        """
        kinematics = self._target_kinematics()
        if kinematics is None:
            self.lead_offset_m = None
            self.lead_target_id = None
            return
        _, raw_offset_m = kinematics
        now_s = self.game.game_time.get_current_time()
        if self.lead_target_id != self.parent.target_id:
            self.lead_offset_m = raw_offset_m
        else:
            self.lead_offset_m = low_pass_filter_first_order(
                value=raw_offset_m,
                previous=self.lead_offset_m,
                dt=now_s - self.lead_update_time_s,
                rise_time=LEAD_SMOOTHING_TIME_S,
                fall_time=LEAD_SMOOTHING_TIME_S,
            )
        self.lead_target_id = self.parent.target_id
        self.lead_update_time_s = now_s

    def predict_target_position(self) -> np.ndarray | None:
        """
        :return: Where a bolt fired now meets the parent's target: its current
            position plus the smoothed lead offset (the raw one until
            update_lead has run on it). None if the parent or its target is not
            in the interactions.
        """
        kinematics = self._target_kinematics()
        if kinematics is None:
            return None
        target_current_position, raw_offset_m = kinematics
        if self.lead_target_id == self.parent.target_id:
            return target_current_position + self.lead_offset_m
        return target_current_position + raw_offset_m

    def compute_shot_speed(self, start_position: np.ndarray) -> np.ndarray:
        """
        Computes the speed vector at which the next laser shot will be emitted

        TODO : Add random spread ? (Very small, subject to parent health ?)

        :param start_position: The starting point of the laser
        :return: The shot's world velocity (includes the parent's velocity)
        """
        if not self.is_target_acquired:
            # No acquisition: fire straight ahead
            shot_dir = self.parent.forward
        else:
            # Target locked: fire at its predicted position, if it still exists
            target_predicted_position = self.predict_target_position()
            if target_predicted_position is None:
                desired_shot_dir = self.parent.forward
            else:
                predicted_direction = target_predicted_position - start_position
                norm = magnitude(predicted_direction)
                if norm < 1e-4:
                    # Better safe than sorry
                    desired_shot_dir = self.parent.forward
                else:
                    desired_shot_dir = predicted_direction / norm

            # Constrain assist inside assist cone
            if (
                np.dot(desired_shot_dir, self.parent.forward)
                < self.min_assist_alignment
            ):
                # In parent coordinates, stretch the forward component so the
                # direction lies on the assist cone with the same lateral component,
                # normalise, and transform back to world coordinates
                quat = np.quaternion(*self.parent.orientation)
                desired_shot_dir_body = rotate_single_vector(
                    quat.conjugate(), desired_shot_dir
                )
                lateral_amplitude = np.sqrt(  # Remove forward (Y) component
                    desired_shot_dir_body[0] ** 2 + desired_shot_dir_body[2] ** 2
                )
                forward_component = lateral_amplitude * self.inv_max_assist_tan_angle
                clipped_dir_body = np.array(
                    [
                        desired_shot_dir_body[0],
                        forward_component,
                        desired_shot_dir_body[2],
                    ]
                )
                norm = magnitude(clipped_dir_body)
                if norm < 1e-4:
                    # Should not happen since the lateral component is significant,
                    # but better safe than sorry
                    shot_dir = self.parent.forward
                else:
                    clipped_dir_body /= norm
                    shot_dir = rotate_single_vector(quat, clipped_dir_body)
            else:
                shot_dir = desired_shot_dir

        # Non relativistic projectiles: they are emitted from a possibly moving gun
        shot_speed = LASER_SPEED_MPS * np.array(shot_dir) + self.parent.speed
        return shot_speed

    @property
    def is_target_acquired(self) -> bool:
        """Whether the target lock is confirmed (shots lead the target)."""
        return self.target_lock.is_locked

    @property
    def acquisition_elapsed_time_s(self) -> float:
        """How long the current target has been continuously held in the cone."""
        return self.target_lock.elapsed_time_s

    def compute_acquisition(self):
        """
        Updates the target lock and the smoothed lead
        """
        self.target_lock.update()
        self.update_lead()

    def clean(self):
        """
        Cleans the AutoAim object
        """
        self.target_lock.clean()
        self.game = None
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned auto-aim")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted auto-aim")
