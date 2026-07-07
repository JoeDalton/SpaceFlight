import gc
import logging
import sys
from typing import Any

import numpy as np

from space_flight import DATAFILES_PATH, DEBUG_DELETION
from space_flight.actors.capital_ship.shield_generator import ShieldGenerator
from space_flight.actors.capital_ship.targeting_system import TargetingSystem
from space_flight.actors.ship import Ship

# from space_flight.actors.turret import Turret
from space_flight.game.collisions import attach_collision_sphere

LOGGER = logging.getLogger()


class CapitalShip(Ship):
    """
    A class for capital ships, heavy bombers, big freighter, etc.
    (Slow and not very manoeuverable, attacks from their side or bottom)
    """

    def __init__(
        self,
        game,
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

        # Setup subsystems (shield generators, targeting systems, ...) declared
        # in the ship config.
        self.sub_systems = []
        for gen_conf in self.conf["sub_systems"].get("shield_generators", []):
            self.sub_systems.append(
                ShieldGenerator(
                    game=self.game,
                    parent=self,
                    relative_position=np.array(
                        gen_conf.get("relative_position", [0.0, 0.0, 0.0])
                    ),
                    hit_box_radius_m=gen_conf.get("hit_box_radius_m", 5.0),
                    health=gen_conf.get("health", 1000.0),
                    explosion_scale=gen_conf.get("explosion_scale", 10.0),
                    shield_conf=gen_conf.get("shield", {}),
                )
            )
        for ts_conf in self.conf["sub_systems"].get("targeting_systems", []):
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

        # Mounted turrets. Unlike the pure subsystems above, a turret is
        # bot-controlled (it has its own AI), so it is spawned as a Bot whose
        # pawn is a turret mounted on us. They are separate Destructibles that
        # die with us on their own (via mounted_on.is_dead), so we only keep the
        # bots referenced to spawn them; see clean().
        self.turret_bots = self._spawn_mounted_turrets()

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

        # Initialize engine sound for bot ships
        # TODO better
        if self.parent.name != "player":
            sound_file = DATAFILES_PATH / self.conf["exterior_engine_sound"]
            self.sound_pool = self.game.app.asset_manager.get_asset(
                asset_type="3d_sound",
                path=sound_file,
            )
            self.sound = self.sound_pool.get_sound()
            self.sound.setLoop(True)
            self.sound.setVolume(10.0)
            self.game.app.sfx.audio3d.attachSoundToObject(self.sound, self.node)

            # Automatic velocity tracking
            self.game.app.sfx.audio3d.setSoundVelocityAuto(self.node)

            # TODO Doppler does not seem to work great
            self.game.delayed_methods.do_method_later(
                delay_s=0.5,
                name="Play_engine_sound",
                method=self.sound.play,
            )

    def _spawn_mounted_turrets(self) -> list:
        """
        Spawns the bot-controlled turrets declared in the ship config.

        Each turret is a Bot (it has its own targeting AI) whose pawn is a turret
        mounted on this ship. ``spawn_bot`` is imported here rather than at module
        level to break the ``bot`` <-> ``capital_ship`` import cycle.

        :return: The spawned turret bots
        """
        # Deferred import: bot imports CapitalShip, so importing spawn_bot at the
        # top would be circular.
        from space_flight.actors.bot import spawn_bot

        turret_bots = []
        for i, turret_conf in enumerate(self.conf["sub_systems"].get("turrets", [])):
            turret_bots.append(
                spawn_bot(
                    game=self.game,
                    name=f"{self.parent.name}_turret_{i}",
                    bot_type="turret",
                    pawn_model=turret_conf["turret_type"],
                    team=self.team,
                    parent_object=self,
                    base_position=np.array(
                        turret_conf.get("base_position", [0.0, 0.0, 0.0])
                    ),
                    base_orientation=np.array(
                        turret_conf.get("base_orientation", [1.0, 0.0, 0.0, 0.0])
                    ),
                    ini_yaw_deg=turret_conf.get("ini_yaw_deg", 0.0),
                    ini_pitch_deg=turret_conf.get("ini_pitch_deg", 30.0),
                )
            )
        return turret_bots

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship given throttle and turn rates

        :param throttle: _description_
        :param yaw_rate: _description_
        :param pitch_rate: _description_
        :param roll_rate: _description_
        """
        super().move(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the ship

        :param damage_type: the type of damage to apply (physical, energy)
        """
        # Apply damage to health and shield
        if damage_type == "physical":
            self.health -= damage
        else:
            raise NotImplementedError

    def ship_handle_health(self):
        """
        Monitors the ships health and shield
        """
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            # Subsystems are Destructibles of their own. Once this ship is dead
            # they detect it (parent.is_dead) and drop their health, so the
            # central death handling explodes and cleans each one
            # (see SubSystem.handle_health). We only drop our references here:
            # explicitly cleaning them would leave dead husks lingering in
            # alive_objects (get_health would still report their stale health).
            # Turret bots likewise die with us on their own (mounted_on.is_dead),
            # so we only drop their references too.
            self.sub_systems = []
            self.turret_bots = []
            super().clean()
            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)
