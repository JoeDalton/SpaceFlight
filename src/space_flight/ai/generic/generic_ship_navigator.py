import logging
from typing import List, Tuple

import numpy as np

from space_flight import EPSILON_TOLERANCE, RECORD_GAME
from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M
from space_flight.ai.collision_sensor import CollisionSensor
from space_flight.ai.generic.generic_navigator import GenericNavigator
from space_flight.utils import smooth_step_down

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3), 100.0
COLLISION_REFERENCE_SPEED_MPS = 50


class GenericShipNavigator(GenericNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
        self.has_waypoint_loop = False
        self.time_in_spiral_s = 0.0
        # Per-phase scaling of the collision-avoidance contribution, reset each
        # frame and lowered by phases that deliberately fly close (formation, the
        # strafe corridor). The surface altitude floor is a *separate* mechanism
        # (the sensor lumps all obstacles into one repulsion, so a single scalar
        # can't keep the floor while dropping lateral avoidance).
        self.avoidance_weight_factor = 1.0
        self.collision_sensor = CollisionSensor(game=game, ship=self.pawn)

    def navigate(self, intent: int, target_dict: dict) -> tuple[np.ndarray, float]:
        """
        Merges the tactician's intent and collision avoidance into explicit directions

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: The direction to point to and the desired speed
        """
        # Reset the per-phase avoidance factor; the intent may lower it (formation,
        # strafe corridor) before we apply it below.
        self.avoidance_weight_factor = 1.0
        # Reset the pilot up-reference; a bomb run sets it to aim the belly.
        self.up_reference = None
        # Compute intentional component
        intent_direction, intent_speed = self.navigate_intent(
            intent=intent, target_dict=target_dict
        )
        # Compute collision avoidance component
        (
            avoidance_direction,
            avoidance_speed,
            avoidance_weight,
        ) = self.navigate_avoidance()
        # Scale the avoidance contribution by the phase factor (e.g. dwarfed in
        # formation or during a low corridor pass).
        avoidance_weight *= self.avoidance_weight_factor

        direction = (intent_direction + avoidance_weight * avoidance_direction) / (
            1 + avoidance_weight
        )
        speed = (intent_speed + avoidance_weight * avoidance_speed) / (
            1 + avoidance_weight
        )

        # Step-by-step recording of how much collision avoidance is bending the
        # steering away from the tactician's intent (for forensic analysis).
        if RECORD_GAME and getattr(self.pawn.parent, "record", False):
            name = self.pawn.parent.name
            self.game.record.record(f"{name}_avoidance_weight", float(avoidance_weight))
            intent_norm = np.linalg.norm(intent_direction)
            blended_norm = np.linalg.norm(direction)
            if intent_norm > EPSILON_TOLERANCE and blended_norm > EPSILON_TOLERANCE:
                deflection = float(
                    np.dot(intent_direction / intent_norm, direction / blended_norm)
                )
            else:
                deflection = float("nan")
            self.game.record.record(
                f"{name}_intent_vs_blended_collision_alignment", deflection
            )

        return direction, speed

    def navigate_avoidance(self) -> tuple[np.ndarray, float, float]:
        """
        Polls the collision sensor and computes direction and speed to avoid collision

        :return: The direction to point to, the desired speed and the avoidance weight
        """
        (
            avoidance_direction,
            avoidance_weight,
        ) = self.collision_sensor.compute_repulsion()
        if avoidance_weight < 1e-4:
            return np.zeros(3), 0.0, 0.0
        avoidance_speed = COLLISION_REFERENCE_SPEED_MPS / avoidance_weight

        return avoidance_direction, avoidance_speed, avoidance_weight

    def navigate_intent(
        self, intent: int, target_dict: dict
    ) -> tuple[np.ndarray, float]:
        """
        Turns the tactician's intent into explicit directions

        :return: The direction to point to and the desired speed
        """
        raise NotImplementedError

    # %% ==== REGROUP ====

    def regroup(self, target_dict={}) -> Tuple[np.ndarray, float]:
        """
        Regroups with allies. If none are left, go to the center of the world

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and the desired speed
        """
        target_relative_position = target_dict["position"] - self.pawn.position
        target_distance = np.linalg.norm(target_relative_position)

        # Case where the target is at zero distance
        if target_distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        return (
            target_relative_position / target_distance,
            self.personality["navigator"]["regroup"]["speed_mps"],
        )

    # %% ==== DISENGAGE ====

    def disengage(self, target_dict={}) -> Tuple[np.ndarray, float]:
        """
        Flees from the danger zone, defined as the center of gravity of all foes

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and the desired speed
        """
        target_relative_position = target_dict["position"] - self.pawn.position
        target_distance = np.linalg.norm(target_relative_position)

        # Case where the target is at zero distance
        if target_distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        fleeing_direction = -target_relative_position / target_distance

        return fleeing_direction, self.personality["navigator"]["speeding"]["speed_mps"]

    # %% ==== PATROL ====

    def set_waypoints(self, waypoints: List[np.ndarray], is_loop: bool = False):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: A list of waypoint coordinates
        """
        assert len(waypoints) >= 1
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.has_waypoint_loop = is_loop

    def follow_waypoints(self) -> Tuple[np.ndarray, float]:
        """
        Goes to the next available waypoint

        :return: The direction to point to and the desired speed
        """
        # Handle the case where waypoints have already been visited
        if self.next_waypoint_idx == len(self.waypoints):
            if self.has_waypoint_loop:
                # Start the loop again
                self.next_waypoint_idx = 0
            else:
                # It's not a loop.
                # Empty list and return no direction
                self.waypoints = []
                self.next_waypoint_idx = 0
                return NO_DIRECTION

        # Find next waypoint
        next_waypoint = self.waypoints[self.next_waypoint_idx]
        waypoint_direction = next_waypoint - self.pawn.position
        self.distance_to_waypoint_m = np.linalg.norm(waypoint_direction)

        # Handle the case where the next waypoint has been met already
        if (
            self.distance_to_waypoint_m
            < self.personality["navigator"]["patrol"]["waypoint_meeting_tolerance_m"]
        ):
            # Do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            return NO_DIRECTION

        # Go to the next waypoint
        direction = waypoint_direction / self.distance_to_waypoint_m
        return direction, self.personality["navigator"]["patrol"]["speed_mps"]

    # %% ==== formation ====

    def formation(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Follows the leader of the formation with the offset defined by the index of the
        ship in the formation.

        The formation leader is in the same team as self, so game.interactions does
        not pre-compute their relative speeds/positions (cost saving).
        Therefore, all computations are done here

        :param target_dict: A dictionary with the formation leader's id, as well as the
                            current ship's desired position in the formation
        :return: The direction to point to and the desired speed
        """

        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to form up "
                "but there's no attached target"
            )
            return NO_DIRECTION

        # Fly close in formation: dwarf the collision-avoidance contribution.
        self.avoidance_weight_factor = self.personality["navigator"]["formation"][
            "collision_avoidance_contribution_factor"
        ]

        # Identify leader in interactions
        try:
            leader_actor_index = self.game.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
            leader = self.game.interactions.actors[leader_actor_index]
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.pawn.parent.name}: "
                    "Formation leader has been destroyed since last intent update."
                )
            return NO_DIRECTION

        # Compute pursuit variables
        relative_position_in_formation = target_dict["target_relative_position"]
        position_in_formation = leader.position + (
            leader.right * relative_position_in_formation[0]
            + leader.forward * relative_position_in_formation[1]
            + leader.up * relative_position_in_formation[2]
        )
        target_position = (
            position_in_formation
            + leader.forward
            * self.personality["navigator"]["formation"]["ideal_distance_m"]
        )  # Aim forward of the intended position to make the follow algos work
        # Should target speed must take into account the turn speed of the leader ?
        target_speed = leader.speed  # +
        # np.cross(
        #     leader.pqr, (position_in_formation - leader.position)
        # )

        # Compute relative quantities
        direction = np.float64(target_position - self.pawn.position)
        distance_m = np.linalg.norm(direction)
        if distance_m > TARGET_DISTANCE_TOLERANCE_M:
            direction /= distance_m
        else:
            direction = np.zeros(3)
            distance_m = 0.0

        relative_speed_vector = target_speed - self.pawn.speed
        longitudinal_speed_scalar_mps = np.dot(relative_speed_vector, direction)

        # Compute Lead pursuit
        aim_vector = self.compute_lead_pursuit(
            target_current_position=target_position,
            target_current_speed=target_speed,
            lead_time_s=1.0,
        )

        aim_vector_norm = np.linalg.norm(aim_vector)
        if aim_vector_norm < EPSILON_TOLERANCE:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Compute desired speed
        target_speed_mps = np.linalg.norm(target_speed)
        pursuit_speed_mps = self.compute_follow_speed(
            distance_m=distance_m,
            target_speed_mps=target_speed_mps,
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
            intent="formation",
        )

        return aim_vector, pursuit_speed_mps

    # %% ==== COMMON METHODS ====
    def compute_follow_speed(
        self,
        distance_m: float,
        target_speed_mps: float,
        longitudinal_speed_scalar_mps: float,
        intent: str,
    ) -> float:
        """
        Computes the desired speed to follow a target
        It must be the same as the target speed if it is at the desired follow distance
        It must increase if the target is too far and vice-versa
        TODO : effect of closing speed ?

        :param distance_m: Distance to target
        :param target_speed_mps: Speed of target
        :param longitudinal_speed_scalar_mps: relative speed in the target's direction
        :return: The desired follow speed
        """
        desired_speed_mps = (
            target_speed_mps
            + self.compute_speed_target_distance_contribution(
                distance_m=distance_m, intent=intent
            )
        )
        desired_speed_mps = min(max(desired_speed_mps, 0.0), self.pawn.max_speed_mps)
        return desired_speed_mps

    def compute_speed_target_distance_contribution(
        self,
        distance_m: float,
        intent: str,
    ) -> float:
        """
        Computes the contribution of target distance to pursuit speed
        Far targets get high speed,

        :param distance_m: Distance to target
        :return: The distance contribution to pursuit speed
        """
        distance_contribution_mps = self.pawn.max_speed_mps * (
            0.5
            - smooth_step_down(
                x=distance_m,
                x_step=self.personality["navigator"][intent]["ideal_distance_m"],
                slope=self.personality["navigator"][intent]["speed_distance_slope"],
            )
        )
        return distance_contribution_mps

    # %% ==== DELETING ====

    def clean(self):
        super().clean()
        self.collision_sensor.clean()
        self.collision_sensor = None
