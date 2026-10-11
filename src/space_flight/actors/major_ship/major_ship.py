from __future__ import annotations

import gc
import logging
import sys
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.major_ship.hangar import Hangar
from space_flight.actors.major_ship.shield import Shield
from space_flight.actors.major_ship.shield_generator import ShieldGenerator
from space_flight.actors.major_ship.targeting_system import TargetingSystem
from space_flight.actors.ship import Ship
from space_flight.game.collisions import attach_collision_sphere

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class MajorShip(Ship):
    """
    Base class for the big ships carrying subsystems (shield generators, turrets,
    hangars, ...): escort ships (transports, frigates, corvettes) and capital
    ships (star destroyers). Each ship config picks its subclass (see
    :func:`make_major_ship`).
    (Slow and not very manoeuverable, attacks from their side or bottom)
    """

    def __init__(
        self,
        game: FlightState,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        is_cockpit: bool = True,
        team: int = 0,
    ):
        super().__init__(
            game=game,
            parent=parent,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            ini_speed=ini_speed,
            is_cockpit=is_cockpit,
            team=team,
        )

        # Actor category, so target filters can single major ships out (the HUD
        # "Capital ships" filter covers escort and capital ships alike).
        self.category = "capital_ship"

        # Subsystems declared in the ship config (possibly none)
        sub_systems_conf = self.conf.get("sub_systems", {})
        self.sub_systems = []

        # Shield generators, projecting one shared shield (built below).
        # self.shield_generators is also read by the fleet AI.
        self.shield_generators = []
        for gen_conf in sub_systems_conf.get("shield_generators", []):
            generator = ShieldGenerator(
                game=self.game,
                parent=self,
                relative_position=np.array(
                    gen_conf.get("relative_position", [0.0, 0.0, 0.0])
                ),
                hit_box_radius_m=gen_conf.get("hit_box_radius_m", 5.0),
                health=gen_conf.get("health", 1000.0),
                explosion_scale=gen_conf.get("explosion_scale", 10.0),
            )
            self.sub_systems.append(generator)
            self.shield_generators.append(generator)

        self._setup_shield(sub_systems_conf)

        for ts_conf in sub_systems_conf.get("targeting_systems", []):
            self.sub_systems.append(
                TargetingSystem(
                    game=self.game,
                    parent=self,
                    relative_position=np.array(
                        ts_conf.get("relative_position", [0.0, 0.0, 0.0])
                    ),
                    hit_box_radius_m=ts_conf.get("hit_box_radius_m", 5.0),
                    health=ts_conf.get("health", 1000.0),
                    explosion_scale=ts_conf.get("explosion_scale", 10.0),
                    fire_rate_multiplier=ts_conf.get("fire_rate_multiplier", 2.0),
                    auto_aim_params=ts_conf.get("auto_aim", {}),
                )
            )

        # Hangars, launching fighters on request
        self.hangars = self._build_hangars(sub_systems_conf)
        self.sub_systems.extend(self.hangars)

        # Mounted, bot-controlled subsystems (turrets, tractor beams): each has
        # its own AI, so it is spawned as a Bot whose pawn is mounted on us.
        self.mounted_bots = self._spawn_mounted_bots(
            "turrets", bot_type="turret", model_key="turret_type"
        ) + self._spawn_mounted_bots(
            "tractor_beams", bot_type="tractor_beam", model_key="tractor_beam_type"
        )

        # Initialize collisions # TODO capsule/mesh/whatever relevant
        self.hit_box_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="ship",
            radius=self.hit_box_radius_m,
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

        # Set explosion size for death animation
        self.explosion_scale = self.conf["explosion_scale"]

    def _build_hangars(self, sub_systems_conf: dict) -> list[Hangar]:
        """
        Build the hangars declared in the ship config.

        :param sub_systems_conf: The ship's sub_systems config section
        :return: The hangars
        """
        hangars = []
        for i, hangar_conf in enumerate(sub_systems_conf.get("hangars", [])):
            hangars.append(
                Hangar(
                    game=self.game,
                    parent=self,
                    relative_position=np.array(
                        hangar_conf.get("relative_position", [0.0, 0.0, 0.0])
                    ),
                    half_extents_m=hangar_conf.get(
                        "half_extents_m", [20.0, 20.0, 10.0]
                    ),
                    health=hangar_conf.get("health", 3000.0),
                    explosion_scale=hangar_conf.get("explosion_scale", 40.0),
                    group_size=hangar_conf.get("group_size", 3),
                    launch_interval_s=hangar_conf.get("launch_interval_s", 1.5),
                    max_active=hangar_conf.get("max_active", 6),
                    launch_direction=hangar_conf.get(
                        "launch_direction", [0.0, 0.0, -1.0]
                    ),
                    launch_speed_mps=hangar_conf.get("launch_speed_mps", 30.0),
                    launch_margin_m=hangar_conf.get("launch_margin_m", 5.0),
                    name=f"hangar_{i}",
                )
            )
        return hangars

    def _spawn_mounted_bots(
        self, config_key: str, bot_type: str, model_key: str
    ) -> list:
        """
        Spawns the bot-controlled mounts of a given kind declared in the ship
        config (turrets, tractor beams, ...).

        Each mount is a Bot (it has its own tracking AI) whose pawn is bolted onto
        this ship.

        :param config_key: The sub_systems config section listing the mounts
        :param bot_type: The bot type to spawn for each entry
        :param model_key: The config field naming each mount's model/config
        :return: The spawned mount bots
        """
        # Deferred import: bot imports MajorShip, so importing spawn_bot at the
        # top would be circular.
        from space_flight.actors.bot import spawn_bot

        bots = []
        mounts_conf = self.conf.get("sub_systems", {}).get(config_key, [])
        for i, mount_conf in enumerate(mounts_conf):
            bots.append(
                spawn_bot(
                    game=self.game,
                    name=f"{self.parent.name}_{bot_type}_{i}",
                    bot_type=bot_type,
                    pawn_model=mount_conf[model_key],
                    team=self.team,
                    parent_object=self,
                    base_position=np.array(
                        mount_conf.get("base_position", [0.0, 0.0, 0.0])
                    ),
                    base_orientation=np.array(
                        mount_conf.get("base_orientation", [1.0, 0.0, 0.0, 0.0])
                    ),
                    ini_yaw_deg=mount_conf.get("ini_yaw_deg", 0.0),
                    ini_pitch_deg=mount_conf.get("ini_pitch_deg", 30.0),
                )
            )
        return bots

    def _setup_shield(self, sub_systems_conf: dict):
        """
        Build the single shared :class:`Shield` projected by this ship's shield
        generators, if it has any.

        A ship with **no** shield generators gets **no** shield (a shield spec on
        such a ship is ignored, with a warning). Sets :attr:`shield` to the shield
        or None.

        :param sub_systems_conf: The ship's sub_systems config section
        """
        self.shield = None
        if not self.shield_generators:
            if sub_systems_conf.get("shield") is not None:
                LOGGER.warning(
                    "Ship declares a 'shield' spec but no 'shield_generators'; "
                    "no shield will be projected."
                )
            return

        shield_conf = sub_systems_conf.get("shield", {})
        self.shield = Shield(
            game=self.game,
            ship=self,
            generators=self.shield_generators,
            health=shield_conf.get("health", 4000.0),
            regen_rate=shield_conf.get("regen_rate", 0.0),
            color=shield_conf.get("color"),
            shape=shield_conf.get("shape"),
            model=shield_conf.get("model"),
        )

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship given throttle and turn rates (see :meth:`Ship.move`)

        :param throttle: Throttle command in [0, 1], above 1 for boost
        :param yaw_rate: Yaw rate command in [-1, 1]
        :param pitch_rate: Pitch rate command in [-1, 1]
        :param roll_rate: Roll rate command in [-1, 1]
        """
        super().move(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

    @property
    def shield_level(self) -> float:
        """
        A major ship's shield is a :class:`Shield` object (or None when the
        ship has no shield generators); expose its strength as a plain scalar.

        :return: The current shield strength, or 0 when unshielded
        """
        if self.shield is None:
            return 0.0
        return self.shield.get_shield_level()

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage straight to hull health (the shared shield absorbs hits
        separately, through the collision handlers)

        :param damage: The amount of damage to apply
        :param damage_type: the type of damage to apply (physical, energy)
        """
        if damage_type == "physical":
            self.health -= damage
        else:
            raise NotImplementedError

    def ship_handle_health(self):
        """
        Clamps health to its maximum
        """
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            # Subsystems, mounted bots and the shared shield are Destructibles of
            # their own: they detect our death (mounted_on.is_dead / doomed) and
            # are exploded and cleaned by the central death handling (the shield
            # after its collapse). We only drop our references: cleaning them here
            # would leave dead husks in alive_objects reporting stale health.
            self.sub_systems = []
            self.shield_generators = []
            self.hangars = []
            self.shield = None
            self.mounted_bots = []
            app = self.game.app  # Ship.clean drops self.game
            super().clean()
            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(app.taskMgr.getAllTasks())
