from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Tuple

import numpy as np

from space_flight import EPSILON_TOLERANCE, RECORD_GAME
from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Intent
from space_flight.ai.collision_sensor import CollisionSensor
from space_flight.ai.generic.generic_navigator import GenericNavigator
from space_flight.utils import magnitude, smooth_step_down

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3), 100.0
COLLISION_REFERENCE_SPEED_MPS = 50


class GenericShipNavigator(GenericNavigator):
    """
    Navigator for free-flying ships: blends the intent's direction with collision
    avoidance, and outputs a direction to point to and a desired speed.
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
        self.has_waypoint_loop = False
        # Patrol progress tracking: when the bot can't get closer to its waypoint
        # (turn radius too large for its speed), it slows down to tighten its turn
        self._best_distance_to_waypoint_m = float("inf")
        self._time_without_progress_s = 0.0
        self.patrol_speed_factor = 1.0
        self.time_in_spiral_s = 0.0
        # Game time of the last navigate() and the time elapsed since the one
        # before: navigate() runs when the bot thinks, not necessarily every frame
        self._last_navigate_s = None
        self.think_dt_s = 0.0
        # Per-phase scaling of the collision-avoidance contribution, reset by each
        # navigate() and lowered by phases that deliberately fly close (formation,
        # the strafe corridor). The strafe altitude floor is separate: the sensor
        # lumps all obstacles into one repulsion, so this scalar can't keep the
        # floor while dropping lateral avoidance.
        self.avoidance_weight_factor = 1.0
        self.collision_sensor = CollisionSensor(game=game, ship=self.pawn)

    def navigate(self, intent: Intent, target_dict: dict) -> tuple[np.ndarray, float]:
        """
        Merges the tactician's intent and collision avoidance into explicit directions

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: The direction to point to and the desired speed
        """
        now_s = self.game.game_time.get_current_time()
        if self._last_navigate_s is None:
            self.think_dt_s = self.game.game_time.get_time_step()
        else:
            self.think_dt_s = now_s - self._last_navigate_s
        self._last_navigate_s = now_s
        # Reset the per-phase avoidance factor; the intent may lower it (formation,
        # strafe corridor) before we apply it below.
        self.avoidance_weight_factor = 1.0
        # Reset the sensor reach to full; a bomb run may shorten it (drop the outer
        # sphere) so it can overfly a big target without being pushed off it.
        self.collision_sensor.active_range = self.collision_sensor.n_spheres
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
            intent_norm = magnitude(intent_direction)
            blended_norm = magnitude(direction)
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

    def update_triggers(self, intent: Intent, target_dict: dict):
        """
        Weapon decisions (firing, bomb release) on the frames where navigate()
        does not run. None by default.

        :param intent: The tactician's current intent
        :param target_dict: The tactician's current target info
        """

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
        self, intent: Intent, target_dict: dict
    ) -> tuple[np.ndarray, float]:
        """
        Turns the tactician's intent into explicit directions

        :return: The direction to point to and the desired speed
        """
        raise NotImplementedError

    # %% ==== REGROUP ====

    def regroup(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Regroups with allies. If none are left, go to the center of the world

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and the desired speed
        """
        target_relative_position = target_dict["position"] - self.pawn.position
        target_distance = magnitude(target_relative_position)

        # Case where the target is at zero distance
        if target_distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        return (
            target_relative_position / target_distance,
            self.personality["navigator"]["regroup"]["speed_mps"],
        )

    # %% ==== DISENGAGE ====

    def disengage(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Flees from the danger zone, defined as the center of gravity of all foes

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and the desired speed
        """
        target_relative_position = target_dict["position"] - self.pawn.position
        target_distance = magnitude(target_relative_position)

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
        :param is_loop: Whether to restart from the first waypoint after the last
        """
        assert len(waypoints) >= 1
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.has_waypoint_loop = is_loop
        self._reset_patrol_progress()

    def clear_waypoints(self):
        """
        Drops the current trajectory, as when a non-looping one is completed
        """
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.has_waypoint_loop = False
        self._reset_patrol_progress()

    def _reset_patrol_progress(self):
        """
        Forgets the approach history of the current waypoint and restores full speed
        """
        self._best_distance_to_waypoint_m = float("inf")
        self._time_without_progress_s = 0.0
        self.patrol_speed_factor = 1.0

    def follow_waypoints(self) -> Tuple[np.ndarray, float]:
        """
        Goes to the next available waypoint

        :return: The direction to point to and the desired speed
        """
        # No trajectory: the route was cleared (clear_waypoints) while the
        # tactician is still committed to patrolling
        if not self.waypoints:
            return NO_DIRECTION

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
        self.distance_to_waypoint_m = magnitude(waypoint_direction)

        # Handle the case where the next waypoint has been met already
        if (
            self.distance_to_waypoint_m
            < self.personality["navigator"]["patrol"]["waypoint_meeting_tolerance_m"]
        ):
            # Do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            self._reset_patrol_progress()
            return NO_DIRECTION

        # Slow down if we are not getting any closer (orbiting the waypoint)
        patrol = self.personality["navigator"]["patrol"]
        if (
            self.distance_to_waypoint_m
            < self._best_distance_to_waypoint_m - patrol["progress_epsilon_m"]
        ):
            self._best_distance_to_waypoint_m = self.distance_to_waypoint_m
            self._time_without_progress_s = 0.0
        else:
            self._time_without_progress_s += self.think_dt_s
            if self._time_without_progress_s > patrol["stall_time_s"]:
                self.patrol_speed_factor = max(
                    self.patrol_speed_factor * patrol["stall_deceleration_factor"],
                    patrol["min_speed_factor"],
                )
                self._time_without_progress_s = 0.0

        # Go to the next waypoint
        direction = waypoint_direction / self.distance_to_waypoint_m
        return direction, patrol["speed_mps"] * self.patrol_speed_factor

    # %% ==== formation ====

    def formation(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Follows the formation leader at the ship's slot offset (in the leader's
        frame), aiming ideal_distance_m ahead of the slot with lead pursuit.

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
        # TODO account for the leader's turn rate in the target speed?
        target_speed = leader.speed  # +
        # np.cross(
        #     leader.pqr, (position_in_formation - leader.position)
        # )

        # Compute relative quantities
        direction = np.float64(target_position - self.pawn.position)
        distance_m = magnitude(direction)
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

        aim_vector_norm = magnitude(aim_vector)
        if aim_vector_norm < EPSILON_TOLERANCE:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Compute desired speed
        target_speed_mps = magnitude(target_speed)
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
        Computes the desired speed to follow a target: the target's speed at the
        ideal follow distance, faster when too far and slower when too close,
        clamped to [minimum_speed_mps, max_speed_mps] (the personality's optional
        minimum_speed_mps for that intent, 0 by default).
        TODO : effect of closing speed ? (longitudinal_speed_scalar_mps is unused)

        :param distance_m: Distance to target
        :param target_speed_mps: Speed of target
        :param longitudinal_speed_scalar_mps: relative speed in the target's direction
        :param intent: The navigator personality section to tune with ("attack",
            "formation")
        :return: The desired follow speed
        """
        desired_speed_mps = (
            target_speed_mps
            + self.compute_speed_target_distance_contribution(
                distance_m=distance_m, intent=intent
            )
        )
        minimum_speed_mps = self.personality["navigator"][intent].get(
            "minimum_speed_mps", 0.0
        )
        desired_speed_mps = min(
            max(desired_speed_mps, minimum_speed_mps), self.pawn.max_speed_mps
        )
        return desired_speed_mps

    def compute_speed_target_distance_contribution(
        self,
        distance_m: float,
        intent: str,
    ) -> float:
        """
        Computes the contribution of target distance to pursuit speed: from
        -max_speed_mps / 2 (close) to +max_speed_mps / 2 (far), zero at
        ideal_distance_m.

        :param distance_m: Distance to target
        :param intent: The navigator personality section to tune with
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
