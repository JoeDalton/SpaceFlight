from __future__ import annotations

from typing import TYPE_CHECKING, Any

from space_flight.actors.pawn import Pawn
from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician
from space_flight.utils import smooth_step_up

if TYPE_CHECKING:
    from uuid import UUID

    from space_flight.game.flight_state import FlightState
    from space_flight.weapons.ordnance_launcher import OrdnanceLauncher

# The attack plan when the prey cannot be resolved: a gun chase
DEFAULT_ATTACK_PLAN = {
    "attack_mode": AttackMode.PURSUIT,
    "weapon": "guns",
    "launcher": None,
}

# TODO Add an intent to go back to the fight area if too far

# TODO (Where ?) Make the ships that disengaged and are sufficiently far disappear
# from the scene


class FighterTactician(GenericTactician):
    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def update_intent(self) -> tuple[Intent, dict]:
        """
        Picks the intent by priority: evade an overwhelming threat, disengage if
        in poor fighting shape, engage the best prey, hold formation (wingmen),
        patrol (leader), else regroup.

        TODO: include role/squad strategy biases

        :return: The intent and its target dict
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
            best_prey_dict.update(self._plan_attack(best_prey_dict["target_id"]))
            return Intent.ENGAGE, best_prey_dict

        # Check if bot has formation or patrol orders
        orders = self.evaluate_orders()
        if orders is not None:
            return orders

        # Nothing specific to do for now. Regroup with friends
        friends_center_dict = self.evaluate_team_center(team="friends")
        friends_center_dict["target_id"] = Intent.REGROUP
        return Intent.REGROUP, friends_center_dict

    def _plan_attack(self, target_id: UUID) -> dict:
        """
        Choose how to attack the prey. First the weapon (see _choose_weapon),
        then the geometry: bomb -> BOMB; else a slow/immobile target -> STRAFE,
        an agile one -> PURSUIT.

        :param target_id: The chosen prey's id
        :return: The plan to carry in the target dict: its attack_mode, weapon
            ("guns", "bomb", "missile" or "rocket") and the launcher to select
            for it (None for guns)
        """
        try:
            target_index = self.game.interactions.get_actor_index_from_id(target_id)
            target = self.game.interactions.actors[target_index]
        except (ValueError, KeyError, TypeError):
            return dict(DEFAULT_ATTACK_PLAN)

        weapon, launcher = self._choose_weapon(target)
        if weapon == "bomb":
            attack_mode = AttackMode.BOMB
        elif self._is_slow(target):
            attack_mode = AttackMode.STRAFE
        else:
            attack_mode = AttackMode.PURSUIT
        return {"attack_mode": attack_mode, "weapon": weapon, "launcher": launcher}

    def _is_slow(self, target: Any) -> bool:
        """
        :param target: The prey actor
        :return: Whether it is too slow/immobile to be chased sensibly (False
            for a non-numeric mobility, e.g. a mocked target)
        """
        mobility = getattr(target, "mobility", 1.0)
        threshold = self.personality["tactician"]["strafe_mobility_threshold"]
        try:
            return bool(mobility <= threshold)
        except TypeError:
            return False

    def _choose_weapon(self, target: Any) -> tuple[str, OrdnanceLauncher | None]:
        """
        Pick the weapon system for a target, by the target's mobility (see the
        ordnance's target_mobility):

        - heavy ordnance, if it beats guns (see _heavy_ordnance_beats_guns): a
          bomb, or a torpedo (a missile meant for slow targets) against a slow
          primary target, whichever the personality prefers first
          (prefer_torpedoes_to_bombs)
        - a concussion missile (a missile meant for agile targets) against an
          agile primary target
        - a rocket meant for the target's mobility (slow targets only)
        - guns otherwise

        Only launchers with stock left are considered.

        :param target: The prey actor
        :return: The weapon ("guns", "bomb", "missile" or "rocket") and its
            launcher (None for guns)
        """
        is_slow = self._is_slow(target)
        target_mobility = "slow" if is_slow else "agile"
        is_primary = getattr(target, "id", None) in self.primary_target_ids
        missile = None
        if is_primary:
            missile = next(
                (
                    launcher
                    for launcher in self._launchers_with_stock("missile")
                    if launcher.conf["target_mobility"] == target_mobility
                ),
                None,
            )

        bomb = next(iter(self._launchers_with_stock("bomb")), None)
        heavy_ordnance = [("bomb", bomb)]
        if is_slow:
            torpedo = ("missile", missile)
            if self.personality["tactician"]["prefer_torpedoes_to_bombs"]:
                heavy_ordnance.insert(0, torpedo)
            else:
                heavy_ordnance.append(torpedo)
        for weapon, launcher in heavy_ordnance:
            if launcher is not None and self._heavy_ordnance_beats_guns(
                target, launcher
            ):
                return weapon, launcher

        if missile is not None and not is_slow:
            return "missile", missile
        for rocket in self._launchers_with_stock("rocket"):
            if rocket.conf["target_mobility"] == target_mobility:
                return "rocket", rocket
        return "guns", None

    def _launchers_with_stock(self, category: str) -> list[OrdnanceLauncher]:
        """
        :param category: The ordnance type ("bomb", "rocket" or "missile")
        :return: The pawn's secondary weapons of that type with stock left, in
            loadout order
        """
        return [
            launcher
            for launcher in self.pawn.secondary_cycle()
            if launcher.category == category and launcher.stock > 0
        ]

    def _heavy_ordnance_beats_guns(
        self, target: Any, launcher: OrdnanceLauncher
    ) -> bool:
        """
        Whether limited heavy ordnance (a bomb or a torpedo) beats guns on a
        target, by suitability: only on a target that is stationary, tough AND
        valuable, with supply to spare. Any non-numeric input (e.g. a mocked
        target) falls back to guns.

        :param target: The prey actor
        :param launcher: The ordnance's launcher (with stock left)
        :return: True for the ordnance
        """
        scoring = self.personality["tactician"]["heavy_ordnance_scoring"]
        try:
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
                float(launcher.stock), scoring["supply_step"], scoring["supply_slope"]
            )
            stationarity = 1.0 - mobility
            worth = hardness * value
            s_gun = scoring["gun_base"] + scoring["gun_soft"] * (1.0 - hardness)
            s_ordnance = (
                scoring["ordnance_scale"] * stationarity * worth * supply_factor
            )
            return bool(s_ordnance > s_gun)
        except (TypeError, ValueError, AttributeError):
            return False
