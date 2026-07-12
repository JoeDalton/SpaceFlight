import logging
from typing import Tuple

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)

LOGGER = logging.getLogger()


class CapitalShipNavigator(GenericShipNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.CAPITAL_SHIP_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def navigate_intent(
        self, intent: int, target_dict: dict
    ) -> tuple[np.ndarray, float]:
        """
        Turns the tactician's intent into explicit directions

        :return: The direction to point to and the desired speed
        """
        if intent == Intent.IDLE:
            self.engage_phase = ""
            return NO_DIRECTION
        elif intent == Intent.PATROL:
            self.engage_phase = ""
            return self.follow_waypoints()
        elif intent == Intent.ENGAGE:
            return self.engage_target(target_dict)
        elif intent == Intent.REGROUP:
            self.engage_phase = ""
            return self.regroup(target_dict)
        elif intent == Intent.DISENGAGE:
            self.engage_phase = ""
            return self.disengage(target_dict)
        elif intent == Intent.FORMATION:
            self.engage_phase = ""
            return self.formation(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

        # %% ==== ENGAGE ====

    def engage_target(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Engages a target by orbiting it so it stays abeam on the side-mounted
        turret flank (the turrets track and fire on their own; this only maintains
        the hull geometry).

        Rather than a fixed-radius circle, the ship holds a constant standoff from
        the target's oriented bounding box and drives tangentially, so the orbit
        shape follows the target: a circle for a compact target, a racetrack for a
        long thin one (constant firing range off the flanks).

        :param target_dict: A dictionary with the target id
        :return: The direction to point to and the desired speed
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to engage "
                "but there's no attached target"
            )
            return NO_DIRECTION

        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.pawn.parent.name}: "
                    "Target has been destroyed since last intent update."
                )
            return NO_DIRECTION

        distance_m = self.game.interactions.distances[
            my_actor_index, target_actor_index
        ]
        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        target = self.game.interactions.actors[target_actor_index]
        target_position = self.pawn.position + distance_m * direction

        self.behaviour_sm.request("orbit")
        return self.orbit_target(target=target, target_position=target_position)

    def orbit_target(self, target, target_position: np.ndarray) -> tuple:
        """
        Hold a constant standoff from the target's horizontal oriented bounding box
        and drive tangentially around it, staggered slightly off the target plane.

        :param target: The target actor (read for its bounding box and orientation)
        :param target_position: The target's world position this frame
        :return: The direction to point to and the desired speed
        """
        orbit = self.personality["navigator"]["orbit"]
        world_up = self.game.scene.up_direction

        nearest_point = self._nearest_point_on_horizontal_obb(
            target=target, center=target_position, point=self.pawn.position
        )

        # Outward normal from the hull, kept in the horizontal plane.
        outward = self.pawn.position - nearest_point
        outward_horizontal = outward - np.dot(outward, world_up) * world_up
        outward_distance_m = np.linalg.norm(outward_horizontal)
        if outward_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            # Degenerate (directly over the hull): fall back to the target's beam.
            outward_horizontal = self._horizontal_axis(target.right, world_up)
            outward_distance_m = np.linalg.norm(outward_horizontal)
            if outward_distance_m < TARGET_DISTANCE_TOLERANCE_M:
                return NO_DIRECTION
        outward_normal = outward_horizontal / outward_distance_m

        # Standoff distance off the hull surface; floored so the bow/stern caps stay
        # flyable for a slow ship (the box already embodies the target's width).
        standoff_m = max(orbit["standoff_clearance_m"], orbit["min_turn_radius_m"])
        radial_error_m = outward_distance_m - standoff_m

        # Tangent to the orbit (90° rotation of the outward normal about world up),
        # sense chosen so the target sits on the turret flank.
        tangential = orbit["direction"] * np.cross(world_up, outward_normal)

        desired_direction = (
            tangential - orbit["radial_gain"] * radial_error_m * outward_normal
        )

        # Sit slightly off the exact target plane (avoid collisions / turret pitch 0)
        altitude_error_m = (
            np.dot(target_position - self.pawn.position, world_up)
            + orbit["altitude_stagger_m"]
        )
        desired_direction = (
            desired_direction + orbit["vertical_gain"] * altitude_error_m * world_up
        )

        desired_norm = np.linalg.norm(desired_direction)
        if desired_norm < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION
        return desired_direction / desired_norm, orbit["orbit_speed_mps"]

    def _horizontal_axis(self, axis: np.ndarray, world_up: np.ndarray) -> np.ndarray:
        """
        Project a body axis into the horizontal plane (drop the world-up component).

        :param axis: The axis to project
        :param world_up: The world up direction
        :return: The horizontal projection (not normalised)
        """
        return axis - np.dot(axis, world_up) * world_up

    def _nearest_point_on_horizontal_obb(
        self, target, center: np.ndarray, point: np.ndarray
    ) -> np.ndarray:
        """
        Closest point to point on the target's horizontal oriented bounding box
        footprint (the box's right/forward extents, projected into the horizontal
        plane). Falls back to a square footprint from the collision radius when the
        target exposes no bounding box (e.g. a subsystem).

        :param target: The target actor
        :param center: The target's world position
        :param point: The query point (the attacker's position)
        :return: The nearest point on the footprint, in world coordinates
        """
        world_up = self.game.scene.up_direction
        half_extents = getattr(target, "bounding_box_half_extents", None)
        if half_extents is None:
            radius_m = float(getattr(target, "hit_box_radius_m", 50.0))
            half_extents = np.array([radius_m, radius_m, radius_m])

        # Horizontal footprint axes from the target's orientation.
        right_axis = self._horizontal_axis(target.right, world_up)
        forward_axis = self._horizontal_axis(target.forward, world_up)
        right_norm = np.linalg.norm(right_axis)
        forward_norm = np.linalg.norm(forward_axis)
        if right_norm < 1e-4 or forward_norm < 1e-4:
            # No usable footprint orientation: treat as a point at the center.
            return center.copy()
        right_axis /= right_norm
        forward_axis /= forward_norm

        relative = point - center
        clamped_right = np.clip(
            np.dot(relative, right_axis), -half_extents[0], half_extents[0]
        )
        clamped_forward = np.clip(
            np.dot(relative, forward_axis), -half_extents[1], half_extents[1]
        )
        return center + clamped_right * right_axis + clamped_forward * forward_axis
