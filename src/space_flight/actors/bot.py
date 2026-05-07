import gc
import logging
import sys

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.capital_ship import CapitalShip
from space_flight.actors.destructibles import Destructible
from space_flight.actors.fighter import Fighter
from space_flight.actors.turret import Turret
from space_flight.ai.capital_ship.capital_ship_navigator import CapitalShipNavigator
from space_flight.ai.capital_ship.capital_ship_pilot import CapitalShipPilot
from space_flight.ai.capital_ship.capital_ship_tactician import CapitalShipTactician
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.fighter.fighter_tactician import FighterTactician
from space_flight.ai.turret.turret_navigator import TurretNavigator
from space_flight.ai.turret.turret_pilot import TurretPilot
from space_flight.ai.turret.turret_tactician import TurretTactician

LOGGER = logging.getLogger()
WAYPOINT_MEETING_TOLERANCE = 10


class Bot(Destructible):
    def __init__(
        self,
        game,
        name: str,
        bot_type: str,
        pawn_model: str,
        team: int = 0,
        debug_decisions: bool = False,
        **kwargs,
    ):
        super().__init__(game=game)
        self.name = name
        self.bot_type = bot_type
        if self.bot_type == "fighter":
            self.pawn = Fighter(
                game=self.game,
                parent=self,
                ship_type=pawn_model,
                ini_position=kwargs.get("ini_position", np.zeros(3)),
                ini_orientation=kwargs.get(
                    "ini_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_speed=kwargs.get("ini_speed", np.zeros(3)),
                is_cockpit=False,
                team=team,
            )

            self.pilot = FighterPilot(game=self.game, pawn=self.pawn)
            self.navigator = FighterNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = FighterTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        elif self.bot_type == "turret":
            self.pawn = Turret(
                game=self.game,
                parent=self,
                turret_type=pawn_model,
                parent_object=kwargs.get("parent_object", self.game.root_node),
                base_position=kwargs.get("base_position", np.zeros(3)),
                base_orientation=kwargs.get(
                    "base_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_yaw_deg=kwargs.get("ini_yaw_deg", 0.0),
                ini_pitch_deg=kwargs.get("ini_pitch_deg", -30),
                team=team,
            )

            self.pilot = TurretPilot(game=self.game, pawn=self.pawn)
            self.navigator = TurretNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = TurretTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        elif self.bot_type == "capital_ship":
            self.pawn = CapitalShip(
                game=self.game,
                parent=self,
                ship_type=pawn_model,
                ini_position=kwargs.get("ini_position", np.zeros(3)),
                ini_orientation=kwargs.get(
                    "ini_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_speed=kwargs.get("ini_speed", np.zeros(3)),
                is_cockpit=False,
                team=team,
            )

            self.pilot = CapitalShipPilot(game=self.game, pawn=self.pawn)
            self.navigator = CapitalShipNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = CapitalShipTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        else:
            raise NotImplementedError(f"Unknown bot type {self.bot_type}")
        # TODO remove
        self.game.player.add_target(target=self.pawn, name=self.name)
        self.team = team

        self.add_task(method=self.move_bot_task)

        # Add self to the interacting actors
        self.game.interactions.add_actor(self.pawn)

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
        if self.bot_type == "fighter" or self.bot_type == "capital_ship":
            intent, target_dict = self.tactician.think()

            target_direction, desired_speed_mps = self.navigator.navigate(
                intent=intent, target_dict=target_dict
            )
            throttle, yaw_rate, pitch_rate, roll_rate = self.pilot.pilot(
                target_direction=target_direction, desired_speed_mps=desired_speed_mps
            )
            self.pawn.move(
                throttle=throttle,
                yaw_rate=yaw_rate,
                pitch_rate=pitch_rate,
                roll_rate=roll_rate,
            )
        elif self.bot_type == "turret":
            intent, target_dict = self.tactician.think()

            target_direction = self.navigator.navigate(
                intent=intent, target_dict=target_dict
            )
            yaw_rate, pitch_rate = self.pilot.pilot(target_direction=target_direction)
            self.pawn.move(
                yaw_rate=yaw_rate,
                pitch_rate=pitch_rate,
            )
        else:
            raise NotImplementedError(f"Unknown bot type {self.bot_type}")

    def get_health(self) -> float:
        """
        Find the health of the bot

        :return: The health of the bot
        """
        return self.pawn.health

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
        Pawn-type dependent ! TODO
        Associated sound TODO
        Model spinning before explosing ? TODO
        """
        self.game.explosion_fx_pool.spawn(
            position=self.pawn.position,
            scale=self.pawn.explosion_scale,
            base_velocity=self.pawn.speed,
        )

    def clean(self):
        """
        Remove every child
        """
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaning bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
        try:  # TODO to remove anyway when the player no longer has its own targets
            self.game.player.remove_target(target_to_remove=self.pawn)
        except AttributeError:
            # In level cleanup, player may no longer exist at this point
            pass
        try:
            self.game.interactions.remove_actor(self.pawn)
        except AttributeError:
            # In level cleanup, game.interactions no longer exist at this point
            pass
        self.pilot.clean()
        self.pilot = None
        self.navigator.clean()
        self.navigator = None
        self.tactician.clean()
        self.tactician = None
        self.pawn.clean()
        self.pawn = None
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
    bot_type: str,
    pawn_model: str,
    team: int = 0,
    debug_decisions: bool = False,
    **kwargs,
) -> Bot:
    bot = Bot(
        game=game,
        name=name,
        bot_type=bot_type,
        pawn_model=pawn_model,
        team=team,
        debug_decisions=debug_decisions,
        **kwargs,
    )

    return bot
