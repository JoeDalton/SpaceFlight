from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_tactician import GenericTactician


class TrackingMountTactician(GenericTactician):
    """
    Target selection for a tracking mount (turret, tractor beam...).

    Scores the surrounding foes as preys and engages the most interesting one;
    the mount's pawn then decides what to do with the engaged target (fire, grab).
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.TURRET_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def update_intent(self) -> tuple[int, dict]:
        """
        Evaluates the tactical situation around the bot.
        For each foe, score its value as a prey and choose the most interesting one
        to engage.
        """
        # Find current actor index of self
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)

        # Check if bot has a good enough target to engage
        best_prey_dict = self.evaluate_preys(my_actor_index)
        if (
            best_prey_dict["score"]
            >= self.personality["tactician"]["min_engagement_score"]
        ):
            return Intent.ENGAGE, best_prey_dict

        # Nothing specific to do for now
        return Intent.IDLE, {}
