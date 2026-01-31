import logging
from enum import Enum, auto

# from typing import List

# import numpy as np

# from space_flight import DEBUG_DELETION, DISTANCE_TOLERANCE_M
# from space_flight.utils import rotate_single_vector

LOGGER = logging.getLogger()

INTENT_UPDATE_DELAY_S = 1.0

ALIGNMENT_WEIGHT = 1.0
RELATIVE_VELOCITY_WEIGHT = 0.0
REFERENCE_DISTANCE_M = 500
REFERENCE_VELOCITY_MPS = 1000
SCORE_THRESHOLD_FOR_ACTION = 0.1
SHOOTING_MAX_DISTANCE = 500
SHOOTING_MIN_COS_ANGLE = 0.96


class Intent(Enum):
    """
    Definition of the possile states
    """

    ENGAGE = auto()
    EVADE = auto()
    DISENGAGE = auto()
    REGROUP = auto()
    PATROL = auto()
    IDLE = auto()


class AutoTactician:
    """
    A Finite State Machine to define the intents of the bots
    """

    def __init__(
        self,
        app,
        ship,
        commitment_times: dict = {
            Intent.ENGAGE: 3.0,
            Intent.EVADE: 1.0,
            Intent.DISENGAGE: 5.0,
            Intent.REGROUP: 3.0,
            Intent.PATROL: 3.0,
            Intent.IDLE: 0.1,
        },
        thresholds: dict = {
            "low_shield": 2,
            "min_engagement_score": 0.25,
            "primary_target_engagement_multiplier": 2.0,
            "max_threat_score": 0.25,
        },
    ):
        self.app = app
        self.ship = ship
        self.intent = Intent.IDLE  # Current state
        self.target = None  # Current target
        self.primary_target = None  # Assigned by squad tactics
        self.time_since_update = 0.0
        self.time_since_commitment = 1000.0
        # Bot personality/role:
        # - commitment times (hysteresis)
        # - transition thresholds (aggresivity/recklessness)
        self.commitment_times = commitment_times
        self.thresholds = thresholds

    def think(self):
        """
        Evaluates the intent of the bot at the correct frequency
        """
        dt = self.app.clock.dt
        self.time_since_update += dt
        self.time_since_commitment += dt
        if self.time_since_update >= INTENT_UPDATE_DELAY_S:
            # TODO: Move commitment time check here after debug for better perf
            self.time_since_update = 0.0
            intent, target = self.update_intent()
            if self.time_since_commitment >= self.commitment_times[self.intent] and (
                intent != self.intent or target != self.target
            ):
                self.time_since_commitment = 0.0
                self.intent = intent
                self.target = target

    def update_intent(self):
        """
        Evaluates the intent of the bot with priorites
        """
        context: dict = self.evaluate_context()

        # Check if bot is threatened
        for threat in context["threats"]:
            if threat["score"] >= self.thresholds["max_threat_score"]:
                return Intent.EVADE, threat["target"]

        # Check if the bot's ship is in good enough shape to continue fighting
        if context["shield"] <= self.thresholds["low_shield"]:
            return Intent.DISENGAGE

        # Check if bot has a good enough target to engage
        for threat in context["threats"]:
            if threat["score"] >= self.thresholds["max_threat_score"]:
                return Intent.EVADE, threat["target"]
