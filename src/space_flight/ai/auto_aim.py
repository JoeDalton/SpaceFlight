import logging

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.laser_cannon import LASER_SPEED_MPS
from space_flight.utils import rotate_single_vector

LOGGER = logging.getLogger()


class AutoAim:
    """
    A class for the autoaim of laser cannons

    If the parent does not have a target, the shot direction is straight ahead.
    If the parent has a target and target lock is acquired, turn laser towards the
    target's predicted position
    """

    def __init__(
        self,
        game,
        parent,
        target_lock_delay_s: float = 1.0,
        acquisition_cone_angle_deg: float = 30.0,
        max_assist_angle_deg: float = 5,
        max_assist_distance_m: float = 1000.0,
    ):
        self.game = game
        self.parent = parent
        self.previous_target_id = None
        self.is_target_acquired = False
        self.target_lock_delay_s = target_lock_delay_s
        self.acquisition_elapsed_time_s = 0.0
        self.min_acquisition_alignment = np.cos(np.deg2rad(acquisition_cone_angle_deg))
        self.min_assist_alignment = np.cos(np.deg2rad(max_assist_angle_deg))
        self.inv_max_assist_tan_angle = 1 / np.tan(np.deg2rad(max_assist_angle_deg))
        self.max_assist_distance_m = max_assist_distance_m

    def compute_shot_speed(self, start_position: np.ndarray):
        """
        Computes the speed vector at which the next laser shot will be emitted

        # TODO : Add random spread ? (Very small, subject to parent health ?)

        :param start_position: The starting point of the laser
        """
        if not self.is_target_acquired:
            # No acquisition: fire straight ahead
            shot_dir = self.parent.forward
        else:
            # Identify self and target in interactions
            my_actor_index = self.game.interactions.get_actor_index_from_id(
                self.parent.id
            )
            try:
                target_actor_index = self.game.interactions.get_actor_index_from_id(
                    self.parent.target_id
                )
                target_found = True
            except ValueError:
                # Parent has no target => Nothing to assist to
                desired_shot_dir = self.parent.forward
                target_found = False

            if target_found:
                # Target acquired and exists: fire in its predicted prediction

                # Get necessary info from interactions and pre compute target properties
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
                norm = np.linalg.norm(predicted_direction)
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
                # Transform the desired shot direction in parent coordinates and
                # Prolong the "forward" component so the final direction lies on
                # the assist cone, with the same lateral component.
                # Then make it unit length, then transform it back in world coordinates
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
                norm = np.linalg.norm(clipped_dir_body)
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

    def compute_acquisition(self):
        """
        Identifies the ship's target and determines whether it has been acquired
        """
        if not self.parent.target_id:
            # Parent has no target => Nothing to acquire
            self.previous_target_id = None
            self.acquisition_elapsed_time_s = 0.0
            self.is_target_acquired = False
            return
        elif self.parent.target_id != self.previous_target_id:
            # Target has changed since last frame => Not acquired yet
            self.previous_target_id = self.parent.target_id
            self.acquisition_elapsed_time_s = 0.0
            self.is_target_acquired = False
            return
        else:
            # Target should exist and is the same as last time

            # Identify self and target in interactions
            my_actor_index = self.game.interactions.get_actor_index_from_id(
                self.parent.id
            )
            try:
                target_actor_index = self.game.interactions.get_actor_index_from_id(
                    self.parent.target_id
                )
            except ValueError:
                # Parent has no target => Nothing to acquire
                self.previous_target_id = None
                self.acquisition_elapsed_time_s = 0.0
                self.is_target_acquired = False
                return

            # Is the target inside the cone of acquisition ?
            target_direction = self.game.interactions.directions[
                my_actor_index, target_actor_index, :
            ]
            alignment = np.dot(target_direction, self.parent.forward)
            if alignment < self.min_acquisition_alignment:
                # Not aligned enough for acquisition => Not acquired yet
                # + Reset acqusition delay
                self.acquisition_elapsed_time_s = 0.0
                self.is_target_acquired = False
                return
            # Is the target in the acquisition time for long enough ?
            self.acquisition_elapsed_time_s += self.game.game_time.get_time_step()
            if self.acquisition_elapsed_time_s < self.target_lock_delay_s:
                # Not acquired yet, but getting there !
                self.is_target_acquired = False
                return
            else:
                # Alignement and elapsed time are satisfactory => target lock !
                self.is_target_acquired = True

    def clean(self):
        """
        Cleans the AutoAim object
        """
        self.game = None
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned auto-aim")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted auto-aim")
