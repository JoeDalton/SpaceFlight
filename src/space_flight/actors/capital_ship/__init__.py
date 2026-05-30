import gc
import logging
import sys
from typing import Any

import numpy as np

from space_flight import DATAFILES_PATH, DEBUG_DELETION

# from space_flight.actors.capital_ship.shield_generator import ShieldGenerator
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

        # TODO Setup subsystems

        # Initialize collisions # TODO capsule/mesh/whatever relevant
        self.hit_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="ship",
            radius=self.hit_radius_m,
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
            super().clean()
            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)
