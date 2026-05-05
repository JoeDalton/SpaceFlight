import logging
import uuid
from typing import Tuple

import numpy as np
import quaternion
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import (
    CardMaker,
    LPoint3,
    LVector3,
    NodePath,
    PointLight,
    Quat,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH, DEBUG_DELETION
from space_flight.game.collisions import attach_collision_segment
from space_flight.utils import build_axis_billboard_quat

LOGGER = logging.getLogger()

LASER_SPEED_MPS = 2000.0
SQT2_S = np.sqrt(2.0) / 2.0
LIGHT_ATTENUATION = (1, 0.05, 0)


class LaserCannon:
    def __init__(self, game, parent):
        self.parent = parent
        self.game = game

        # Cannon configuration
        cannon_positions = self.parent.conf["cannon_positions"]
        self.n_cannon = len(cannon_positions)
        self.cannon_nodes = []
        for cannon_idx in range(self.n_cannon):
            # Create a dummy node to attach models
            node = NodePath("player_node")
            node.reparentTo(self.parent.node)
            node.set_pos(*cannon_positions[cannon_idx])
            self.cannon_nodes.append(node)

        # Laser configuration
        self.shot_power = self.parent.conf["shot_power"]
        self.laser_base_range_m = self.parent.conf["laser_base_range_m"]
        self.life_time_s = self.laser_base_range_m / LASER_SPEED_MPS
        self.fire_delay = 1.0 / self.parent.conf["laser_fire_rate"]
        color = self.parent.conf["laser_color"]

        # Sound initialization
        sound_file = DATAFILES_PATH / self.parent.conf["laser_sound"]
        self.sound_pool = self.game.app.asset_manager.get_asset(
            asset_type="3d_sound",
            path=sound_file,
        )

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
        self.laser_texture = self.game.app.asset_manager.get_asset(
            asset_type="texture",
            path=DATAFILES_PATH / f"sprites/lasers/laser_{color}.png",
        ).get_texture()

        # Initialize cannon
        self.current_next_cannon_idx = 0
        self.last_fire_time = self.game.game_time.get_current_time()

    def fire(self):
        # Fire at prescribed rate
        current_time = self.game.game_time.get_current_time()
        if current_time - self.last_fire_time < self.fire_delay:
            return

        # Compute start position
        start_position = self.cannon_nodes[self.current_next_cannon_idx].get_pos(
            self.game.root_node
        )
        # Get shot direction from auto-aim
        try:
            shot_speed = self.parent.auto_aim.compute_shot_speed(
                start_position=start_position
            )
        except AttributeError:
            # Non relativistic projectiles: they are emitted from a possibly moving gun
            shot_speed = (
                LASER_SPEED_MPS * np.array(self.parent.forward) + self.parent.speed
            )

        # Spawn laser shot
        _ = LaserShot(
            game=self.game,
            origin_ship_id=self.parent.id,
            texture=self.laser_texture,
            power=self.shot_power,
            life_time_s=self.life_time_s,
            light_color=self.light_color,
            speed=shot_speed,
            start_position=start_position,
        )

        # Attach sound to the cannon currently firing
        self.game.app.sfx.cannon_fire(
            sound_pool=self.sound_pool,
            node=self.cannon_nodes[self.current_next_cannon_idx],
        )

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
        self.parent = None
        self.laser_texture = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned laser cannon")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted laser cannon")


class LaserShot:
    """
    A class for laser shot objects

    The render is a custom camera-facing quad whose long axis is the laser velocity
    direction.
    A native panda3d billboard must not be used since it rotates freely
    """

    def __init__(
        self,
        game,
        origin_ship_id: str,
        texture,
        power: float,
        life_time_s: float,
        light_color: Tuple,
        speed: np.ndarray,
        start_position,
    ):
        self.game = game
        self.id = uuid.uuid4()
        self.power = power
        self.origin_ship_id = origin_ship_id

        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        self.shot = self.game.root_node.attach_new_node(cm.generate())

        # Compute orientation
        # A preset orientation is ok since lasers have short lifetimes. For longer-lived
        # objects, I would have to reset the orientation at each frame.
        camera_position = self.game.app.camera.get_pos(self.game.root_node)
        to_camera_vector = camera_position - start_position
        billboard_quat = build_axis_billboard_quat(
            forward=speed, up_hint=to_camera_vector
        ) * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        self.shot.set_quat(Quat(*quaternion.as_float_array(billboard_quat)))

        my_range = speed * life_time_s

        end_position = start_position + LVector3(*my_range)

        # Don't rely on scene lighting since lasers emit their own light
        self.shot.set_light_off()
        # Set texture
        self.shot.set_texture(texture)
        # Allow to be seen from both sides
        self.shot.set_two_sided(True)
        # Allow transparency
        self.shot.set_transparency(TransparencyAttrib.MAlpha)

        # Preset movement
        self.shot.set_pos(start_position)
        laser_movement_interval = LerpPosInterval(self.shot, life_time_s, end_position)
        self.game.interval_manager.play_interval(laser_movement_interval)

        # Add light source on laser
        self.plight = PointLight("plight")
        self.plight.setColor(light_color)
        self.plight.set_attenuation(LIGHT_ATTENUATION)
        self.plnp = self.shot.attachNewNode(self.plight)
        self.plnp.setPos(0, 0, 0)
        self.game.app.render.setLight(self.plnp)

        # Initialize collision segment
        # The length of the segment is the typical frame time
        # multiplied by the laser speed to cover the space spanned by the laser
        # between two frames
        dt = 1 / self.game.game_time.get_average_frame_rate()
        relative_start_position = np.zeros(3)
        length = np.linalg.norm(speed) * dt * np.array([0.0, 0.0, 1.0])
        relative_end_position = relative_start_position + length
        self.laser_col_np = attach_collision_segment(
            game=self.game,
            name="laser",
            collider_type="laser",
            parent_node=self.shot,
            parent_object=self,
            relative_start_position=LPoint3(*relative_start_position),
            relative_end_position=LPoint3(*relative_end_position),
        )

        # Register self in temporary game objects
        self.game.game_objects[self.id] = self

        # Clean laser at the end of its life
        # Make it disappear at the end of range
        self.game.delayed_methods.do_method_later(
            delay_s=life_time_s,
            name="CleanLaserShot",
            method=self.clean,
        )

    def clean(self, remove_from_game_objects: bool = True):
        """
        Cleans a LaserShot object
        """
        # Clear light
        try:
            self.game.app.render.clear_light(self.plnp)
        except AttributeError:
            pass
        self.plnp.removeNode()
        # Remove collision sphere reference to self
        try:
            self.laser_col_np.setPythonTag("owner", None)
        except AttributeError:
            pass
        self.laser_col_np = None
        # Remove shot node
        try:
            self.shot.removeNode()
        except AttributeError:
            pass
        self.shot = None
        # Remove shot from the temporary game objects
        if remove_from_game_objects:
            # Do not do it at the final game cleanup
            # Otherwise it messes up with the loop
            if self.game.method_lists:
                try:
                    self.game.method_lists.pop(self.id)
                except KeyError:
                    pass

        self.game = None

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted laser")
