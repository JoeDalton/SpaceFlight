from space_flight.actors.pawn import Pawn
from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician
from space_flight.utils import smooth_step_up

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
        Choose how to attack the prey. First the weapon (guns vs. a limited bomb,
        by suitability scoring), then the geometry: bomb -> BOMB; guns + a
        slow/immobile target -> STRAFE; guns + an agile target -> PURSUIT.

        :param target_id: The chosen prey's id
        :return: The attack mode to carry in the target dict
        """
        try:
            target_index = self.game.interactions.get_actor_index_from_id(target_id)
            target = self.game.interactions.actors[target_index]
        except (ValueError, KeyError, TypeError):
            return AttackMode.PURSUIT

        if self._choose_weapon(target) == "bomb":
            return AttackMode.BOMB

        mobility = getattr(target, "mobility", 1.0)
        threshold = self.personality["tactician"]["strafe_mobility_threshold"]
        try:
            is_slow = mobility <= threshold
        except TypeError:
            # Non-numeric mobility (e.g. a mocked target): default to the chase.
            return AttackMode.PURSUIT
        return AttackMode.STRAFE if is_slow else AttackMode.PURSUIT

    def _choose_weapon(self, target) -> str:
        """
        Pick the weapon system for a target by suitability: a limited bomb only
        beats guns on a target that is stationary, tough AND valuable, with supply
        to spare. Any non-numeric input (e.g. a mocked target) or no supply falls
        back to guns.

        :param target: The prey actor
        :return: "bomb" or "guns"
        """
        bomb_supply = getattr(self.pawn, "bomb_supply", 0)
        scoring = self.personality["tactician"]["bomb_scoring"]
        try:
            if bomb_supply <= 0:
                return "guns"
            mobility = float(getattr(target, "mobility", 1.0))
            hardness_input = float(getattr(target, "health", 0.0)) + float(
                target.shield_level
            )
            hardness = smooth_step_up(
                hardness_input, scoring["hardness_step"], scoring["hardness_slope"]
            )
            is_primary = getattr(target, "id", None) in self.primary_target_ids
            value_raw = (
                self.personality["tactician"]["primary_target_engagement_multiplier"]
                if is_primary
                else 1.0
            )
            value = smooth_step_up(
                value_raw, scoring["value_step"], scoring["value_slope"]
            )
            supply_factor = smooth_step_up(
                float(bomb_supply), scoring["supply_step"], scoring["supply_slope"]
            )
            stationarity = 1.0 - mobility
            worth = hardness * value
            s_gun = scoring["gun_base"] + scoring["gun_soft"] * (1.0 - hardness)
            s_bomb = scoring["bomb_scale"] * stationarity * worth * supply_factor
            return "bomb" if s_bomb > s_gun else "guns"
        except (TypeError, ValueError, AttributeError):
            return "guns"
