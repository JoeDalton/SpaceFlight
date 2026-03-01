import logging

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.laser_cannon import LASER_SPEED_MPS

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
        max_assist_angle_deg: float = 10.0,
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
        self.max_assist_distance_m = max_assist_distance_m

    def compute_shot_speed(self, start_pos: np.ndarray):
        """
        Computes the speed vector at which the next laser shot will be emitted

        # TODO : Add random spread ? (Very small, subject to parent health ?)

        :param start_pos: The starting point of the laser
        """
        if not self.is_target_acquired:
            # No acquisition: fire straight ahead
            shot_dir = self.parent.forward
        else:
            # Target acquired: fire in its predicted prediction, constrained by the max
            # assist cone
            # TODO
            shot_dir = self.parent.forward

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
                if self.debug:
                    LOGGER.info(
                        f"Navigator {self.ship.parent.name}: "
                        "Target has been destroyed since last intent update."
                    )
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
