from typing import Tuple

import numpy as np
import quaternion
from panda3d.core import (
    BoundingSphere,
    CardMaker,
    ColorBlendAttrib,
    CullFaceAttrib,
    LPoint3,
    NodePath,
    PointLight,
    Quat,
    Shader,
    Vec3,
)

from space_flight import DATAFILES_PATH
from space_flight.game.collisions import attach_collision_segment
from space_flight.utils import build_axis_billboard_quat
from space_flight.weapons import Munition, Weapon

LASER_SPEED_MPS = 2000.0
SQT2_S = np.sqrt(2.0) / 2.0
LIGHT_ATTENUATION = (1, 0.05, 0)

# --- Capsule-impostor look -------------------------------------------------- #
#: Length of the glowing bolt core, world units.
LASER_LENGTH = 15.0
#: Radius of the white-hot core, world units.
CORE_RADIUS = 0.05
#: Radius of the soft coloured halo around the core, world units.
GLOW_RADIUS = 0.2

#: GLOBAL TOGGLE — whether each bolt carries its own dynamic PointLight.
#: The capsule impostor already looks self-lit, so the light only matters for
#: casting coloured light onto nearby hulls. Hundreds of live bolts means
#: hundreds of dynamic lights, which is the real cost here (far more than the
#: geometry), so flip this to False to drop them wholesale.
EMIT_LASER_LIGHT = False

#: Halo tint per configured laser colour (a touch off-primary reads better as a
#: glow than a pure primary).
GLOW_TINTS = {
    "red": Vec3(1.0, 0.05, 0.05),
    "green": Vec3(0.1, 1.0, 0.15),
    "blue": Vec3(0.2, 0.45, 1.0),
}

#: The laser shader is shared by every bolt; load it once, lazily.
_LASER_SHADER = None


def _laser_shader() -> Shader:
    """Load (once) and return the shared laser capsule-impostor GLSL shader."""
    global _LASER_SHADER
    if _LASER_SHADER is None:
        _LASER_SHADER = Shader.load(
            Shader.SL_GLSL,
            vertex=DATAFILES_PATH / "shaders/laser.vert",
            fragment=DATAFILES_PATH / "shaders/laser.frag",
        )
    return _LASER_SHADER


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

        # Prepare laser look
        laser_intensity = 1.0
        if color == "red":
            self.light_color = (laser_intensity, 0, 0, 1)
        elif color == "green":
            self.light_color = (0, laser_intensity, 0, 1)
        elif color == "blue":
            self.light_color = (0, 0, laser_intensity, 1)
        else:
            raise ValueError
        # Halo tint fed to the capsule shader (self-lit; no sprite texture).
        self.laser_color_rgb = GLOW_TINTS[color]

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
            color=self.laser_color_rgb,
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
        self.laser_color_rgb = None
        super().clean()


class LaserShot(Munition):
    """
    A class for laser shot objects.

    The render is an analytic *capsule impostor*: a single camera-facing quad
    whose fragment shader measures each pixel's distance to the bolt's core line
    segment and turns it into a glowing capsule (see ``shaders/laser.frag``). It
    reads as a solid 3D glowing tube from any angle, including looking straight
    down its own axis (as when the player fires forward), where it shows as a
    bright disc rather than collapsing to a sliver.
    """

    def __init__(
        self,
        game,
        origin_ship_id: str,
        color: Vec3,
        power: float,
        life_time_s: float,
        light_color: Tuple,
        speed: np.ndarray,
        start_position,
        origin_ship=None,
    ):
        # Store the visual parameters before the base __init__ calls _build_visual.
        self.color = color
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
        # Camera-facing card; the shader expands it and draws the capsule.
        cm = CardMaker("laser")
        cm.set_frame(-1.0, 1.0, -1.0, 1.0)
        shot = self.game.root_node.attach_new_node(cm.generate())

        # Orient the node so its local +Z runs along the bolt's travel direction.
        # This is what the swept collision segment (built along local Z in
        # _attach_collider) relies on; the capsule core is likewise placed along
        # local Z below. The roll about that axis is irrelevant (the capsule is
        # axially symmetric and the shader re-faces the card every frame), so the
        # preset up_hint from the spawn-time camera is only there to pin one.
        camera_position = self.game.app.camera.get_pos(self.game.root_node)
        to_camera_vector = camera_position - start_position
        orientation_quat = build_axis_billboard_quat(
            forward=self.speed, up_hint=to_camera_vector
        ) * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        shot.set_quat(Quat(*quaternion.as_float_array(orientation_quat)))

        # Capsule core: the fixed model-space segment along local Z.
        half_len = LASER_LENGTH * 0.5
        shot.set_shader(_laser_shader())
        shot.set_shader_input("uA", Vec3(0.0, 0.0, -half_len))
        shot.set_shader_input("uB", Vec3(0.0, 0.0, half_len))
        shot.set_shader_input("uColor", self.color)
        shot.set_shader_input("uCoreRadius", CORE_RADIUS)
        shot.set_shader_input("uGlowRadius", GLOW_RADIUS)

        # Additive glow (ONE, ONE): order-independent w.r.t. other bolts and the
        # translucent shields / clouds it flies through, so no sorting needed.
        shot.set_attrib(
            ColorBlendAttrib.make(
                ColorBlendAttrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne
            )
        )
        # Seen from any side; self-lit; no depth write (test only, via the
        # shader's gl_FragDepth) so it never occludes other transparent geometry.
        shot.set_attrib(CullFaceAttrib.make(CullFaceAttrib.MCullNone))
        shot.set_light_off()
        shot.set_depth_write(False)
        shot.set_bin("fixed", 20)  # drawn after the sorted "transparent" bin

        # The vertex shader expands the unit card to half_size, so give the node
        # matching bounds or the frustum culler (which only sees the card's own
        # extent) would clip the bolt at the screen edge.
        half_size = half_len + 3.0 * GLOW_RADIUS
        shot.node().set_bounds(BoundingSphere(LPoint3(0, 0, 0), half_size))
        shot.node().set_final(True)

        # Optional self-cast dynamic light (see EMIT_LASER_LIGHT).
        if EMIT_LASER_LIGHT:
            self.plight = PointLight("laser_light")
            self.plight.set_color(self.light_color)
            self.plight.set_attenuation(LIGHT_ATTENUATION)
            self.plnp = shot.attach_new_node(self.plight)
            self.plnp.set_pos(0, 0, 0)
            self.game.app.render.set_light(self.plnp)
        else:
            self.plnp = None

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
        # Clear the laser's own light (if any) before the shared teardown removes
        # the node.
        if self.plnp is not None:
            try:
                self.game.app.render.clear_light(self.plnp)
            except AttributeError:
                pass
            self.plnp.removeNode()
            self.plnp = None
