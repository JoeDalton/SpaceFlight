from typing import Tuple

import numpy as np
import quaternion
from panda3d.core import (
    CardMaker,
    LPoint3,
    NodePath,
    PointLight,
    Quat,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH
from space_flight.actors.weapon import Munition, Weapon
from space_flight.game.collisions import attach_collision_segment
from space_flight.utils import build_axis_billboard_quat

LASER_SPEED_MPS = 2000.0
SQT2_S = np.sqrt(2.0) / 2.0
LIGHT_ATTENUATION = (1, 0.05, 0)


class LaserCannon(Weapon):
    """
    A rate-limited multi-cannon gun. Cycles through its cannon nodes, aims each
    shot via the parent's auto-aim (falling back to nose-forward), spawns a
    :class:`LaserShot` and plays the fire sound.
    """

    def __init__(self, game, parent, parent_node=None):
        fire_delay = 1.0 / parent.conf["laser_fire_rate"]
        super().__init__(game, parent, parent_node, fire_delay=fire_delay)

        # Cannon configuration
        cannon_positions = self.parent.conf["cannon_positions"]
        self.n_cannon = len(cannon_positions)
        self.cannon_nodes = []
        for cannon_idx in range(self.n_cannon):
            # Create a dummy node to attach models
            node = NodePath("player_node")
            node.reparentTo(self.parent_node)
            node.set_pos(*cannon_positions[cannon_idx])
            self.cannon_nodes.append(node)

        # Laser configuration
        self.shot_power = self.parent.conf["shot_power"]
        self.laser_base_range_m = self.parent.conf["laser_base_range_m"]
        self.life_time_s = self.laser_base_range_m / LASER_SPEED_MPS
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

        # Initialize cannon cycling
        self.current_next_cannon_idx = 0

    def fire(self):
        # Fire at the prescribed rate (reload gate on the Weapon base)
        if not self._ready_to_fire():
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
        self._spawn_munition(
            LaserShot,
            start_position,
            shot_speed,
            self.shot_power,
            self.life_time_s,
            texture=self.laser_texture,
            light_color=self.light_color,
        )

        # Attach sound to the cannon currently firing
        self.game.app.sfx.cannon_fire(
            game=self.game,
            sound_pool=self.sound_pool,
            node=self.cannon_nodes[self.current_next_cannon_idx],
        )

        # Prepare next laser shot
        self.current_next_cannon_idx = (
            self.current_next_cannon_idx + 1
        ) % self.n_cannon

    def clean(self):
        for node in self.cannon_nodes:
            node.remove_node()
        self.cannon_nodes = []
        self.sound_pool = []
        self.laser_texture = None
        super().clean()


class LaserShot(Munition):
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
        origin_ship=None,
    ):
        # Store the visual parameters before the base __init__ calls _build_visual.
        self.texture = texture
        self.light_color = light_color
        super().__init__(
            game=game,
            origin_ship_id=origin_ship_id,
            power=power,
            life_time_s=life_time_s,
            speed=speed,
            start_position=start_position,
            origin_ship=origin_ship,
        )

    def _build_visual(self, start_position) -> NodePath:
        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        shot = self.game.root_node.attach_new_node(cm.generate())

        # Compute orientation
        # A preset orientation is ok since lasers have short lifetimes. For longer-lived
        # objects, I would have to reset the orientation at each frame.
        camera_position = self.game.app.camera.get_pos(self.game.root_node)
        to_camera_vector = camera_position - start_position
        billboard_quat = build_axis_billboard_quat(
            forward=self.speed, up_hint=to_camera_vector
        ) * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        shot.set_quat(Quat(*quaternion.as_float_array(billboard_quat)))

        # Don't rely on scene lighting since lasers emit their own light
        shot.set_light_off()
        # Set texture
        shot.set_texture(self.texture)
        # Allow to be seen from both sides
        shot.set_two_sided(True)
        # Allow transparency
        shot.set_transparency(TransparencyAttrib.MAlpha)

        # Add light source on the laser (it is self-lit)
        self.plight = PointLight("plight")
        self.plight.setColor(self.light_color)
        self.plight.set_attenuation(LIGHT_ATTENUATION)
        self.plnp = shot.attachNewNode(self.plight)
        self.plnp.setPos(0, 0, 0)
        self.game.app.render.setLight(self.plnp)

        return shot

    def _attach_collider(self) -> NodePath:
        # Initialize collision segment
        # The length of the segment is the typical frame time
        # multiplied by the laser speed to cover the space spanned by the laser
        # between two frames
        dt = 1 / self.game.game_time.get_average_frame_rate()
        relative_start_position = np.zeros(3)
        length = np.linalg.norm(self.speed) * dt * np.array([0.0, 0.0, 1.0])
        relative_end_position = relative_start_position + length
        return attach_collision_segment(
            game=self.game,
            name="laser",
            collider_type="laser",
            parent_node=self.shot,
            parent_object=self,
            relative_start_position=LPoint3(*relative_start_position),
            relative_end_position=LPoint3(*relative_end_position),
        )

    def _clean_extra(self) -> None:
        # Clear the laser's own light before the shared teardown removes the node.
        try:
            self.game.app.render.clear_light(self.plnp)
        except AttributeError:
            pass
        self.plnp.removeNode()
        self.plnp = None
