import logging
import random
from typing import Tuple

import numpy as np
import quaternion
from direct.interval.IntervalGlobal import LerpPosInterval
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject
from panda3d.core import (
    AudioSound,
    CardMaker,
    CollisionNode,
    CollisionSphere,
    LVector3,
    NodePath,
    PointLight,
    Quat,
    TransparencyAttrib,
)

from space_flight import ALL_BIT, DATAFILES_PATH

from space_flight import DEBUG_DELETION
LOGGER = logging.getLogger()

LASER_SPEED_MPS = 1000.0
# LASER_SPEED_MPS = 30.0
SQT2_S = np.sqrt(2.0) / 2.0
LIGHT_ATTENUATION = (1, 0.05, 0)


class LaserCannon:
    def __init__(self, app: ShowBase, parent_ship):
        self.parent_ship = parent_ship
        self.app = app

        # Cannon configuration
        cannon_positions = self.parent_ship.conf["cannon_positions"]
        self.n_cannon = len(cannon_positions)
        self.cannon_nodes = []
        for cannon_idx in range(self.n_cannon):
            # Create a dummy node to attach models
            node = NodePath("player_node")
            node.reparentTo(self.parent_ship.node)
            node.set_pos(*cannon_positions[cannon_idx])
            self.cannon_nodes.append(node)

        # Laser configuration
        self.shot_power = self.parent_ship.conf["shot_power"]
        self.laser_base_range_m = self.parent_ship.conf["laser_base_range_m"]
        self.life_time_s = self.laser_base_range_m / LASER_SPEED_MPS
        self.fire_delay = 1.0 / self.parent_ship.conf["laser_fire_rate"]
        color = self.parent_ship.conf["laser_color"]

        # Sound initialization
        sound_file = DATAFILES_PATH / self.parent_ship.conf["laser_sound"]
        if sound_file != "none":
            self.sound_pool = [self.app.audio3d.loadSfx(sound_file) for _ in range(20)]

        # Prepare laser model
        laser_intensity = 1.0
        if color == "red":
            self.light_color = (laser_intensity, 0, 0, 1)
        elif color == "green":
            self.light_color = (0, laser_intensity, 0, 1)
        elif color == "blue":
            self.light_color = (0, 0, laser_intensity, 1)
        else:
            raise ValueError
        self.laser_texture = self.app.loader.loadTexture(
            DATAFILES_PATH / f"models/lasers/laser_{color}.png"
        )

        # Initialize cannon
        self.current_next_cannon_idx = 0
        self.global_clock = ClockObject.getGlobalClock()
        self.last_fire_time = self.global_clock.getFrameTime()

    def fire(self):
        # Fire at prescribed rate
        current_time = self.global_clock.getFrameTime()
        if current_time - self.last_fire_time < self.fire_delay:
            return

        # Start position and orientation relative to the ship
        ship_quat = self.parent_ship.node.get_quat(self.app.render)
        q_ship = np.quaternion(*ship_quat)
        q_laser = q_ship * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        ship_dir = ship_quat.get_forward()

        # Compute start and end positions
        speed = LASER_SPEED_MPS * np.array(ship_dir) + self.parent_ship.speed
        start_pos = self.cannon_nodes[self.current_next_cannon_idx].get_pos(
            self.app.render
        )

        # TODO : shoot slightly inward so that the shots cross at mid range
        # TODO : Add random spread ? (Very small)

        _ = LaserShot(
            app=self.app,
            texture=self.laser_texture,
            power=self.shot_power,
            life_time_s=self.life_time_s,
            light_color=self.light_color,
            speed=speed,
            start_pos=start_pos,
            quat=q_laser,
        )

        # Add sound to laser shot (empty list if no sound)
        for sound in self.sound_pool:
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                # Randomize the pitch of the sound to get a more realistic feeling
                sound.setPlayRate(random.uniform(0.9, 1.1))
                # Attach sound to the cannon currently firing
                self.app.audio3d.attachSoundToObject(
                    sound, self.cannon_nodes[self.current_next_cannon_idx]
                )
                sound.play()
                break

        # Prepare next laser shot
        self.current_next_cannon_idx = (
            self.current_next_cannon_idx + 1
        ) % self.n_cannon
        self.last_fire_time = current_time

    def clean(self):
        for node in self.cannon_nodes:
            node.remove_node()
        self.cannon_nodes = []
        self.sound_pool = []
        self.parent_ship = None
        self.laser_texture = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned laser cannon")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted laser cannon")


class LaserShot:
    def __init__(
        self,
        app,
        texture,
        power: float,
        life_time_s: float,
        light_color: Tuple,
        speed: np.ndarray,
        start_pos,
        quat,
    ):
        self.app = app
        self.power = power

        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        self.shot = self.app.render.attach_new_node(cm.generate())
        self.shot.set_texture(texture)
        self.shot.set_two_sided(True)
        self.shot.set_transparency(TransparencyAttrib.MAlpha)

        self.shot.set_quat(Quat(*quaternion.as_float_array(quat)))

        my_range = speed * life_time_s

        end_pos = start_pos + LVector3(*my_range)
        light_duration = life_time_s / 2

        # Don't rely on scene lighting since lasers emit their own light
        self.shot.set_light_off()

        # Preset movement
        self.shot.set_pos(start_pos)
        LerpPosInterval(self.shot, life_time_s, end_pos).start()

        # Add light source on laser
        plight = PointLight("plight")
        plight.setColor(light_color)
        plight.set_attenuation(LIGHT_ATTENUATION)
        plnp = self.shot.attachNewNode(plight)
        plnp.setPos(0, 0, 0)
        self.app.render.setLight(plnp)
        self.app.doMethodLater(
            light_duration,
            lambda t: self.app.render.clear_light(plnp),
            "RemoveLaserLight",
        )

        # Initialize collision
        self.laser_cnode = CollisionNode("laser")
        self.laser_cnode.addSolid(CollisionSphere(0, 0, 0, 1))
        self.laser_cnode.setFromCollideMask(ALL_BIT)
        self.laser_cnode.setIntoCollideMask(0)
        self.laser_np = self.shot.attachNewNode(self.laser_cnode)
        self.app.collision_system.traverser.addCollider(
            self.laser_np, self.app.collision_system.handler
        )
        self.laser_np.setPythonTag("owner", self)
        self.laser_np.show()

        # Clean laser at the end of its life
        # Make it disappear at the end of range
        self.app.doMethodLater(
            life_time_s,
            lambda t: self.laser_np.setPythonTag("owner", None),
            "DeleteLaserOwner",
        )
        self.app.doMethodLater(
            light_duration, lambda t: plnp.remove_node(), "RemoveLaserLight"
        )
        self.app.doMethodLater(
            life_time_s, lambda t: self.shot.remove_node(), "RemoveLaser"
        )

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted laser")
