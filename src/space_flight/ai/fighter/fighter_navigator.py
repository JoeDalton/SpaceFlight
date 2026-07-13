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
        target_dict["attack_mode"]):

        - PURSUIT (default): constant-angle chase, good against agile prey.
        - STRAFE: a committed ingress -> attack -> break -> reposition run for
          slow or immobile targets.
        - BOMB: overfly a slow/immobile target and drop a bomb along the belly.

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
        Enrich target_dict in place with the per-frame engagement geometry
        shared by every attack mode, so all pattern methods take the single
        target_dict.

        :param target_dict: The tactician's target info (needs target_id);
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
        ingress -> attack -> break -> reposition -> ingress that runs in fast,
        fires, peels off and comes around again, instead of spiralling like a chase.

        For a surface-mounted prey (surface_normalsurface_hit_point in
        target_dict) the ingress becomes a low-altitude corridor (a run at a set
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
        :param factor_key: The fraction key (e.g. "attack_speed_factor")
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
        Bombing run against a slow/immobile target: a committed cycle
        ingress -> approach -> run -> break -> reposition.

        - The ingress is normal (banking) flight that gets the bomber onto the
          target's track line: it swings to an entry point ``entry_distance_m`` behind
          the target when ahead/abeam, then follows the track line in (pure-pursuit on
          a carrot up the line) at ``run_altitude_m``, using fast banked turns to null
          the cross-track offset the belly-down run could never remove.
        - The approach flies belly-down (the up-reference turns the fighter pilot into
          the capital-ship pilot: roll +Z to the reference up, yaw+pitch to aim)
          following the track line in (carrot pure-pursuit at run altitude), so the
          belly is settled and on the line before the run. It is entered only once on
          the line; if the bomber drifts off, it drops back to the ingress.
        - The run keeps that belly-down attitude, still following the (curving) track
          line over the target at run altitude; the belly (-Z) bomb velocity sweeps
          through the target and the cone release fires. Then it peels off.

        The up-reference (approach/run) is the surface normal for a surface-mounted
        prey, otherwise world up.

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

        # Belly (-Z) points down the up-reference during the RUN: the surface normal
        # for a surface prey, else world up (a level drop straight down).
        up_reference = (
            surface_normal
            if surface_normal is not None
            else self.game.scene.up_direction
        )

        # Entry point: entry_distance_m behind the target along its track, at run
        # altitude. "Behind" follows the target's velocity when it is moving, else the
        # bomber's own bearing to a stationary target (see _bomb_track_direction).
        track_direction = self._bomb_track_direction(
            target_speed, direction, up_reference, bomb
        )
        entry_point = (
            target_position
            - track_direction * bomb["entry_distance_m"]
            + up_reference * bomb["run_altitude_m"]
        )

        # Along-track position (negative = behind the target) and the horizontal
        # cross-track offset from the target's track line -- the two quantities that
        # decide when the bomber is lined up for a clean overfly.
        relative = self.pawn.position - target_position
        along_track_m = float(np.dot(relative, track_direction))
        cross_track_m = self._bomb_cross_track(relative, track_direction, up_reference)

        phase = self.behaviour if self.behaviour.startswith("bomb_") else "bomb_ingress"

        if phase == "bomb_ingress":
            # Hand off to the belly-down approach only once actually lined up: behind
            # the target AND on its track line (small cross-track). Until then the
            # ingress banks -- fast turns the belly-down run can't make -- to null the
            # cross-track, which is the whole point of the ingress.
            if along_track_m < 0.0 and cross_track_m < bomb["lateral_tolerance_m"]:
                self.behaviour_sm.request("bomb_approach")
                return self._bomb_approach(
                    target_position,
                    track_direction,
                    up_reference,
                    along_track_m,
                    bomb,
                )
            self.behaviour_sm.request("bomb_ingress")
            return self._bomb_ingress(
                entry_point,
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb,
            )

        if phase == "bomb_approach":
            # Lost the line (no longer behind, or drifted off the track beyond the
            # recovery band): the belly-down approach yaws too slowly to re-acquire, so
            # drop back to the fast-banking ingress line-follow.
            if along_track_m >= 0.0 or cross_track_m > bomb["lateral_recovery_m"]:
                self.behaviour_sm.request("bomb_ingress")
                return self._bomb_ingress(
                    entry_point,
                    target_position,
                    track_direction,
                    up_reference,
                    along_track_m,
                    bomb,
                )
            # Lock onto the belly-down run once within lock_time_s of flight to the
            # target (at the bomber's current speed) AND still on the line, so the run
            # only commits from a clean overfly setup.
            lock_distance_m = max(
                np.linalg.norm(self.pawn.speed) * bomb["lock_time_s"],
                TARGET_DISTANCE_TOLERANCE_M,
            )
            if (
                distance_m <= lock_distance_m
                and cross_track_m < bomb["lateral_tolerance_m"]
            ):
                self.behaviour_sm.request("bomb_run")
                return self._bomb_run(
                    target_position,
                    track_direction,
                    up_reference,
                    along_track_m,
                    bomb,
                )
            self.behaviour_sm.request("bomb_approach")
            return self._bomb_approach(
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb,
            )

        if phase == "bomb_run":
            # Release once the bomb's velocity sweeps the target, then break.
            if self.compute_release_condition(target_position, target_speed, bomb):
                self.pawn.drop_bomb()
                self.behaviour_sm.request("bomb_break")
                return self._bomb_break(direction, bomb)
            # Overflew (or can't close) without a solution -> break and re-attack.
            if closing_speed_mps <= 0.0:
                self.behaviour_sm.request("bomb_break")
                return self._bomb_break(direction, bomb)
            self.behaviour_sm.request("bomb_run")
            return self._bomb_run(
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb,
            )

        if phase == "bomb_break":
            if self.behaviour_duration_s > bomb["break_duration_s"]:
                self.behaviour_sm.request("bomb_reposition")
                return self._bomb_reposition(direction, bomb)
            self.behaviour_sm.request("bomb_break")
            return self._bomb_break(direction, bomb)

        # bomb_reposition: extend out, then come around for another run.
        if (
            distance_m > bomb["reposition_distance_m"]
            and self.behaviour_duration_s > bomb["reposition_min_duration_s"]
        ):
            self.behaviour_sm.request("bomb_ingress")
            return self._bomb_ingress(
                entry_point,
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb,
            )
        self.behaviour_sm.request("bomb_reposition")
        return self._bomb_reposition(direction, bomb)

    def compute_release_condition(
        self, target_position: np.ndarray, target_speed: np.ndarray, bomb: dict
    ) -> bool:
        """
        Whether a bomb dropped this frame would hit the target.

        The bomb travels in a straight line (no gravity) at v_bomb = ship.speed -
        launch_speed * ship.up (i.e. the belly -Z plus inherited ship velocity),
        so it is forward-and-down. Release when the target -- led by the bomb's
        flight time to it (distance / |v_bomb|, the closing time at the bomb's true
        speed) -- lies within a tight cone of that velocity and in range. The lead
        makes the cone track the intercept point, so it can stay tight (accurate).

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

        to_target = target_position - self.pawn.position
        distance_m = np.linalg.norm(to_target)
        if distance_m > bomb["max_release_distance_m"]:
            return False

        # Lead the target by the bomb's flight time to it (distance / true bomb
        # speed), then aim the cone at that intercept point.
        flight_time_s = distance_m / v_bomb_norm
        to_intercept = (
            target_position + target_speed * flight_time_s
        ) - self.pawn.position
        to_intercept_norm = np.linalg.norm(to_intercept)
        if to_intercept_norm < TARGET_DISTANCE_TOLERANCE_M:
            return False
        aligned = (
            np.dot(to_intercept / to_intercept_norm, bomb_direction)
            > bomb["min_cos_release"]
        )
        return bool(aligned)

    def _bomb_aim(self, point: np.ndarray) -> np.ndarray:
        """Unit direction from the bomber to a world point (nose target)."""
        to_point = point - self.pawn.position
        to_point_norm = np.linalg.norm(to_point)
        if to_point_norm > TARGET_DISTANCE_TOLERANCE_M:
            return to_point / to_point_norm
        return self.pawn.forward

    def _bomb_track_direction(
        self,
        target_speed: np.ndarray,
        direction: np.ndarray,
        up_reference: np.ndarray,
        bomb: dict,
    ) -> np.ndarray:
        """
        The (horizontal) track direction used to place the entry point "behind" the
        target: the target's velocity direction when it is moving, else the bomber's
        current bearing to it so a stationary target still has a well-defined behind.
        Flattened against the reference up so the entry point sits purely at the run
        altitude, not tilted by a climbing target.
        """
        target_speed_norm = np.linalg.norm(target_speed)
        if target_speed_norm >= bomb["min_track_speed_mps"]:
            track = target_speed / target_speed_norm
        else:
            track = direction
        track = track - np.dot(track, up_reference) * up_reference
        track_norm = np.linalg.norm(track)
        # track is a (near-)unit vector, so compare against a small epsilon, not the
        # metres-scale distance tolerance: only fall back to the nose when the track
        # is (near-)parallel to the reference up (nothing horizontal left).
        if track_norm > 1e-6:
            return track / track_norm
        return self.pawn.forward

    def _bomb_cross_track(
        self,
        relative: np.ndarray,
        track_direction: np.ndarray,
        up_reference: np.ndarray,
    ) -> float:
        """
        The bomber's horizontal cross-track offset from the target's track line: the
        component of ``relative`` (bomber minus target) perpendicular to both the track
        and the reference up. This is the lateral miss that must be nulled before the
        belly-down run, since belly-down yaw is too slow to remove it during the pass.
        """
        cross = (
            relative
            - np.dot(relative, track_direction) * track_direction
            - np.dot(relative, up_reference) * up_reference
        )
        return float(np.linalg.norm(cross))

    def _bomb_line_carrot(
        self,
        target_position: np.ndarray,
        track_direction: np.ndarray,
        up_reference: np.ndarray,
        along_track_m: float,
        lookahead_m: float,
    ) -> np.ndarray:
        """
        Aim direction for a pure-pursuit follow of the target's track line: a carrot
        ``lookahead_m`` further up the line than the bomber's own along-track position,
        at run altitude. Because the track is the target's *instantaneous* velocity
        direction (recomputed every frame), the carrot swings with the target as it
        turns, so following it keeps the bomber on the curving track -- unlike a fixed
        linear lead, which points off the outside of the turn.
        """
        carrot = (
            target_position
            + track_direction * (along_track_m + lookahead_m)
            + up_reference * self.personality["navigator"]["bomb"]["run_altitude_m"]
        )
        return self._bomb_aim(carrot)

    def _bomb_ingress(
        self,
        entry_point: np.ndarray,
        target_position: np.ndarray,
        track_direction: np.ndarray,
        up_reference: np.ndarray,
        along_track_m: float,
        bomb: dict,
    ) -> Tuple[np.ndarray, float]:
        """
        Positioning leg (normal, banking flight -- NO up-reference, so it can turn fast
        to null the cross-track).

        When ahead of / abeam the target (along_track >= 0) it swings to the entry
        point behind the target to get onto the tail. Once behind, it follows the
        target's track line (carrot pure-pursuit) so the belly-down run can start on
        the line. The outer sensor sphere is dropped so the long-range look-ahead
        doesn't push the bomber off its own target.
        """
        self.collision_sensor.active_range = self.collision_sensor.n_spheres - 1
        speed = bomb["ingress_speed_factor"] * self.pawn.max_speed_mps
        if along_track_m >= 0.0:
            # Ahead / abeam: swing around to the entry point on the tail.
            return self._bomb_aim(entry_point), speed
        # Behind: follow the track line in.
        return (
            self._bomb_line_carrot(
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb["line_lookahead_m"],
            ),
            speed,
        )

    def _bomb_approach(
        self,
        target_position: np.ndarray,
        track_direction: np.ndarray,
        up_reference: np.ndarray,
        along_track_m: float,
        bomb: dict,
    ) -> Tuple[np.ndarray, float]:
        """
        Approach run: fly belly-down (publishes the up-reference, so the fighter pilot
        rolls +Z to the reference up and yaws/pitches to aim) following the target's
        track line in (carrot pure-pursuit at run altitude). Flying belly-down here --
        rather than banking in -- keeps the belly settled so the run starts clean;
        following the line (not a fixed lead) keeps it tracking a turning target. If
        the tail/line is lost, the caller falls back to the banking ingress. Avoidance
        is dwarfed and the outer sensor dropped for the close overfly.
        """
        self.up_reference = up_reference
        self.avoidance_weight_factor = self.personality["navigator"]["strafe"][
            "corridor_avoidance_factor"
        ]
        self.collision_sensor.active_range = self.collision_sensor.n_spheres - 1
        return (
            self._bomb_line_carrot(
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb["run_lookahead_m"],
            ),
            bomb["approach_speed_factor"] * self.pawn.max_speed_mps,
        )

    def _bomb_run(
        self,
        target_position: np.ndarray,
        track_direction: np.ndarray,
        up_reference: np.ndarray,
        along_track_m: float,
        bomb: dict,
    ) -> Tuple[np.ndarray, float]:
        """
        The committed delivery leg. Locks the roll to the reference up (publishes the
        up-reference, so the fighter pilot flies belly-down: roll only to level the
        wings to up_reference, yaw+pitch to aim, no banking) and follows the target's
        track line over it (carrot pure-pursuit at run altitude, short lookahead so it
        tracks a turning target tightly). The steady belly (-Z) bomb velocity sweeps
        through the target as it overflies -> the cone release fires. Dwarfs avoidance
        and drops the outer sensor sphere so it can overfly closely.
        """
        self.up_reference = up_reference
        self.avoidance_weight_factor = self.personality["navigator"]["strafe"][
            "corridor_avoidance_factor"
        ]
        self.collision_sensor.active_range = self.collision_sensor.n_spheres - 1
        return (
            self._bomb_line_carrot(
                target_position,
                track_direction,
                up_reference,
                along_track_m,
                bomb["run_lookahead_m"],
            ),
            bomb["run_speed_factor"] * self.pawn.max_speed_mps,
        )

    def _bomb_break(
        self, direction: np.ndarray, bomb: dict
    ) -> Tuple[np.ndarray, float]:
        """
        Peel away after the drop by turning back the way we came. Deliberately does
        NOT climb: a climbing break would ratchet the run altitude up pass after
        pass, so the bomber would end up bombing from far too high. Altitude is
        re-established by the ingress on the next pass.
        """
        return -direction, bomb["break_speed_factor"] * self.pawn.max_speed_mps

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
