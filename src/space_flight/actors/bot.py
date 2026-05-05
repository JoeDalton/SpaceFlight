import gc
import logging
import sys

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.destructibles import Destructible
from space_flight.actors.ship import Ship
from space_flight.actors.trihedron import Trihedron
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.fighter.fighter_tactician import FighterTactician

LOGGER = logging.getLogger()
WAYPOINT_MEETING_TOLERANCE = 10


class Bot(Destructible):
    def __init__(
        self,
        game,
        name: str,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        team: int = 0,
        debug_decisions: bool = False,
    ):
        super().__init__(game=game)
        self.name = name
        self.ship = Ship(
            game=self.game,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=False,
            team=team,
        )

        self.pilot = FighterPilot(game=self.game, pawn=self.ship)
        self.navigator = FighterNavigator(
            game=self.game, pawn=self.ship, debug=debug_decisions
        )
        self.tactician = FighterTactician(
            game=self.game, pawn=self.ship, debug=debug_decisions
        )
        # TODO remove
        self.game.player.add_target(target=self.ship, name=self.name)
        self.team = team

        self.add_task(method=self.move_bot_task)

        # Add self to the interacting actors
        self.game.interactions.add_actor(self.ship)

    def move_bot_task(self):
        """
        Find how the bot should move:
        - The tactician decides which targets to point and the weights
            to associate to each behaviour
        - The navigator bundles the tactician's wishes and outputs a direction
            to point to and a distance
        - The pilot steers the ship and adjusts the throttle to follow its aim
        - The ship moves according to the games physics
        """
        intent, target_dict = self.tactician.think()

        target_direction, desired_speed_mps = self.navigator.navigate(
            intent=intent, target_dict=target_dict
        )
        throttle, yaw_rate, pitch_rate, roll_rate = self.pilot.pilot(
            target_direction=target_direction, desired_speed_mps=desired_speed_mps
        )
        self.ship.move_ship(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

    def get_health(self) -> float:
        """
        Find the health of the bot

        :return: The health of the bot
        """
        return self.ship.health

    def set_personality(self, personality: dict):
        """
        Sets a personality to the bot via its tactician, navigator and pilot parameters

        :param personality: A personality dictionary
        """
        self.tactician.personality = personality
        self.navigator.personality = personality
        self.pilot.personality = personality

    def play_death(self):
        """
        Plays the death animation of the ship

        Procedural explosion at the ship's last location
        Associated sound #TODO
        Model spinning before explosing ? TODO
        """
        self.game.explosion_fx_pool.spawn(
            position=self.ship.position,
            scale=self.ship.explosion_scale,
            base_velocity=self.ship.speed,
        )

    def clean(self):
        """
        Remove every child
        """
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaning bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
        try:  # TODO to remove anyway when the player no longer has its own targets
            self.game.player.remove_target(target_to_remove=self.ship)
        except AttributeError:
            # In level cleanup, player may no longer exist at this point
            pass
        try:
            self.game.interactions.remove_actor(self.ship)
        except AttributeError:
            # In level cleanup, game.interactions no longer exist at this point
            pass
        self.pilot.clean()
        self.pilot = None
        self.navigator.clean()
        self.navigator = None
        self.tactician.clean()
        self.tactician = None
        self.ship.clean()
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaned bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
            LOGGER.info(f"Bot nref = {sys.getrefcount(self)}")
            LOGGER.info(f"Bot references {gc.get_referrers(self)}")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Deleted bot {self.name}")


def spawn_bot(
    game,
    name: str,
    ship_type: str,
    ini_position: np.ndarray = np.zeros(3),
    ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
    has_debug_trihedron: bool = False,
    team: int = 0,
    debug_decisions: bool = False,
) -> Bot:
    bot = Bot(
        game=game,
        name=name,
        ship_type=ship_type,
        ini_position=ini_position,
        ini_orientation=ini_orientation,
        team=team,
        debug_decisions=debug_decisions,
    )
    if has_debug_trihedron:
        Trihedron(game=game, parent=bot.ship.node, scale=1)

    return bot
