import gc
import logging
import sys
from typing import Any

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.bomb_launcher import BombLauncher
from space_flight.actors.laser_cannon import LaserCannon
from space_flight.actors.ship import Ship
from space_flight.ai.auto_aim import AutoAim
from space_flight.game.collisions import attach_collision_sphere

LOGGER = logging.getLogger()


class Fighter(Ship):
    """
    A class for fighter planes and light bombers
    (quick, manoeuverable, have forward cannons, chase targets...)
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

        # Setup integrated shield
        self.max_shield = self.conf["shield"]
        self.shield = self.max_shield
        self.shield_regen_rate = self.conf["shield_regen_rate"]

        # Initialize cannons
        # TODO auto-aim parameters from difficulty config file
        self.target_id = None
        self.auto_aim = AutoAim(game=self.game, parent=self)
        self.laser_cannon = LaserCannon(game=self.game, parent=self)

        # Limited bomb ordnance + its launcher. drop_bomb spends one unit and
        # releases a bomb; supply gates how many can be dropped.
        self.bomb_supply = self.conf.get("bomb_supply", 0)
        self.bomb_launcher = BombLauncher(game=self.game, parent=self)

        # Initialize collisions
        self.hit_box_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="ship",
            radius=self.hit_box_radius_m,
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

        # Handle ship health and shield
        self.parent.add_task(method=self.ship_handle_health)

        # Set explosion size for death animation
        self.explosion_scale = self.conf["explosion_scale"]

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

        # Compute target acquisition
        self.auto_aim.compute_acquisition()

    @property
    def shield_level(self) -> float:
        """
        A fighter's shield is a plain scalar pool.

        :return: The current shield strength
        """
        return self.shield

    def drop_bomb(self) -> bool:
        """
        Release one bomb from the limited supply.

        The launcher is rate-limited (reload), so a drop can be refused while it is
        reloading even with ordnance to spare; supply is only spent on an actual
        release. Mirrors ``laser_cannon.fire()`` as the hook the bombing-run
        navigator calls, and lets the tactician's ammo accounting work against a
        real, depleting supply.

        :return: True if a bomb was released, False if out of ordnance or reloading
        """
        if self.bomb_supply <= 0:
            return False
        if not self.bomb_launcher.launch():
            # Still reloading -- do not spend a unit of ordnance.
            return False
        self.bomb_supply -= 1
        LOGGER.info("%s dropped a bomb (%d left)", self.parent.name, self.bomb_supply)
        return True

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the ship

        :param damage_type: the type of damage to apply (physical, energy)
        """
        # Apply damage to health and shield
        if damage_type == "physical":
            if self.shield - damage >= 0.0:
                self.shield -= damage
            else:
                health_damage = damage - self.shield
                self.health -= health_damage
                self.shield = 0.0
        else:
            raise NotImplementedError

    def ship_handle_health(self):
        """
        Monitors the ships health and shield
        """
        dt = self.game.game_time.get_time_step()
        self.shield = min(
            max(0.0, self.shield + dt * self.shield_regen_rate), self.max_shield
        )
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            super().clean()
            # Remove fighter-specific attributes
            self.auto_aim.clean()
            self.auto_aim = None
            self.laser_cannon.clean()
            self.laser_cannon = None
            self.bomb_launcher.clean()
            self.bomb_launcher = None

            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)
