import logging
import random
from typing import Tuple

import numpy as np
import quaternion
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import (
    AudioSound,
    CardMaker,
    LPoint3,
    LVector3,
    NodePath,
    PointLight,
    Quat,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH, DEBUG_DELETION
from space_flight.collisions import attach_collision_segment

LOGGER = logging.getLogger()

LASER_SPEED_MPS = 2000.0
SQT2_S = np.sqrt(2.0) / 2.0
LIGHT_ATTENUATION = (1, 0.05, 0)


class LaserCannon:
    def __init__(self, game, parent_ship):
        self.parent_ship = parent_ship
        self.game = game

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
            self.sound_pool = [
                self.game.sfx.audio3d.loadSfx(sound_file) for _ in range(20)
            ]

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
        self.laser_texture = self.game.app.loader.loadTexture(
            DATAFILES_PATH / f"models/lasers/laser_{color}.png"
        )

        # Initialize cannon
        self.current_next_cannon_idx = 0
        self.last_fire_time = self.game.game_time.get_current_time()

    def fire(self):
        # Fire at prescribed rate
        current_time = self.game.game_time.get_current_time()
        if current_time - self.last_fire_time < self.fire_delay:
            return

        # Start position and orientation relative to the ship
        ship_quat = self.parent_ship.node.get_quat(self.game.app.render)
        q_ship = np.quaternion(*ship_quat)
        q_laser = q_ship * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        ship_dir = ship_quat.get_forward()

        # Compute start and end positions
        speed = LASER_SPEED_MPS * np.array(ship_dir) + self.parent_ship.speed
        start_pos = self.cannon_nodes[self.current_next_cannon_idx].get_pos(
            self.game.app.render
        )

        # TODO : shoot slightly inward so that the shots cross at mid range
        # TODO : Add random spread ? (Very small)
        # TODO : Slight AutoAim when target lock

        _ = LaserShot(
            game=self.game,
            origin_ship_id=self.parent_ship.id,
            texture=self.laser_texture,
            power=self.shot_power,
            life_time_s=self.life_time_s,
            light_color=self.light_color,
            speed=speed,
            start_pos=start_pos,
            quat=q_laser,
        )

        # Add sound to laser shot (empty list if no sound)
        # TODO move to SFX
        for sound in self.sound_pool:
            # Using a pool to avoid reloading resources
            # Must use a non-currently-playing sound, otherwise it will restart
            if sound.status() != AudioSound.PLAYING:
                # Randomize the pitch of the sound to get a more realistic feeling
                sound.setPlayRate(random.uniform(0.9, 1.1))
                # Attach sound to the cannon currently firing
                self.game.sfx.audio3d.attachSoundToObject(
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
        game,
        origin_ship_id: str,
        texture,
        power: float,
        life_time_s: float,
        light_color: Tuple,
        speed: np.ndarray,
        start_pos,
        quat,
    ):
        self.game = game
        self.power = power
        self.origin_ship_id = origin_ship_id

        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        self.shot = self.game.app.render.attach_new_node(cm.generate())
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
        laser_movement_interval = LerpPosInterval(self.shot, life_time_s, end_pos)
        self.game.interval_manager.play_interval(laser_movement_interval)

        # Add light source on laser
        plight = PointLight("plight")
        plight.setColor(light_color)
        plight.set_attenuation(LIGHT_ATTENUATION)
        plnp = self.shot.attachNewNode(plight)
        plnp.setPos(0, 0, 0)
        self.game.app.render.setLight(plnp)

        # Initialize collision segment
        # The length of the segment is the typical frame time
        # multiplied by the laser speed to cover the space spanned by the laser
        # between two frames
        dt = 1 / self.game.game_time.get_average_frame_rate()
        relative_start_position = np.zeros(3)
        length = np.linalg.norm(speed) * dt * np.array([0.0, 0.0, 1.0])
        relative_end_position = relative_start_position + length
        self.laser_np = attach_collision_segment(
            game=self.game,
            name="laser",
            collider_type="laser",
            parent_node=self.shot,
            parent_object=self,
            relative_start_position=LPoint3(*relative_start_position),
            relative_end_position=LPoint3(*relative_end_position),
        )

        # Clean laser at the end of its life
        # Make it disappear at the end of range
        self.game.delayed_methods.do_method_later(
            delay_s=light_duration,
            name="RemoveLaserLight1",
            method=self.game.app.render.clear_light,
            extra_args=[plnp],
        )
        self.game.delayed_methods.do_method_later(
            delay_s=light_duration,
            name="RemoveLaserLight2",
            method=plnp.remove_node,
        )
        self.game.delayed_methods.do_method_later(
            delay_s=life_time_s,
            name="DeleteLaserOwner",
            method=self.laser_np.setPythonTag,
            extra_args=["owner", None],
        )
        self.game.delayed_methods.do_method_later(
            delay_s=life_time_s,
            name="RemoveLaser",
            method=self.shot.remove_node,
        )

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted laser")
