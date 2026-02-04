import logging
from typing import List

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M
from space_flight.utils import rotate_single_vector

LOGGER = logging.getLogger()

ALIGNMENT_WEIGHT = 1.0
RELATIVE_VELOCITY_WEIGHT = 0.0
REFERENCE_DISTANCE_M = 500
REFERENCE_VELOCITY_MPS = 1000
SCORE_THRESHOLD_FOR_ACTION = 0.1
SHOOTING_MAX_DISTANCE = 500
SHOOTING_MIN_COS_ANGLE = 0.96


class AutoTactician:
    """
    TODO
    Finds the proper strategy for a bot:
    - Select the most valuable target (enemy to kill, friend to escort,
        patrol to do, should be scriptable ?)
    - Weigh the behaviour forces
    - The weights could depend on an aggressive/defensive/cowardly personnality
    - They may depend on the situation and/or a scenario
    """

    def __init__(
        self,
        app,
        ship,
        chase_weight: float = 1.0,
        evade_weight: float = 1.0,
        flee_weight: float = 0.0,
        patrol_weight: float = 0.2,
    ):
        self.app = app
        self.ship = ship
        self.chase_weight = chase_weight
        self.evade_weight = evade_weight
        self.flee_weight = flee_weight
        self.patrol_weight = patrol_weight

    def think(self) -> List[dict]:
        """
        Example of result

        behaviours = [
            {
                "action": "chase_target",
                "target": <a vulnerable enemy>, # Or a leader to follow
                "weight": 1,
            },
            {
                "action": "evade_target",
                "target": <a menacing enemy ship>,
                "weight": 5,
            },
            {
                "action": "flee_from_target",
                "target": <some asteroid that's too close>,
                "weight": 10,
            },
            {
                "action": "follow_waypoints", # Only one of those please
                "weight": 1,
            },
        ]

        Then:
        - The navigator uses the distance associated with the most weighted behaviour
        - The navigator makes a weighted average of all behaviour directions. If
            the average is null, return NO_DIRECTION

        TODO: For the flee problem, use a global array of all collidable objects ?
        Or use the collision system of panda3d ?
        Aaaaaaaaaaaaaaaaaaah, paniiiiiiic !!!

        TODO: closing velocity does not seem very interesting, retrospectively. Is it?

        TODO: Bots should chase for farther, and perhaps ignore the angle at
        long distance. ATM, when on the side, they don't see me...

        TODO: avoid friendly fire ?

        """
        my_thoughts = [
            {
                "action": "follow_waypoints",
                "weight": self.patrol_weight,
            },
        ]

        my_actor_index = self.app.interactions.get_actor_index(self.ship)
        directions = self.app.interactions.directions[my_actor_index, :, :]
        distances = self.app.interactions.distances[my_actor_index, :]
        # rel_velocities = self.app.interactions.rel_velocities[my_actor_index, :, :]

        # Find if actors are hostile
        # TODO: create an ad-hoc interaction matrix instead
        hostile_mask = distances > TARGET_DISTANCE_TOLERANCE_M

        # Find if actors are forward or behind
        ship_quat = np.quaternion(*self.ship.orientation)
        ship_forward = rotate_single_vector(ship_quat, np.array([0.0, 1.0, 0.0]))
        cos_alignments = np.dot(directions, ship_forward)
        projection_signs = np.sign(cos_alignments)
        forward_mask = projection_signs >= 0
        behind_mask = projection_signs < 0

        # Compute alignment score:
        # The more aligned and the closer the target the more interesting it is
        with np.errstate(divide="ignore", invalid="ignore"):
            alignment_score = cos_alignments / distances * REFERENCE_DISTANCE_M

        # Compute chasing behaviour
        chasing_scores = (
            hostile_mask
            * forward_mask
            * (
                alignment_score
                * ALIGNMENT_WEIGHT
                # + closing_velocity_score * RELATIVE_VELOCITY_WEIGHT
            )
        )

        try:
            chasing_idx = np.nanargmax(chasing_scores)
            if chasing_scores[chasing_idx] > SCORE_THRESHOLD_FOR_ACTION:
                my_thoughts.append(
                    {
                        "action": "chase_target",
                        "target": self.app.interactions.actors[chasing_idx],
                        "weight": self.chase_weight,
                    },
                )
                if (
                    distances[chasing_idx] < SHOOTING_MAX_DISTANCE
                    and cos_alignments[chasing_idx] > SHOOTING_MIN_COS_ANGLE
                ):
                    # Target is close enough for distance and angle. Let's shoot it !
                    self.ship.laser_cannon.fire()
        except ValueError:
            pass

        # Compute evading scores
        # TODO More threatening if the actor is pointing towards us,
        # not really if it's behind... It can be pre-computed for everyone
        evading_scores = (
            hostile_mask
            * behind_mask
            * (
                -alignment_score  # negative because they are behind
                * ALIGNMENT_WEIGHT
                # + closing_velocity_score * RELATIVE_VELOCITY_WEIGHT
            )
        )
        try:
            evading_idx = np.nanargmax(evading_scores)
            if evading_scores[evading_idx] > SCORE_THRESHOLD_FOR_ACTION:
                my_thoughts.append(
                    {
                        "action": "evade_target",
                        "target": self.app.interactions.actors[evading_idx],
                        "weight": self.chase_weight,
                    },
                )
        except ValueError:
            pass

        return my_thoughts

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")

    def placeholder_think(self):
        if self.ship.parent.name == "prey":
            my_thoughts = [
                {
                    "action": "evade_target",
                    "target": self.ship.app.player.ship,
                    "weight": 1,
                },
            ]
        elif self.ship.parent.name == "lead":
            my_thoughts = [
                {
                    "action": "follow_waypoints",
                    "weight": 1,
                },
            ]
        else:
            my_thoughts = [
                {
                    "action": "chase_target",
                    "target": self.ship.app.lead_bot.ship,
                    "weight": 1,
                },
            ]

        return my_thoughts
