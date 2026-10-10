from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.actors.pawn import Pawn
from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# TODO Add an intent to go back to the fight area if too far

# TODO (Where ?) Make the ships that disengaged and are sufficiently far disappear
# from the scene


class MajorShipTactician(GenericTactician):
    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.ESCORT_SHIP_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.scripted_prey_dict = {"active": False}

    def update_intent(self) -> tuple[Intent, dict]:
        """
        Picks the intent by priority: disengage if in poor fighting shape, engage
        the scripted prey (ORBIT), hold formation (wingmen), patrol (leader),
        else regroup.

        TODO: include role/squad strategy biases

        :return: The intent and its target dict
        """
        # Check if the bot's ship is in good enough shape to continue fighting
        fighting_shape = self.evaluate_fighting_shape()
        if fighting_shape <= self.personality["tactician"]["min_fighting_shape"]:
            foes_center_dict = self.evaluate_team_center(team="foes")
            foes_center_dict["target_id"] = Intent.DISENGAGE
            return Intent.DISENGAGE, foes_center_dict

        # Placeholder trigger: engagement is scenario-scripted. TODO derive it
        # from threat scoring, so capital ships pick their own orbit targets.
        if self.scripted_prey_dict["active"]:
            self.scripted_prey_dict["attack_mode"] = AttackMode.ORBIT
            return Intent.ENGAGE, self.scripted_prey_dict

        # Check if bot has formation or patrol orders
        orders = self.evaluate_orders()
        if orders is not None:
            return orders

        # Nothing specific to do for now. Regroup with friends
        friends_center_dict = self.evaluate_team_center(team="friends")
        friends_center_dict["target_id"] = Intent.REGROUP
        return Intent.REGROUP, friends_center_dict
