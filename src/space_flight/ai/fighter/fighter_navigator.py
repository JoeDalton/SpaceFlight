import logging
from typing import Tuple

import numpy as np

from space_flight import RECORD_GAME
from space_flight.actors.bomb_launcher import BOMB_SPEED_MPS
from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, AttackMode, Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)
from space_flight.utils import smooth_step_down, smooth_step_up

LOGGER = logging.getLogger()


class FighterNavigator(GenericShipNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.time_in_spiral_s = 0.0

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
            # Exact behaviour is defined and recorded inside engage_target
            # TODO reset spiral time if new order ? May not be necessary
            return self.engage_target(target_dict)
        elif intent == Intent.EVADE:
            self.engage_phase = ""
            return self.evade_target(target_dict)
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
        Engages a target with the attack mode the tactician chose (carried in
        ``target_dict["attack_mode"]``):

        - ``PURSUIT`` (default): constant-angle chase, good against agile prey.
        - ``STRAFE``: a committed ingress -> attack -> break -> reposition run for
          slow or immobile targets.
        - ``BOMB``: overfly a slow/immobile target and drop a bomb along the belly.

        :param target_dict: A dictionary with the target id, attack mode and
            (for surface-mounted preys) surface normal/hit point
        :return: The direction to point to and the desired speed
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to engage "
                "but there's no attached target"
            )
            return NO_DIRECTION

        if not self._resolve_engagement(target_dict):
            return NO_DIRECTION

        attack_mode = target_dict.get("attack_mode", AttackMode.PURSUIT)
        if attack_mode == AttackMode.BOMB:
            return self.bomb_target(target_dict)
        if attack_mode == AttackMode.STRAFE:
            return self.strafe_target(target_dict)
        return self.pursue_target(target_dict)

    def _resolve_engagement(self, target_dict: dict) -> bool:
        """
        Enrich ``target_dict`` in place with the per-frame engagement geometry
        shared by every attack mode, so all pattern methods take the single
        ``target_dict``.

        :param target_dict: The tactician's target info (needs ``target_id``);
            mutated with the resolved geometry keys
        :return: True if resolved, False if the target is gone
        """
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
            return False

        distance_m = self.game.interactions.distances[
            my_actor_index, target_actor_index
        ]
        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed_vector = self.game.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]
        target_dict["distance_m"] = distance_m
        target_dict["direction"] = direction
        target_dict["relative_speed_vector"] = relative_speed_vector
        target_dict["longitudinal_speed_scalar_mps"] = np.dot(
            relative_speed_vector, direction
        )
        target_dict["target_current_position"] = (
            self.pawn.position + distance_m * direction
        )
        target_dict["target_current_speed"] = self.pawn.speed + relative_speed_vector
        return True

    def _record_firing(self, distance_m: float, firing_alignment: float, fired: bool):
        """
        Step-by-step recording of the firing solution (for post-hoc analysis of
        why a bot does or does not land hits). Inert unless recording is on for
        this bot.
        """
        if not RECORD_GAME or not getattr(self.pawn.parent, "record", False):
            return
        name = self.pawn.parent.name
        self.game.record.record(f"{name}_firing_alignment", float(firing_alignment))
        self.game.record.record(
            f"{name}_in_fire_range",
            bool(
                distance_m < self.personality["navigator"]["fire"]["maximum_distance_m"]
            ),
        )
        self.game.record.record(f"{name}_fired", bool(fired))

    def pursue_target(self, target_dict: dict) -> Tuple[np.ndarray, float]:
        """
        The constant-angle-pursuit chase (CAP + lead + lag) with the reposition and
        extend escape behaviours. Good against agile prey.

        :param target_dict: The target info enriched with the engagement geometry
            (see _resolve_engagement)
        :return: The direction to point to and the desired speed
        """
        distance_m = target_dict["distance_m"]
        direction = target_dict["direction"]
        relative_speed_vector = target_dict["relative_speed_vector"]
        longitudinal_speed_scalar_mps = target_dict["longitudinal_speed_scalar_mps"]
        target_current_position = target_dict["target_current_position"]
        target_current_speed = target_dict["target_current_speed"]

        # Compute lead pursuit direction necessary for firing solution
        lead_direction = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )

        # Decide whether to shoot
        firing_alignment = np.dot(lead_direction, self.pawn.forward)
        in_range = (
            distance_m < self.personality["navigator"]["fire"]["maximum_distance_m"]
        )
        aligned = (
            firing_alignment
            > self.personality["navigator"]["fire"]["minimum_cos_angle"]
        )
        fired = in_range and aligned
        if fired:
            self.pawn.laser_cannon.fire()
        self._record_firing(
            distance_m=distance_m, firing_alignment=firing_alignment, fired=fired
        )

        # Check if we risk passing ahead of the target
        if self.check_overshoot_risk(
            closing_speed_mps=-longitudinal_speed_scalar_mps, distance_m=distance_m
        ):
            self.behaviour_sm.request("reposition")
            return self.reposition(direction=direction)

        # Check if we need to extend the trajectory to avoid a spiral of death
        longitudinal_speed_vector = longitudinal_speed_scalar_mps * direction
        lateral_speed_vector = relative_speed_vector - longitudinal_speed_vector
        lateral_speed_scalar_mps = np.linalg.norm(lateral_speed_vector)

        if self.check_extend_conditions(
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
            lateral_speed_scalar_mps=lateral_speed_scalar_mps,
        ):
            self.behaviour_sm.request("extend")
            return self.extend()

        # Pursue target
        self.behaviour_sm.request("pursuit")

        # Compute CAP contribution
        cap_direction = self.compute_constant_angle_pursuit(
            direction=direction,
            distance_m=distance_m,
            lateral_speed_vector=lateral_speed_vector,
        )
        # Compute lag_pursuit contribution
        lag_direction = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lag_time_s"],
        )
        # Compute weigths of pursuit strategies
        cap_weight, lead_weight, lag_weight = self.compute_engage_weights(
            distance_m=distance_m
        )
        aim_vector = (
            self.personality["navigator"]["attack"]["cap_bias"]
            * cap_direction
            * cap_weight
            + self.personality["navigator"]["attack"]["lead_bias"]
            * lead_direction
            * lead_weight
            + self.personality["navigator"]["attack"]["lag_bias"]
            * lag_direction
            * lag_weight
        )
        aim_vector_norm = np.linalg.norm(aim_vector)
        if aim_vector_norm < TARGET_DISTANCE_TOLERANCE_M:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Compute desired speed
        target_speed_mps = np.linalg.norm(target_current_speed)
        pursuit_speed_mps = self.compute_follow_speed(
            distance_m=distance_m,
            target_speed_mps=target_speed_mps,
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
            intent="attack",
        )

        return aim_vector, pursuit_speed_mps

    # %% ==== STRAFE ====

    def strafe_target(self, target_dict: dict) -> Tuple[np.ndarray, float]:
        """
        Strafing run against a slow or immobile target: a committed phase cycle
        ``ingress -> attack -> break -> reposition -> ingress`` that runs in fast,
        fires, peels off and comes around again, instead of spiralling like a chase.

        For a surface-mounted prey (``surface_normal``/``surface_hit_point`` in
        ``target_dict``) the ingress becomes a low-altitude corridor (a run at a set
        altitude above the surface, then a dive), the break climbs along the normal,
        and a hard altitude floor forces recovery. Without surface info it is a
        straight open-space pass.

        :param target_dict: The target info enriched with the engagement geometry
            (see _resolve_engagement); surface fields optional
        :return: The direction to point to and the desired speed
        """
        strafe = self.personality["navigator"]["strafe"]
        distance_m = target_dict["distance_m"]
        direction = target_dict["direction"]
        target_position = target_dict["target_current_position"]
        target_speed = target_dict["target_current_speed"]
        closing_speed_mps = -target_dict["longitudinal_speed_scalar_mps"]
        surface_normal = target_dict.get("surface_normal")
        surface_hit_point = target_dict.get("surface_hit_point")

        # Lead the target: fly at where it will be when we arrive, i.e. lead by the
        # closing time (distance / closing_speed), so a moving target is met head-on
        # instead of chased from behind.
        lead_time_s = 0.0
        if closing_speed_mps > 1e-3:
            lead_time_s = min(distance_m / closing_speed_mps, strafe["max_lead_time_s"])
        lead_target_position = target_position + target_speed * lead_time_s
        lead_direction = self.compute_lead_pursuit(
            target_current_position=target_position,
            target_current_speed=target_speed,
            lead_time_s=lead_time_s,
        )

        # Fire whenever aligned and in range, in any phase.
        self._strafe_try_fire(
            target_position=target_position,
            target_speed=target_speed,
            distance_m=distance_m,
        )

        # Hard altitude floor: force a recovery break if we drop too low.
        if self._below_altitude_floor(surface_normal, surface_hit_point, strafe):
            self.behaviour_sm.request("strafe_break")

        phase = (
            self.behaviour if self.behaviour.startswith("strafe_") else "strafe_ingress"
        )

        if phase == "strafe_ingress":
            if distance_m < strafe["attack_distance_m"]:
                self.behaviour_sm.request("strafe_attack")
                return self._strafe_attack(lead_direction=lead_direction, strafe=strafe)
            self.behaviour_sm.request("strafe_ingress")
            return self._strafe_ingress(
                lead_direction=lead_direction,
                lead_target_position=lead_target_position,
                distance_m=distance_m,
                surface_normal=surface_normal,
                strafe=strafe,
            )

        if phase == "strafe_attack":
            # Press in until point-blank; peel off early only on a geometry-driven
            # escape (about to overshoot, or stalled and unable to close) rather
            # than an arbitrary timer.
            reached_standoff = distance_m < strafe["break_distance_m"]
            overshooting = self.check_overshoot_risk(
                closing_speed_mps=closing_speed_mps, distance_m=distance_m
            )
            stalled = (
                self.behaviour_duration_s > strafe["stall_time_s"]
                and closing_speed_mps < strafe["minimum_closing_speed_mps"]
            )
            if reached_standoff or overshooting or stalled:
                self.behaviour_sm.request("strafe_break")
                return self._strafe_break(
                    direction=direction, surface_normal=surface_normal, strafe=strafe
                )
            self.behaviour_sm.request("strafe_attack")
            return self._strafe_attack(lead_direction=lead_direction, strafe=strafe)

        if phase == "strafe_break":
            if self.behaviour_duration_s > strafe["break_duration_s"]:
                self.behaviour_sm.request("strafe_reposition")
                return self._strafe_reposition(direction=direction, strafe=strafe)
            self.behaviour_sm.request("strafe_break")
            return self._strafe_break(
                direction=direction, surface_normal=surface_normal, strafe=strafe
            )

        # strafe_reposition: extend to standoff, then re-enter the ingress. Commit
        # for a minimum time as well as a minimum distance, so the run flies out and
        # swings around for a clean next pass instead of snapping back too early.
        repositioned_far_enough = distance_m > strafe["reposition_distance_m"]
        repositioned_long_enough = (
            self.behaviour_duration_s > strafe["reposition_min_duration_s"]
        )
        if repositioned_far_enough and repositioned_long_enough:
            self.behaviour_sm.request("strafe_ingress")
            return self._strafe_ingress(
                lead_direction=lead_direction,
                lead_target_position=lead_target_position,
                distance_m=distance_m,
                surface_normal=surface_normal,
                strafe=strafe,
            )
        self.behaviour_sm.request("strafe_reposition")
        return self._strafe_reposition(direction=direction, strafe=strafe)

    def _strafe_try_fire(
        self,
        target_position: np.ndarray,
        target_speed: np.ndarray,
        distance_m: float,
    ):
        """
        Fire the guns if the (near-pure-pursuit) firing solution is aligned with
        the nose and the target is in range.
        """
        lead_direction = self.compute_lead_pursuit(
            target_current_position=target_position,
            target_current_speed=target_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )
        firing_alignment = np.dot(lead_direction, self.pawn.forward)
        fire = self.personality["navigator"]["fire"]
        strafe = self.personality["navigator"]["strafe"]
        # Range from the shared fire config, but a wider (strafe-specific) cone: a
        # fast pass rarely holds the nose within the 5deg pursuit cone, and auto-aim
        # bends the shot the rest of the way.
        fired = (distance_m < fire["maximum_distance_m"]) and (
            firing_alignment > strafe["fire_min_cos_angle"]
        )
        if fired:
            self.pawn.laser_cannon.fire()
        self._record_firing(
            distance_m=distance_m, firing_alignment=firing_alignment, fired=fired
        )

    def _below_altitude_floor(
        self,
        surface_normal: np.ndarray,
        surface_hit_point: np.ndarray,
        strafe: dict,
    ) -> bool:
        """
        Whether the ship has dropped below the corridor's hard altitude floor.

        Only meaningful for surface-mounted preys; without surface info there is
        no floor (open-space pass).

        :return: True if too low and a recovery break must be forced
        """
        if surface_normal is None or surface_hit_point is None:
            return False
        altitude_m = np.dot(self.pawn.position - surface_hit_point, surface_normal)
        return bool(altitude_m < strafe["altitude_floor_m"])

    def _strafe_ingress(
        self,
        lead_direction: np.ndarray,
        lead_target_position: np.ndarray,
        distance_m: float,
        surface_normal: np.ndarray,
        strafe: dict,
    ) -> Tuple[np.ndarray, float]:
        """
        Run in fast toward the target's lead (intercept) point (a low corridor for
        surface preys), weaving to spoil defensive fire. The weave amplitude ramps
        down with distance, so the nose is steady by the time the attack/dive begins.
        """
        # Reseed the weave phase on a fresh ingress so runs are not predictable.
        if self.behaviour_duration_s <= 0.0:
            self.weave_phase_rad = float(np.random.uniform(0.0, 2 * np.pi))

        if surface_normal is not None:
            # Corridor: aim a run altitude above the lead point, which becomes a
            # shallow dive as we close. Deliberately fly low, so dwarf avoidance.
            corridor_point = (
                lead_target_position + surface_normal * strafe["run_altitude_m"]
            )
            base_direction = corridor_point - self.pawn.position
            base_norm = np.linalg.norm(base_direction)
            if base_norm > TARGET_DISTANCE_TOLERANCE_M:
                base_direction = base_direction / base_norm
            else:
                base_direction = lead_direction
            up_reference = surface_normal
            self.avoidance_weight_factor = strafe["corridor_avoidance_factor"]
        else:
            base_direction = lead_direction
            up_reference = self.game.scene.up_direction

        amplitude = strafe["swivel_amplitude"] * min(
            distance_m / strafe["swivel_distance_scale_m"], 1.0
        )
        weaved_direction = self.compute_evasive_weave(
            base_direction=base_direction,
            up_reference=up_reference,
            amplitude=amplitude,
            frequency_hz=strafe["swivel_frequency_hz"],
        )
        return weaved_direction, self._strafe_speed(strafe, "ingress_speed_factor")

    def _strafe_speed(self, strafe: dict, factor_key: str) -> float:
        """
        A strafe phase speed as a fraction of the ship's own top speed.

        :param strafe: The strafe personality sub-dict
        :param factor_key: The fraction key (e.g. ``"attack_speed_factor"``)
        :return: The desired speed in m/s
        """
        return strafe[factor_key] * self.pawn.max_speed_mps

    def _strafe_attack(
        self, lead_direction: np.ndarray, strafe: dict
    ) -> Tuple[np.ndarray, float]:
        """
        Hold the run-in line straight onto the target's lead point (a dive, for
        surface preys), nose steady for the guns. Firing is handled by
        _strafe_try_fire.
        """
        return lead_direction, self._strafe_speed(strafe, "attack_speed_factor")

    def _strafe_break(
        self, direction: np.ndarray, surface_normal: np.ndarray, strafe: dict
    ) -> Tuple[np.ndarray, float]:
        """
        Peel hard away from the target: climb along the surface normal (biased away
        from the target) for surface preys, else simply turn back the way we came.
        """
        if surface_normal is not None:
            break_direction = surface_normal - direction
        else:
            break_direction = -direction
        break_norm = np.linalg.norm(break_direction)
        if break_norm > 1e-4:
            break_direction = break_direction / break_norm
        else:
            break_direction = -direction
        return break_direction, self._strafe_speed(strafe, "break_speed_factor")

    def _strafe_reposition(
        self, direction: np.ndarray, strafe: dict
    ) -> Tuple[np.ndarray, float]:
        """
        Extend away to rebuild distance (and speed) before coming around for the
        next run.
        """
        return -direction, self._strafe_speed(strafe, "reposition_speed_factor")

    # %% ==== BOMB ====

    def bomb_target(self, target_dict: dict) -> Tuple[np.ndarray, float]:
        """
        Bombing run against a slow/immobile target: overfly it and release a bomb
        along the belly (-Z). A committed cycle
        ``ingress -> run -> break -> reposition -> ingress``: line up, fly a straight
        belly-aimed leg while the release solver times the drop, then peel off.

        The belly is aimed via the pilot up-reference (the surface normal for a
        surface-mounted prey, otherwise the line of sight to the target).

        :param target_dict: The target info enriched with engagement geometry
        :return: The direction to point to and the desired speed
        """
        bomb = self.personality["navigator"]["bomb"]
        distance_m = target_dict["distance_m"]
        direction = target_dict["direction"]
        target_position = target_dict["target_current_position"]
        target_speed = target_dict["target_current_speed"]
        closing_speed_mps = -target_dict["longitudinal_speed_scalar_mps"]
        surface_normal = target_dict.get("surface_normal")

        # Roll so the belly (-Z) faces the target: +Z toward the surface normal for
        # a surface prey, else away from the target along the line of sight.
        belly_up_reference = (
            surface_normal if surface_normal is not None else -direction
        )

        phase = self.behaviour if self.behaviour.startswith("bomb_") else "bomb_ingress"

        if phase == "bomb_ingress":
            if distance_m < bomb["run_distance_m"]:
                self.behaviour_sm.request("bomb_run")
                return self._bomb_run(
                    direction, target_position, target_speed, belly_up_reference, bomb
                )
            self.behaviour_sm.request("bomb_ingress")
            return self._bomb_ingress(direction, bomb)

        if phase == "bomb_run":
            # Release once the bomb's velocity lines up with the target, then break.
            if self.compute_release_condition(target_position, target_speed, bomb):
                self.pawn.drop_bomb()
                self.behaviour_sm.request("bomb_break")
                return self._bomb_break(direction, surface_normal, bomb)
            # Overflew (or can't close) without a solution -> break and re-attack.
            if closing_speed_mps <= 0.0:
                self.behaviour_sm.request("bomb_break")
                return self._bomb_break(direction, surface_normal, bomb)
            self.behaviour_sm.request("bomb_run")
            return self._bomb_run(
                direction, target_position, target_speed, belly_up_reference, bomb
            )

        if phase == "bomb_break":
            if self.behaviour_duration_s > bomb["break_duration_s"]:
                self.behaviour_sm.request("bomb_reposition")
                return self._bomb_reposition(direction, bomb)
            self.behaviour_sm.request("bomb_break")
            return self._bomb_break(direction, surface_normal, bomb)

        # bomb_reposition: extend out, then come around for another run.
        if (
            distance_m > bomb["reposition_distance_m"]
            and self.behaviour_duration_s > bomb["reposition_min_duration_s"]
        ):
            self.behaviour_sm.request("bomb_ingress")
            return self._bomb_ingress(direction, bomb)
        self.behaviour_sm.request("bomb_reposition")
        return self._bomb_reposition(direction, bomb)

    def compute_release_condition(
        self, target_position: np.ndarray, target_speed: np.ndarray, bomb: dict
    ) -> bool:
        """
        Whether a bomb dropped this frame would hit the target.

        The bomb travels in a straight line (no gravity) at ``v_bomb = ship.speed -
        launch_speed * ship.up`` (i.e. the belly -Z plus inherited ship velocity),
        so it is forward-and-down. Release when the (lead-adjusted) target lies
        along that velocity within a tolerance cone and range -- mirroring the gun
        fire check, on the bomb's velocity axis instead of the nose.

        :param target_position: The target's world position
        :param target_speed: The target's world velocity
        :param bomb: The bomb personality sub-dict
        :return: True if a drop is on target now
        """
        v_bomb = self.pawn.speed - BOMB_SPEED_MPS * self.pawn.up
        v_bomb_norm = np.linalg.norm(v_bomb)
        if v_bomb_norm < 1e-6:
            return False
        bomb_direction = v_bomb / v_bomb_norm

        # Lead the target by the bomb's closing time (straight-line intercept).
        to_target = target_position - self.pawn.position
        approach = v_bomb - target_speed
        approach_norm = np.linalg.norm(approach)
        if approach_norm > 1e-6:
            lead_time_s = np.linalg.norm(to_target) / approach_norm
            to_target = (
                target_position + target_speed * lead_time_s
            ) - self.pawn.position

        distance_m = np.linalg.norm(to_target)
        if distance_m < TARGET_DISTANCE_TOLERANCE_M:
            return False
        aligned = (
            np.dot(to_target / distance_m, bomb_direction) > bomb["min_cos_release"]
        )
        in_range = distance_m < bomb["max_release_distance_m"]
        return bool(aligned and in_range)

    def _bomb_ingress(
        self, direction: np.ndarray, bomb: dict
    ) -> Tuple[np.ndarray, float]:
        """Close on the target (normal flight) until the straight run begins."""
        return direction, bomb["ingress_speed_factor"] * self.pawn.max_speed_mps

    def _bomb_run(
        self,
        direction: np.ndarray,
        target_position: np.ndarray,
        target_speed: np.ndarray,
        belly_up_reference: np.ndarray,
        bomb: dict,
    ) -> Tuple[np.ndarray, float]:
        """
        The straight, belly-aimed overfly leg. Aims the nose at the target, rolls
        the belly onto it (via the up-reference) and dwarfs collision avoidance so
        the leg stays stable for the release.
        """
        self.up_reference = belly_up_reference
        self.avoidance_weight_factor = self.personality["navigator"]["strafe"][
            "corridor_avoidance_factor"
        ]
        return direction, bomb["run_speed_factor"] * self.pawn.max_speed_mps

    def _bomb_break(
        self, direction: np.ndarray, surface_normal: np.ndarray, bomb: dict
    ) -> Tuple[np.ndarray, float]:
        """
        Peel hard away after the drop: climb along the surface normal for a
        surface prey, else turn back the way we came.
        """
        if surface_normal is not None:
            break_direction = surface_normal - direction
        else:
            break_direction = -direction
        break_norm = np.linalg.norm(break_direction)
        if break_norm > 1e-4:
            break_direction = break_direction / break_norm
        else:
            break_direction = -direction
        return break_direction, bomb["break_speed_factor"] * self.pawn.max_speed_mps

    def _bomb_reposition(
        self, direction: np.ndarray, bomb: dict
    ) -> Tuple[np.ndarray, float]:
        """Extend away to rebuild distance before coming around for the next run."""
        return -direction, bomb["reposition_speed_factor"] * self.pawn.max_speed_mps

    def compute_engage_weights(self, distance_m: float):
        """
        Compute weights of the pursuit strategies as a function of
        distance to target.
        They are overlapping slopes

        :param distance_m: The distance to the prey
        """
        cap_weight = smooth_step_up(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"]["cap_cutoff_distance_m"],
            slope=self.personality["navigator"]["attack"]["cap_lead_cutoff_slope"],
        )
        lead_weight = smooth_step_up(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"][
                "lead_low_cutoff_distance_m"
            ],
            slope=self.personality["navigator"]["attack"]["lead_lag_cutoff_slope"],
        ) * smooth_step_down(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"][
                "lead_high_cutoff_distance_m"
            ],
            slope=self.personality["navigator"]["attack"]["cap_lead_cutoff_slope"],
        )
        lag_weight = smooth_step_down(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"]["lag_cutoff_distance_m"],
            slope=self.personality["navigator"]["attack"]["lead_lag_cutoff_slope"],
        )
        return cap_weight, lead_weight, lag_weight

    def check_extend_conditions(
        self,
        longitudinal_speed_scalar_mps: float,
        lateral_speed_scalar_mps: float,
    ) -> bool:
        """
        Checks if the closing velocity is too low and the lateral velocity is too
        high for too long

        :param longitudinal_speed_scalar_mps: How fast the target is going in
            the self-target direction
        :param lateral_speed_scalar_mps: How fast the target is zooming sideways
        :return: Whether self should extend
        """
        if (
            np.abs(longitudinal_speed_scalar_mps)
            < self.personality["navigator"]["extend"]["minimum_closing_speed_mps"]
        ) and (
            lateral_speed_scalar_mps
            > self.personality["navigator"]["extend"]["maximal_lateral_speed_mps"]
        ):
            # Velocity condition met: accrue this frame's time in the spiral.
            self.time_in_spiral_s += self.game.game_time.get_time_step()
            # Result depends on time condition
            return (
                self.time_in_spiral_s
                > self.personality["navigator"]["extend"]["maximal_time_in_spiral_s"]
            )
        elif (
            self.behaviour == "extend"
            and self.behaviour_duration_s
            < self.personality["navigator"]["extend"]["minimum_duration_s"]
        ):
            # Extending for not enough time
            return True
        else:
            # Velocity condition not met, not in spiral
            # Reset time in spiral
            self.time_in_spiral_s = 0.0
            return False

    def check_overshoot_risk(
        self,
        closing_speed_mps: float,
        distance_m: float,
    ) -> bool:
        """
        Checks if the current trajectory risks taking self farther than the target

        :param closing_speed_mps: How fast the target is closing in
            (positive for closing, negative for pulling away)
        :param distance_m: The distance to the target
        :return: Whether self should reposition
        """
        if closing_speed_mps <= 0:
            # Target pulling away, no risk of overshoot
            return False
        overshoot_time_prediction_s = distance_m / closing_speed_mps

        return (
            overshoot_time_prediction_s
            < self.personality["navigator"]["reposition"]["minimum_time_to_overshoot_s"]
        )

    def reposition(
        self,
        direction: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        Turn hard away from the target to avoid passing in front of it
        Therefore, simply point in the opposite direction with the same distance

        TODO: do something for immobile targets (turrets. They should not be evaded
        the same way as ships)

        :param direction: The direction to the target
        :return: The direction to point to and the desired speed
        """
        # By definition, not in spiral => reset time in spiral
        self.time_in_spiral_s = 0.0
        return -direction, self.personality["navigator"]["turning"]["speed_mps"]

    def extend(self) -> Tuple[np.ndarray, float]:
        """
        Go straight ahead and accelerate to break the pattern

        :return: The direction to point to and the desired speed
        """
        return np.zeros(3), self.personality["navigator"]["speeding"]["speed_mps"]

    # %% ==== EVADE ====

    def evade_target(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Passes behind a target: since the target is threatening, it means that it's
        roughly pointing towards self.
        Therefore, simply point in its direction with 2x the distance

        TODO: do something for immobile targets (turrets. They should not be evaded
        the same way as ships)

        TODO: add randomness to avoid locking in circles

        :param target_dict: A dictionary with the target's direction and distance
        :return: The direction to point to and the desired speed
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to evade but "
                "there's no attached target"
            )
            return NO_DIRECTION

        # Identify self and target in interactions
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

        distance = self.game.interactions.distances[my_actor_index, target_actor_index]

        # Case where the target is at zero distance (Should not happen once ship-ship
        # collisions are implemented)
        if distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]

        return direction, 2 * distance
