import random

import numpy as np
import quaternion
from direct.interval.IntervalGlobal import LerpPosInterval
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject
from panda3d.core import (
    AudioSound,
    CardMaker,
    LVector3,
    NodePath,
    PointLight,
    Quat,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH

LASER_SPEED = 1000.0
SQT2_S = np.sqrt(2.0) / 2.0


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
        self.life_time = self.parent_ship.conf["laser_life_time"]
        self.fire_delay = 1.0 / self.parent_ship.conf["laser_fire_rate"]
        color = self.parent_ship.conf["laser_color"]

        # Sound initialization
        sound_file = DATAFILES_PATH / self.parent_ship.conf["laser_sound"]
        if sound_file != "none":
            self.sound_pool = [self.app.audio3d.loadSfx(sound_file) for _ in range(20)]

        # Initialize laser model
        laser_intensity = 1.0
        self.light_attenuation = (1, 0.05, 0)
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

        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        laser_np = self.app.render.attach_new_node(cm.generate())
        laser_np.set_texture(self.laser_texture)
        laser_np.set_two_sided(True)
        laser_np.set_transparency(TransparencyAttrib.MAlpha)

        # Start position and orientation relative to the ship
        ship_quat = self.parent_ship.node.get_quat(self.app.render)
        q_ship = np.quaternion(*ship_quat)
        q_laser = q_ship * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        ship_dir = ship_quat.get_forward()
        laser_np.set_quat(Quat(*quaternion.as_float_array(q_laser)))

        # Compute start and end positions
        my_speed = LASER_SPEED * np.array(ship_dir) + self.parent_ship.speed
        my_range = my_speed * self.life_time
        start_pos = self.cannon_nodes[self.current_next_cannon_idx].get_pos(
            self.app.render
        )
        end_pos = start_pos + LVector3(*my_range)
        duration = self.life_time
        light_duration = duration / 2

        # Don't rely on scene lighting since lasers emit their own light
        laser_np.set_light_off()

        # Preset movement
        laser_np.set_pos(start_pos)
        LerpPosInterval(laser_np, duration, end_pos).start()
        # Make it disappear at the end of range
        self.app.doMethodLater(
            duration, lambda t: laser_np.remove_node(), "RemoveLaser"
        )

        # Add light source on laser
        plight = PointLight("plight")
        plight.setColor(self.light_color)
        plight.set_attenuation(self.light_attenuation)
        plnp = laser_np.attachNewNode(plight)
        plnp.setPos(0, 0, 0)
        self.app.render.setLight(plnp)
        self.app.doMethodLater(
            light_duration,
            lambda t: self.app.render.clear_light(plnp),
            "RemoveLaserLight",
        )
        self.app.doMethodLater(
            light_duration, lambda t: plnp.remove_node(), "RemoveLaserLight"
        )

        # Add sound to laser shot (empty list if no sound)
        for sound in self.sound_pool:
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                # Randomize the pitch of the sound to get a more realistic feeling
                sound.setPlayRate(random.uniform(0.9, 1.1))
                # Attach sound the cannon currently firing
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
