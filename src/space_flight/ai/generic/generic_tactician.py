import logging

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent
from space_flight.utils import smooth_step_down
from space_flight.utils.state_machine import StateMachine

LOGGER = logging.getLogger()


class GenericTactician:
    """
    A Finite State Machine to define the intents of the bots
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict,
        debug: bool = False,
    ):
        self.game = game
        self.pawn = pawn
        # The intent is the FSM state; the personality's ``commitment_times`` are
        # its per-state minimum dwell (hysteresis), checked dynamically in think()
        # so a runtime personality swap takes effect.
        self.intent_sm = StateMachine(
            initial_state=Intent.IDLE,
            clock=self.game.game_time.get_current_time,
        )
        self.target_dict = {}  # Current target
        self.primary_target_ids = []  # Assigned by squad tactics or level scenario
        self.time_since_update_s = 0.0
        # Bot personality/role:
        # - commitment times (hysteresis)
        # - transition thresholds (aggresivity/recklessness)
        # - behaviour biases
        self.personality = personality
        self.debug = debug

    @property
    def intent(self):
        """The current intent (the intent state machine's state)."""
        return self.intent_sm.state

    def think(self):
        """
        Evaluates the intent of the bot at the correct frequency
        """
        dt = self.game.game_time.get_time_step()
        self.time_since_update_s += dt
        commitment_time_s = self.personality["tactician"]["commitment_times"][
            self.intent_sm.state
        ]
        # TODO make this probabilistic to avoid everyone update at the same time ?
        if (
            self.time_since_update_s
            >= self.personality["tactician"]["intent_update_delay"]
        ) and (self.intent_sm.time_in_state_s >= commitment_time_s):
            self.time_since_update_s = 0.0
            intent, target_dict = self.update_intent()
            if (
                (intent != self.intent_sm.state)
                or (target_dict.get("target_id") != self.target_dict.get("target_id"))
                or (  # Changing formation position, for ships only
                    target_dict.get("formation_index")
                    != self.target_dict.get("formation_index")
                )
                or (  # Switching weapon (e.g. bombs depleted -> guns)
                    target_dict.get("attack_mode")
                    != self.target_dict.get("attack_mode")
                )
            ):
                if self.debug:
                    LOGGER.info(
                        f"Tactician {self.pawn.parent.name} switched to intent "
                        f"{intent}, target {target_dict}"
                    )
                if intent != self.intent_sm.state:
                    # New intent: transition (resets the commitment timer).
                    self.intent_sm.request(intent, force=True)
                else:
                    # Same intent, new target/formation: recommit to the decision.
                    self.intent_sm.reset_timer()
                self.target_dict = target_dict

        # Register target_id if in offensive mode so the auto-aim can do its job
        if self.intent_sm.state == Intent.ENGAGE:
            self.pawn.target_id = self.target_dict["target_id"]
        else:
            self.pawn.target_id = None

        return self.intent_sm.state, self.target_dict

    def update_intent(self):
        """
        Evaluates the tactical situation around the bot and computes the bot's intent
        """
        raise NotImplementedError

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

        if max_threat_score == 0:
            return {"score": 0, "target_id": None}

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
        - Threatening a protected ally -- TODO using primary targets
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

        # Primary target contribution: modifies the interact mask
        primary_target_scores = np.ones(len(distances))
        for actor_idx, actor in enumerate(self.game.interactions.actors):
            if interact_mask[actor_idx]:
                if actor.id in self.primary_target_ids:
                    primary_target_scores[actor_idx] = self.personality["tactician"][
                        "primary_target_engagement_multiplier"
                    ]

        # Assemble all contributions
        prey_scores = (
            interact_mask
            * distance_scores
            * forward_scores
            * health_scores
            * primary_target_scores
        )

        # Select highest scoring prey
        max_prey_score_idx = np.nanargmax(prey_scores)
        max_prey_score = prey_scores[max_prey_score_idx]

        if max_prey_score == 0:
            return {"score": 0, "target_id": None}

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

    def evaluate_team_center(self, team: str) -> dict:
        """
        Find the center of gravity of the "friends" or "foes" team
        """
        my_team = self.pawn.team
        n_actor_in_team = 0
        center = np.zeros(3)
        if team == "friends":
            for actor in self.game.interactions.live_actors:
                if actor.team == my_team and actor != self.pawn:
                    center += actor.position
                    n_actor_in_team += 1
        elif team == "foes":
            for actor in self.game.interactions.live_actors:
                if actor.team != my_team and actor.team != 0:
                    center += actor.position
                    n_actor_in_team += 1
        else:
            raise ValueError(f"Allowed teams: `friends` and `foes`. Current: {team}")

        # No division if there is no one in the team
        if n_actor_in_team == 0:
            return {"position": center}

        return {"position": center / n_actor_in_team}

    def evaluate_formation(self) -> dict:
        """
        Finds whether the bot belongs to a wing formation and returns its leader
        and relative target position
        """
        if self.pawn.formation is None:
            # Does not belong to a formation. Not applicable
            return {"active": False}
        formation_index = self.pawn.formation.get_ship_index(self.pawn.id)
        if formation_index == 0:
            # Self is the leader of the formation. Not applicable
            return {"active": False}
        else:
            # Self belongs to a formation and is not the leader :
            # Activate formation and get the corresponding position
            return {
                "active": True,
                "target_id": self.pawn.formation.ship_ids[0],
                "formation_index": formation_index,
                "target_relative_position": self.pawn.formation.relative_positions[
                    formation_index
                ],
            }

    def evaluate_fighting_shape(self) -> float:
        """
        The bot's fitness to keep fighting: half its health plus its shield. Reads
        the uniform ``health``/``shield_level`` exposed by every pawn, so it works
        the same for fighters and capital ships.

        TODO: add an "energy" mechanic ? Health of subsystems ?

        :return: The fighting-shape score
        """
        return 0.5 * self.pawn.health + self.pawn.shield_level

    def clean(self):
        self.pawn = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")
