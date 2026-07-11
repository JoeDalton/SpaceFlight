import logging

import numpy as np

from space_flight import DEBUG_DELETION, RECORD_GAME
from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Personality
from space_flight.utils.state_machine import StateMachine

LOGGER = logging.getLogger()


class GenericNavigator:
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that controls the pawn
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        self.game = game
        self.pawn: Pawn = pawn
        self.personality: dict = personality
        self.debug = debug
        # The current behaviour is the navigator's FSM state ("idle", "pursuit",
        # "strafe_ingress", ...); behaviour_duration_s is its time-in-state.
        self.behaviour_sm = StateMachine(
            initial_state="idle", clock=self.game.game_time.get_current_time
        )
        self.last_update_time = self.game.game_time.get_current_time()
        # Sub-state of an ENGAGE (e.g. the strafe run's phase). Reset to "" by the
        # non-engage intents. Initialised here so it is always defined.
        self.engage_phase = ""
        # Per-run phase offset for the evasive weave, so successive runs (and the
        # weave itself) are not a predictable clean sinusoid. Reseeded when a run
        # starts (see the strafe ingress).
        self.weave_phase_rad = 0.0

    @property
    def behaviour(self) -> str:
        """The current behaviour (the behaviour state machine's state)."""
        return self.behaviour_sm.state

    @property
    def behaviour_duration_s(self) -> float:
        """How long the current behaviour has been running."""
        return self.behaviour_sm.time_in_state_s

    def navigate(self, intent: int, target_dict: dict):
        """
        Turns the tactician's intent and collision avoidance into explicit directions

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: Explicit directions
        """
        raise NotImplementedError

    def record_behaviour(self, behaviour: str):
        """
        Record which behaviour is currently running and for how long.

        TODO: Somehow manage to commit to a behaviour for a certain time ?
        TODO: Not necessary anymore ?

        :param behaviour: A str describing the behaviour currently in play
        """
        current_time = self.game.game_time.get_current_time()
        # The state machine resets time-in-state on an actual change and accrues it
        # otherwise; a request for the current behaviour is a no-op.
        changed = self.behaviour_sm.request(behaviour)
        if changed and self.debug:
            LOGGER.info(
                f"Navigator {self.pawn.parent.name} switched to behaviour {behaviour}"
            )
        # Kept for the spiral accumulator in check_extend_conditions, which measures
        # time between navigator frames.
        self.last_update_time = current_time

        # Step-by-step recording of the navigator phase, for forensic analysis.
        if RECORD_GAME and getattr(self.pawn.parent, "record", False):
            name = self.pawn.parent.name
            self.game.record.record(f"{name}_behaviour", self.behaviour_sm.state)
            self.game.record.record(
                f"{name}_behaviour_duration_s",
                float(self.behaviour_sm.time_in_state_s),
            )

    def compute_constant_angle_pursuit(
        self, direction: np.ndarray, distance_m: float, lateral_speed_vector: np.ndarray
    ) -> np.ndarray:
        """
        Constant Angle Pursuit (CAP)
        Bring lateral velocity to zero
        Good for closing in from a long distance
        Also good for missiles until the end

        :param direction: The direction of the target
        :param distance_m: Its distance from self
        :param lateral_speed_vector: Its relative velocity on the lateral plane
        :return: The direction to point to
        """
        # TODO Dynamic CAP strength, should vary with distance/closing_speed
        cap_strength_s = 1.0  # Or =1/omega_max_radps
        desired_vector = direction * distance_m - cap_strength_s * lateral_speed_vector
        desired_vector_norm = np.linalg.norm(desired_vector)
        # Norm can't be zero if distance != 0
        return desired_vector / desired_vector_norm

    def compute_lead_pursuit(
        self,
        target_current_position: np.ndarray,
        target_current_speed: np.ndarray,
        lead_time_s: float,
    ) -> np.ndarray:
        """
        Intercepts the target by pointing to its future position
        If the lead time is null, it's pure pursuit
        If the lead time is negative, it's a lag pursuit

        :param target_current_position: The absolute position of the target
        :param target_current_speed: Its absolute speed
        :return: The direction to point to
        """
        target_future_position = (
            target_current_position + target_current_speed * lead_time_s
        )

        # Compute direction to point to
        target_future_direction = target_future_position - self.pawn.position
        target_future_distance_m = np.linalg.norm(target_future_direction)
        if target_future_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            target_future_direction = np.zeros(3)
        else:
            target_future_direction /= target_future_distance_m

        return target_future_direction

    def compute_evasive_weave(
        self,
        base_direction: np.ndarray,
        up_reference: np.ndarray,
        amplitude: float,
        frequency_hz: float,
    ) -> np.ndarray:
        """
        Superimpose a lateral weave on an approach direction so the ship is a
        harder firing solution while still net-closing.

        The weave is in the plane perpendicular to ``up_reference`` (so it does not
        change altitude when that reference is the surface normal), oscillates with
        ``behaviour_duration_s`` plus the per-run :attr:`weave_phase_rad`, and its
        strength is set by ``amplitude`` (the caller ramps that down as the target
        nears, which also steadies the nose for firing).

        :param base_direction: The unit approach direction to weave around
        :param up_reference: The axis kept free of weave (world up or surface normal)
        :param amplitude: Lateral strength added to the unit direction
        :param frequency_hz: Weave frequency
        :return: The weaved unit direction (or ``base_direction`` if degenerate)
        """
        if amplitude <= 0.0:
            return base_direction
        lateral = np.cross(base_direction, up_reference)
        lateral_norm = np.linalg.norm(lateral)
        if lateral_norm < 1e-4:
            return base_direction
        lateral /= lateral_norm

        offset = amplitude * np.sin(
            2 * np.pi * frequency_hz * self.behaviour_duration_s + self.weave_phase_rad
        )
        weaved = base_direction + offset * lateral
        weaved_norm = np.linalg.norm(weaved)
        if weaved_norm < 1e-4:
            return base_direction
        return weaved / weaved_norm

    def clean(self):
        self.pawn = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")
