import gc
import logging
import sys

import numpy as np

from space_flight import DEBUG_DELETION, RECORD_GAME
from space_flight.actors.capital_ship import CapitalShip
from space_flight.actors.capital_ship.tractor_beam import TractorBeamProjector
from space_flight.actors.capital_ship.turret import Turret
from space_flight.actors.destructibles import Destructible
from space_flight.actors.fighter import Fighter
from space_flight.ai import Personality
from space_flight.ai.capital_ship.capital_ship_navigator import CapitalShipNavigator
from space_flight.ai.capital_ship.capital_ship_pilot import CapitalShipPilot
from space_flight.ai.capital_ship.capital_ship_tactician import CapitalShipTactician
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.fighter.fighter_tactician import FighterTactician
from space_flight.ai.tracking_mount.tracking_mount_navigator import (
    TrackingMountNavigator,
)
from space_flight.ai.tracking_mount.tracking_mount_pilot import TrackingMountPilot
from space_flight.ai.tracking_mount.tracking_mount_tactician import (
    TrackingMountTactician,
)

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
            # A turret is a subsystem of the ship it is mounted on (its team is
            # taken from that ship); the bot only controls it.
            self.pawn = Turret(
                game=self.game,
                parent=self,
                turret_type=pawn_model,
                mounted_on=kwargs.get("parent_object"),
                base_position=kwargs.get("base_position", np.zeros(3)),
                base_orientation=kwargs.get(
                    "base_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_yaw_deg=kwargs.get("ini_yaw_deg", 0.0),
                ini_pitch_deg=kwargs.get("ini_pitch_deg", -30),
                personality=Personality.TURRET_DEFAULT,
            )

            self.pilot = TrackingMountPilot(game=self.game, pawn=self.pawn)
            self.navigator = TrackingMountNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = TrackingMountTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        elif self.bot_type == "tractor_beam":
            # A tractor beam projector is, like a turret, a subsystem of its ship
            # driven by this bot. It shares the generic tracking-mount AI; only its
            # personality (grab behaviour) and its pawn differ.
            self.pawn = TractorBeamProjector(
                game=self.game,
                parent=self,
                projector_type=pawn_model,
                mounted_on=kwargs.get("parent_object"),
                base_position=kwargs.get("base_position", np.zeros(3)),
                base_orientation=kwargs.get(
                    "base_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_yaw_deg=kwargs.get("ini_yaw_deg", 0.0),
                ini_pitch_deg=kwargs.get("ini_pitch_deg", -30),
                personality=Personality.TRACTOR_BEAM_DEFAULT,
            )

            self.pilot = TrackingMountPilot(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
            )
            self.navigator = TrackingMountNavigator(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
                debug=debug_decisions,
            )
            self.tactician = TrackingMountTactician(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
                debug=debug_decisions,
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

        self.team = team
        self.record = kwargs.get("record", False)

        self.add_task(method=self.move_bot_task)

        # Add the pawn to the interacting actors. A subsystem pawn (e.g. a
        # turret) already registered itself, so skip the duplicate.
        try:
            self.game.interactions.add_actor(self.pawn)
        except ValueError:
            pass

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
            if RECORD_GAME and self.record:
                self.record_state(
                    intent=intent,
                    target_dict=target_dict,
                    desired_speed_mps=desired_speed_mps,
                )
            throttle, yaw_rate, pitch_rate, roll_rate = self.pilot.pilot(
                target_direction=target_direction,
                desired_speed_mps=desired_speed_mps,
                up_reference=self.navigator.up_reference,
            )
            self.pawn.move(
                throttle=throttle,
                yaw_rate=yaw_rate,
                pitch_rate=pitch_rate,
                roll_rate=roll_rate,
            )
        elif self.bot_type in ("turret", "tractor_beam"):
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

    def record_state(self, intent, target_dict: dict, desired_speed_mps: float):
        """
        Step-by-step recording of the bot's tactical decision (intent, attack mode,
        target and the resulting kinematics), namespaced by bot name, for post-hoc
        analysis of an engagement.

        :param intent: The tactician's chosen intent
        :param target_dict: The tactician's target info (may hold ``attack_mode``)
        :param desired_speed_mps: The navigator's desired speed
        """
        name = self.name
        record = self.game.record

        record.record(
            f"{name}_intent", intent.name if hasattr(intent, "name") else str(intent)
        )
        attack_mode = target_dict.get("attack_mode")
        record.record(
            f"{name}_attack_mode",
            attack_mode.name if attack_mode is not None else "",
        )

        # Resolve the target's readable name and current distance, when it is a
        # real actor (some intents carry a sentinel target_id instead).
        target_id = target_dict.get("target_id")
        target_name = ""
        distance_to_target_m = float("nan")
        target_speed_mps = float("nan")
        target_mobility = float("nan")
        try:
            target_index = self.game.interactions.get_actor_index_from_id(target_id)
            my_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
            target_actor = self.game.interactions.actors[target_index]
            target_name = getattr(
                target_actor,
                "name",
                getattr(getattr(target_actor, "parent", None), "name", str(target_id)),
            )
            distance_to_target_m = float(
                self.game.interactions.distances[my_index, target_index]
            )
            target_speed_mps = float(
                np.linalg.norm(getattr(target_actor, "speed", np.zeros(3)))
            )
            target_mobility = float(getattr(target_actor, "mobility", float("nan")))
        except (ValueError, KeyError, TypeError, AttributeError):
            pass

        record.record(f"{name}_target", str(target_name))
        record.record(f"{name}_distance_to_target_m", distance_to_target_m)
        record.record(f"{name}_target_speed_mps", target_speed_mps)
        record.record(f"{name}_target_mobility", target_mobility)
        record.record(f"{name}_desired_speed_mps", float(desired_speed_mps))
        record.record(f"{name}_speed_mps", float(np.linalg.norm(self.pawn.speed)))

    @property
    def health(self) -> float:
        """
        The bot's health, uniform with the other destructibles: it is its pawn's.
        """
        return self.pawn.health

    @property
    def shield_level(self) -> float:
        """
        The bot's shield strength, uniform with the other destructibles: it is its
        pawn's.
        """
        return self.pawn.shield_level

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
        except (KeyError, AttributeError):
            # Already removed (a subsystem pawn deregisters itself), or
            # game.interactions is gone during level cleanup
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
    # TODO useless function, just use the constructor directly ?
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
