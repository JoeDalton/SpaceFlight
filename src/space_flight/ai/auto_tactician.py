import logging
from enum import Enum, auto
from typing import Tuple

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import REFERENCE_DISTANCE_M
from space_flight.utils import get_time_step

LOGGER = logging.getLogger()


# TODO make this probalistic to avoid everyone update at the same time
INTENT_UPDATE_DELAY_S = 1.0


class Intent(Enum):
    """
    Definition of the possile intent states
    """

    ENGAGE = auto()
    EVADE = auto()
    DISENGAGE = auto()
    REGROUP = auto()
    PATROL = auto()
    IDLE = auto()


class AutoTactician:
    """
    A very basic Finite State Machine to define the intents of the bots
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
            "min_fighting_shape": 2,
            "min_engagement_score": 0.5,
            "primary_target_engagement_multiplier": 5.0,
            "max_threat_score": 0.97,
        },
        weights: dict = {
            "engage": {
                "distance": 0.2,
                "forward": 1.0,
                "health": 0.0,  # TODO
                "ally_threat": 0.0,  # TODO
                "primary_target": 0.0,  # TODO
            },
            "evade": {
                "distance": 0.1,
                "forward": 1.0,
            },
        },
        debug: bool = False,
    ):
        self.app = app
        self.ship = ship
        self.intent = Intent.IDLE  # Current state
        self.target_dict = {}  # Current target
        self.primary_target = None  # Assigned by squad tactics
        self.time_since_update = 0.0
        self.time_since_commitment = 1000.0
        # Bot personality/role:
        # - commitment times (hysteresis)
        # - transition thresholds (aggresivity/recklessness)
        # - behaviour biases
        self.commitment_times = commitment_times
        self.thresholds = thresholds

        # Count selection weights
        self.weights = weights
        self.weights["engage"]["inv_total"] = 1.0 / np.sum(
            list(self.weights["engage"].values())
        )
        self.weights["evade"]["inv_total"] = 1.0 / np.sum(
            list(self.weights["evade"].values())
        )
        self.debug = debug

    def think(self):
        """
        Evaluates the intent of the bot at the correct frequency
        """
        dt = get_time_step()
        self.time_since_update += dt
        self.time_since_commitment += dt
        if (
            self.time_since_update >= INTENT_UPDATE_DELAY_S
            and self.time_since_commitment >= self.commitment_times[self.intent]
        ):
            self.time_since_update = 0.0
            intent, target_dict = self.update_intent()
            if (
                intent != self.intent
                or target_dict["target_id"] != self.target_dict["target_id"]
            ):
                if self.debug:
                    LOGGER.info(
                        f"Tactician switched to intent {intent}, target {target_dict}"
                    )
                self.time_since_commitment = 0.0
                self.intent = intent
                self.target_dict = target_dict
        return self.intent, self.target_dict

    def update_intent(self) -> Tuple[int, dict]:
        """
        Evaluates the tactic situation around the bot.

        For each foe, score its value as a threat or as a prey.
        Also score the bot's own fighting shape

        TODO: include role/squad strategy biases

        TODO: See if I can remove repeated computations
        TODO: Idem to pass to the navigator

        Finally, evaluates the intent of the bot with priorites
        """
        # Find current actor index of self
        my_actor_index = self.app.interactions.get_actor_index_from_id(self.ship.id)

        # Check if bot is threatened
        highest_threat_dict = self.evaluate_threats(my_actor_index)
        if highest_threat_dict["score"] >= self.thresholds["max_threat_score"]:
            return Intent.EVADE, highest_threat_dict

        # Check if the bot's ship is in good enough shape to continue fighting
        fighting_shape = self.evaluate_fighting_shape()
        if fighting_shape <= self.thresholds["min_fighting_shape"]:
            foes_center_dict = self.evaluate_team_center(team="foes")
            foes_center_dict["target_id"] = Intent.DISENGAGE
            return Intent.DISENGAGE, foes_center_dict

        # Check if bot has a good enough target to engage
        best_prey_dict = self.evaluate_preys(my_actor_index)
        if best_prey_dict["score"] >= self.thresholds["min_engagement_score"]:
            return Intent.ENGAGE, best_prey_dict

        # Check if bot has patrol orders
        if len(self.ship.parent.navigator.waypoints) != 0:
            return Intent.PATROL, {"target_id": Intent.PATROL}

        # Nothing specific to do for now. Regroup with friends
        friends_center_dict = self.evaluate_team_center(team="friends")
        friends_center_dict["target_id"] = Intent.REGROUP
        return Intent.REGROUP, friends_center_dict

    def evaluate_fighting_shape(self) -> float:
        """
        Evaluates the fighting shape of the bot
        TODO: add an "energy" mechanic ?
        """
        return 0.5 * self.ship.health + self.ship.shield

    def evaluate_threats(self, my_actor_index: int) -> dict:
        """
        Find the most threatening among all foes and return it with its threat score
        Also find the center of all foes for disengagement

        A threat is high if it :
        - Is close (in range)
        - Holds self in cone of fire
        """

        interact_mask = self.app.interactions.interact[my_actor_index, :]
        distances = self.app.interactions.distances[my_actor_index, :]

        # Is target aligned towards me ?
        alignments = self.app.interactions.alignments[:, my_actor_index]

        # Distance contribution
        with np.errstate(divide="ignore", invalid="ignore"):  # Hide /0 warning
            distance_scores = np.clip(
                a=REFERENCE_DISTANCE_M / distances, a_max=1.0, a_min=0.0
            )

        # Forwardness contribution (1 if forward, 0 if backward,0.5 at 90°)
        forward_scores = 0.5 + 0.5 * alignments

        # Assemble all contributions
        threat_scores = (
            interact_mask
            * (
                distance_scores * self.weights["evade"]["distance"]
                + forward_scores * self.weights["evade"]["forward"]
            )
            * self.weights["evade"]["inv_total"]
        )

        # Select highest scoring prey
        max_threat_score_idx = np.nanargmax(threat_scores)
        max_threat_score = threat_scores[max_threat_score_idx]

        highest_threat_dict = {
            "score": max_threat_score,
            "target_id": self.app.interactions.actors[max_threat_score_idx].id,
        }

        return highest_threat_dict

    def evaluate_preys(self, my_actor_index: int) -> dict:
        """
        Find the most vulnerable among all foes and return it
        with its vulnerability score

        Ideal prey is:
        - Not too far
        - Mostly forward
        - Low on health -- TODO
        - A primary target -- TODO
        - Threatening an ally -- TODO

        TODO: Add a multiplier bonus for targets threatening an ally and primary target
        """
        interact_mask = self.app.interactions.interact[my_actor_index, :]
        distances = self.app.interactions.distances[my_actor_index, :]
        alignments = self.app.interactions.alignments[my_actor_index, :]

        # Distance contribution
        with np.errstate(divide="ignore", invalid="ignore"):  # Hide /0 warning
            distance_scores = np.clip(
                a=REFERENCE_DISTANCE_M / distances, a_max=1.0, a_min=0.0
            )  # TODO get from previous calc in threats

        # Forwardness contribution (1 if forward, 0 if backward,0.5 at 90°)
        forward_scores = 0.5 + 0.5 * alignments

        # Health status contribution TODO
        health_scores = 1.0

        # Ally threatening contribution TODO
        ally_threatening_scores = 1.0

        # Primary target contribution TODO
        primary_target_scores = 1.0

        # Assemble all contributions
        prey_scores = (
            interact_mask
            * (
                distance_scores * self.weights["engage"]["distance"]
                + forward_scores * self.weights["engage"]["forward"]
                + health_scores * self.weights["engage"]["health"]
                + ally_threatening_scores * self.weights["engage"]["ally_threat"]
                + primary_target_scores * self.weights["engage"]["primary_target"]
            )
            * self.weights["engage"]["inv_total"]
        )

        # Select highest scoring prey
        max_prey_score_idx = np.nanargmax(prey_scores)
        max_prey_score = prey_scores[max_prey_score_idx]

        best_prey_dict = {
            "score": max_prey_score,
            "target_id": self.app.interactions.actors[max_prey_score_idx].id,
        }

        return best_prey_dict

    def evaluate_team_center(self, team: str) -> np.ndarray:
        """
        Find the center of gravity of the "friends" or "foes" team
        """
        my_team = self.ship.team
        n_actor_in_team = 0
        center = np.zeros(3)
        if team == "friends":
            for actor in self.app.interactions.actors:
                if actor.team == my_team and actor != self.ship:
                    center += actor.position
                    n_actor_in_team += 1
        elif team == "foes":
            for actor in self.app.interactions.actors:
                if actor.team != my_team and actor.team != 0:
                    center += actor.position
                    n_actor_in_team += 1
        else:
            raise ValueError(f"Allowed teams: `friends` and `foes`. Current: {team}")

        # No division if there is no one in the team
        if n_actor_in_team == 0:
            return {"position": center}

        return {"position": center / n_actor_in_team}

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")
