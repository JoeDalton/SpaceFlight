import gc
import logging
import sys

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai.auto_navigator import AutoNavigator
from space_flight.ai.auto_pilot import AutoPilot
from space_flight.ai.auto_tactician import AutoTactician
from space_flight.destructibles import Destructible
from space_flight.fx import spawn_explosion
from space_flight.ship import Ship
from space_flight.trihedron import Trihedron

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

        self.pilot = AutoPilot(game=self.game, ship=self.ship)
        self.navigator = AutoNavigator(
            game=self.game, ship=self.ship, debug=debug_decisions
        )
        self.tactician = AutoTactician(
            game=self.game, ship=self.ship, debug=debug_decisions
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

        target_direction, reference_distance_m = self.navigator.navigate(
            intent=intent, target_dict=target_dict
        )

        throttle, yaw_rate, pitch_rate, roll_rate = self.pilot.pilot(
            target_direction=target_direction, reference_distance_m=reference_distance_m
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
        spawn_explosion(
            game=self.game,
            position=self.ship.position,
            scale=self.ship.explosion_scale,
            speed=self.ship.speed,
        )

    def clean(self):
        """
        Remove every child
        """
        # TODO: use Interactions and eliminate player targets

        if DEBUG_DELETION:
            LOGGER.info(f"Cleaning bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
        self.game.player.remove_target(target_to_remove=self.ship)
        self.game.interactions.remove_actor(self.ship)
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

    # Debug
    bot.ship.health = 1.1
    bot.ship.shield = 0.0
    bot.ship.shield_regen_rate = 0.0

    return bot
