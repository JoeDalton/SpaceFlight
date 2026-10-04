from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai.target_lock import TargetLock
from space_flight.utils import magnitude, rotate_single_vector
from space_flight.weapons.laser_cannon import LASER_SPEED_MPS

if TYPE_CHECKING:
    from space_flight.actors.capital_ship.turret import Turret
    from space_flight.actors.fighter import Fighter
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


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
            # Identify self and target in interactions
            try:
                my_actor_index = self.game.interactions.get_actor_index_from_id(
                    self.parent.id
                )
                parent_found = True
            except ValueError:
                # Parent has died during this frame, do nothing
                parent_found = False
            try:
                target_actor_index = self.game.interactions.get_actor_index_from_id(
                    self.parent.target_id
                )
                target_found = True
            except ValueError:
                # Parent has no target => Nothing to assist to
                desired_shot_dir = self.parent.forward
                target_found = False

            if target_found and parent_found:
                # Target acquired and exists: fire at its predicted position
                distance_m = self.game.interactions.distances[
                    my_actor_index, target_actor_index
                ]
                direction = self.game.interactions.directions[
                    my_actor_index, target_actor_index, :
                ]
                relative_speed_vector = self.game.interactions.rel_velocities[
                    my_actor_index, target_actor_index, :
                ]

                # Compute lead pursuit direction necessary for firing solution
                target_current_position = self.parent.position + distance_m * direction
                target_current_speed = self.parent.speed + relative_speed_vector

                # Impact time is assumed to be the distance between target and self
                # divided by laser speed
                impact_time_s = distance_m / LASER_SPEED_MPS

                # Predict target position at impact time
                target_predicted_position = (
                    target_current_position + target_current_speed * impact_time_s
                )

                # Find predicted target direction
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
        Identifies the ship's target and determines whether it has been acquired
        """
        self.target_lock.update()

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
