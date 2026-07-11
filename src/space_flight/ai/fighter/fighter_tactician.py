from space_flight.actors.pawn import Pawn
from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician

# TODO Add an intent to go back to the fight area if too far

# TODO (Where ?) Make the ships that disengaged and are sufficiently far disappear
# from the scene


class FighterTactician(GenericTactician):
    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def update_intent(self) -> tuple[int, dict]:
        """
        Evaluates the tactical situation around the bot.

        For each foe, score its value as a threat or as a prey.
        Also score the bot's own fighting shape

        TODO: include role/squad strategy biases

        Finally, evaluates the intent of the bot with priorites
        """
        # Find current actor index of self
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)

        # Check if bot is directly threatened (highest priority action)
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
            best_prey_dict["attack_mode"] = self._select_attack_mode(
                best_prey_dict["target_id"]
            )
            return Intent.ENGAGE, best_prey_dict

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

    def _select_attack_mode(self, target_id) -> AttackMode:
        """
        Choose how to attack the prey: a STRAFE run against a slow/immobile target,
        otherwise the PURSUIT chase. The decision is on the target's (class-based)
        mobility, not its instantaneous speed.

        With guns the only Phase-1 weapon, this is purely the geometry choice; the
        BOMB weapon and its suitability scoring arrive in Phase 2.

        :param target_id: The chosen prey's id
        :return: The attack mode to carry in the target dict
        """
        try:
            target_index = self.game.interactions.get_actor_index_from_id(target_id)
            target = self.game.interactions.actors[target_index]
        except (ValueError, KeyError, TypeError):
            return AttackMode.PURSUIT

        mobility = getattr(target, "mobility", 1.0)
        threshold = self.personality["tactician"]["strafe_mobility_threshold"]
        try:
            is_slow = mobility <= threshold
        except TypeError:
            # Non-numeric mobility (e.g. a mocked target): default to the chase.
            return AttackMode.PURSUIT
        return AttackMode.STRAFE if is_slow else AttackMode.PURSUIT
