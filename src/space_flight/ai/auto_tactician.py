import logging
from typing import Tuple

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import Intent, Personality
from space_flight.utils import smooth_step_down

LOGGER = logging.getLogger()


# TODO make this probabilistic to avoid everyone update at the same time ?
INTENT_UPDATE_DELAY_S = 0.5

# TODO Add an intent to go back to the fight area if too far

# TODO (Where ?) Make the ships that disengaged and are sufficiently far disappear
# from the scene


class AutoTactician:
    """
    A very basic Finite State Machine to define the intents of the bots
    """

    def __init__(
        self,
        game,
        ship,
        personality: dict = Personality.DEFAULT,
        debug: bool = False,
    ):
        self.game = game
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
        self.personality = personality

        self.debug = debug

    def think(self):
        """
        Evaluates the intent of the bot at the correct frequency
        """
        dt = self.game.game_time.get_time_step()
        self.time_since_update += dt
        self.time_since_commitment += dt
        if (self.time_since_update >= INTENT_UPDATE_DELAY_S) and (
            self.time_since_commitment
            >= self.personality["tactician"]["commitment_times"][self.intent]
        ):
            self.time_since_update = 0.0
            intent, target_dict = self.update_intent()
            if (intent != self.intent) or (
                target_dict["target_id"] != self.target_dict["target_id"]
            ):
                if self.debug:
                    LOGGER.info(
                        f"Tactician {self.ship.parent.name} switched to intent "
                        f"{intent}, target {target_dict}"
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

        Finally, evaluates the intent of the bot with priorites
        """
        # Find current actor index of self
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.ship.id)

        # Check if bot is threatened
        highest_threat_dict = self.evaluate_threats(my_actor_index)
        if (
            highest_threat_dict["score"]
            >= self.personality["tactician"]["max_threat_score"]
        ):
            return Intent.EVADE, highest_threat_dict

        # Check if the bot's ship is in good enough shape to continue fighting
        fighting_shape = self.evaluate_fighting_shape()
        if fighting_shape <= self.personality["tactician"]["min_fighting_shape"]:
            foes_center_dict = self.evaluate_team_center(team="foes")
            foes_center_dict["target_id"] = Intent.DISENGAGE
            return Intent.DISENGAGE, foes_center_dict

        # Check if bot has a good enough target to engage
        best_prey_dict = self.evaluate_preys(my_actor_index)
        if (
            best_prey_dict["score"]
            >= self.personality["tactician"]["min_engagement_score"]
        ):
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

        interact_mask = self.game.interactions.interact[my_actor_index, :]
        distances = self.game.interactions.distances[my_actor_index, :]

        # Is target aligned towards me ?
        alignments = self.game.interactions.alignments[:, my_actor_index]

        # Distance contribution
        distance_scores = smooth_step_down(
            x=distances,
            x_step=self.personality["tactician"]["prey_cutoff_distance"],
            slope=0.01,
        )

        # Forwardness contribution
        forward_scores = self.compute_alignment_score(
            alignments=alignments, is_hunter=False
        )

        # Assemble all contributions
        threat_scores = interact_mask * distance_scores * forward_scores

        # Select highest scoring prey
        max_threat_score_idx = np.nanargmax(threat_scores)
        max_threat_score = threat_scores[max_threat_score_idx]

        highest_threat_dict = {
            "score": max_threat_score,
            "target_id": self.game.interactions.actors[max_threat_score_idx].id,
        }

        return highest_threat_dict

    def evaluate_preys(self, my_actor_index: int) -> dict:
        """
        Find the most vulnerable among all foes and return it
        with its vulnerability score

        Ideal prey is:
        - Not too far
        - Mostly forward
        - Low on health ? -- TODO
        - A primary target -- TODO
        - Threatening a protected ally -- TODO

        TODO: Add a multiplier bonus for targets threatening an ally and primary target
        """
        interact_mask = self.game.interactions.interact[my_actor_index, :]
        distances = self.game.interactions.distances[my_actor_index, :]
        alignments = self.game.interactions.alignments[my_actor_index, :]

        # Distance contribution
        distance_scores = smooth_step_down(
            x=distances,
            x_step=self.personality["tactician"]["hunter_cutoff_distance"],
            slope=0.01,
        )

        # Forwardness contribution
        forward_scores = self.compute_alignment_score(
            alignments=alignments, is_hunter=True
        )

        # Health status contribution TODO
        health_scores = 1.0

        # Ally threatening contribution TODO
        ally_threatening_scores = 1.0

        # Primary target contribution TODO
        primary_target_scores = 1.0

        # Assemble all contributions
        prey_scores = (
            interact_mask
            * distance_scores
            * forward_scores
            * health_scores
            * ally_threatening_scores
            * primary_target_scores
        )

        # Select highest scoring prey
        max_prey_score_idx = np.nanargmax(prey_scores)
        max_prey_score = prey_scores[max_prey_score_idx]

        best_prey_dict = {
            "score": max_prey_score,
            "target_id": self.game.interactions.actors[max_prey_score_idx].id,
        }

        return best_prey_dict

    def compute_alignment_score(
        self, alignments: np.ndarray, is_hunter: bool
    ) -> np.ndarray:
        """
        Computes a prey/threat score based on the cos of the angle between the forward
        direction of the hunter and the hunter-prey vector

        :param alignments: The array of cos angles
        :param is_hunter: If true, use the hunter values. Else use the prey values
        :return: The array of scores
        """
        if is_hunter:
            focus_factor = self.personality["tactician"]["hunter_angular_focus"]
        else:
            focus_factor = self.personality["tactician"]["prey_angular_focus"]
        # Base forwardness contribution
        # (1 if prey is forward, 0 if backward, 0.5 at 90°)
        base = 0.5 + 0.5 * alignments
        # The more focused, the less angled target are scored
        forward_scores = 1 + (base - 1) * focus_factor
        return forward_scores

    def evaluate_team_center(self, team: str) -> np.ndarray:
        """
        Find the center of gravity of the "friends" or "foes" team
        """
        my_team = self.ship.team
        n_actor_in_team = 0
        center = np.zeros(3)
        if team == "friends":
            for actor in self.game.interactions.actors:
                if actor.team == my_team and actor != self.ship:
                    center += actor.position
                    n_actor_in_team += 1
        elif team == "foes":
            for actor in self.game.interactions.actors:
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
