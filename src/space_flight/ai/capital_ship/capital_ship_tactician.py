from space_flight.actors.pawn import Pawn
from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician

# TODO Add an intent to go back to the fight area if too far

# TODO (Where ?) Make the ships that disengaged and are sufficiently far disappear
# from the scene


class CapitalShipTactician(GenericTactician):
    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.CAPITAL_SHIP_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.scripted_prey_dict = {"active": False}

    def update_intent(self) -> tuple[int, dict]:
        """
        Evaluates the tactical situation around the bot.

        For each foe, score its value as a threat or as a prey.
        Also score the bot's own fighting shape

        TODO: include role/squad strategy biases

        Finally, evaluates the intent of the bot with priorites
        """
        # Check if the bot's ship is in good enough shape to continue fighting
        fighting_shape = self.evaluate_fighting_shape()
        if fighting_shape <= self.personality["tactician"]["min_fighting_shape"]:
            foes_center_dict = self.evaluate_team_center(team="foes")
            foes_center_dict["target_id"] = Intent.DISENGAGE
            return Intent.DISENGAGE, foes_center_dict

        # Check if bot has a prey.
        # Placeholder trigger: engagement is still scenario-scripted. Deriving it
        # from threat scoring (so capital ships pick their own orbit targets) is
        # left for a later pass, see the design doc.
        if self.scripted_prey_dict["active"]:
            self.scripted_prey_dict["attack_mode"] = AttackMode.ORBIT
            return Intent.ENGAGE, self.scripted_prey_dict

        # Check if bot has patrol orders
        if len(self.pawn.parent.navigator.waypoints) != 0:
            return Intent.PATROL, {"target_id": Intent.PATROL}

        # Check if bot has formation orders
        formation_dict = self.evaluate_formation()
        if formation_dict["active"] is True:
            return Intent.FORMATION, formation_dict

        # Nothing specific to do for now. Regroup with friends
        friends_center_dict = self.evaluate_team_center(team="friends")
        friends_center_dict["target_id"] = Intent.REGROUP
        return Intent.REGROUP, friends_center_dict

    # evaluate_fighting_shape is inherited from GenericTactician (uniform
    # health/shield_level).
