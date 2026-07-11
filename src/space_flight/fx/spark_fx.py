from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import Point3, Shader, Texture, Vec3

from space_flight import DATAFILES_PATH
from space_flight.fx import ParticleBuffer
from space_flight.utils import build_orthogonal_basis, sample_direction_in_cone

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ===========================================================================
# SPARK FX
# ===========================================================================
#
# Hit sparks: a short, bright burst of round glowing particles thrown out of a
# laser impact. One shared GPU billboard buffer (:class:`SparkPool`) holds every
# spark; per-hit look is chosen from a :class:`SparkPreset`.
#
# Colour and gravity travel PER PARTICLE (vertex columns), not as uniforms, so
# bursts of different presets (metal / ice / magic) can be alive at the same
# time in the one buffer without repainting one another.

# ---------------------------------------------------------------------------
# Tuning knobs
# ---------------------------------------------------------------------------
# Global multipliers applied on top of *every* preset, so the whole spark look
# can be dialled in from one place while tuning. 1.0 = the per-preset values as
# authored below; bump these to taste.

#: Scales each spark's billboard size (how big the individual sparks look).
SPARK_SIZE_SCALE = 10.0

#: Scales spark launch speed (how far the jet of sparks sprays from the hit).
SPARK_SPEED_SCALE = 10.0

#: Scales the emission-cone (jet) half-angle for every preset (1.0 = as
#: authored below; > 1 = wider spray, < 1 = tighter beam).
SPARK_JET_ANGLE_SCALE = 1.0

#: Per-particle vertex columns for the spark effect, appended to the shared
#: billboard columns owned by :class:`ParticleBuffer`.
_SPARK_COLUMNS = [
    ("velocity", 3),
    ("size", 1),
    ("lifetime", 1),
    ("gravity", 1),
    ("spark_color", 4),
]

#: Single spark sprite (its red channel adds detail on top of the procedural
#: SDF glow; the shape floors to the glow so a flat texture still reads).
_SPARK_TEXTURE = DATAFILES_PATH / "sprites/particles/spark.png"


# ---------------------------------------------------------------------------
# Spark shader
# ---------------------------------------------------------------------------

#: The spark shader is shared by every burst; load it once, lazily.
_SPARK_SHADER = None


def _spark_shader() -> Shader:
    """
    Load (once) and return the shared spark GLSL shader.

    :return: The shared spark :class:`Shader`.
    """
    global _SPARK_SHADER
    if _SPARK_SHADER is None:
        _SPARK_SHADER = Shader.load(
            Shader.SL_GLSL,
            vertex=DATAFILES_PATH / "shaders/spark.vert",
            fragment=DATAFILES_PATH / "shaders/spark.frag",
        )
    return _SPARK_SHADER


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SparkPreset:
    """
    Look and emission parameters for one kind of hit spark.

    :param color_inner: RGBA of fast / hot sparks (the burst's largest).
    :param color_outer: RGBA of slow / cool sparks.
    :param count:       Number of sparks emitted per hit.
    :param speed:       Maximum launch speed (world units/s).
    :param spread:      Cone spread in [0, 1]; scales the emission half-angle
                        (0 = tight beam, 1 = full hemisphere).
    :param gravity:     Downward acceleration (world units/s²).
    :param lifetime:    Maximum spark lifetime (seconds).
    :param size:        Maximum billboard half-size (world units).
    """

    color_inner: tuple
    color_outer: tuple
    count: int
    speed: float
    spread: float
    gravity: float
    lifetime: float
    size: float


#: Bright yellow-orange metal sparks, used for hull (destructible) hits.
METAL = SparkPreset(
    color_inner=(1.0, 0.95, 0.5, 1.0),
    color_outer=(1.0, 0.25, 0.0, 1.0),
    count=40,
    speed=6.0,
    spread=0.55,
    gravity=4.0,
    lifetime=0.7,
    size=0.12,
)

#: Cool blue-white sparks, used for shield hits.
ICE = SparkPreset(
    color_inner=(0.8, 1.0, 0.9, 1.0),
    color_outer=(0.0, 0.3, 1.0, 1.0),
    count=40,
    speed=5.0,
    spread=0.3,
    gravity=2.0,
    lifetime=0.7,
    size=0.12,
)

#: Violet, focused, low-gravity sparks (kept available; not currently wired).
MAGIC = SparkPreset(
    color_inner=(0.9, 0.5, 1.0, 1.0),
    color_outer=(0.3, 0.0, 0.8, 1.0),
    count=40,
    speed=8.0,
    spread=0.15,
    gravity=0.5,
    lifetime=0.7,
    size=0.12,
)

#: Gray-brown debris sparks, used for rock / asteroid terrain hits.
ROCK = SparkPreset(
    color_inner=(0.70, 0.62, 0.50, 1.0),
    color_outer=(0.40, 0.30, 0.20, 1.0),
    count=40,
    speed=8.0,
    spread=0.15,
    gravity=0.5,
    lifetime=0.7,
    size=0.12,
)


# ---------------------------------------------------------------------------
# Spark pool
# ---------------------------------------------------------------------------


class SparkPool(ParticleBuffer):
    """
    GPU-driven hit-spark pool: one shared billboard buffer for every spark.

    :param game: The game whose root node is the parent scene.
    """

    def __init__(self, game: FlightState) -> None:
        texture = game.app.asset_manager.get_asset(
            asset_type="texture", path=_SPARK_TEXTURE
        ).get_texture()
        texture.setMagfilter(Texture.FTLinear)
        texture.setMinfilter(Texture.FTLinear)
        # Clamp so the round sprite does not wrap at the quad edges.
        texture.setWrapU(Texture.WMClamp)
        texture.setWrapV(Texture.WMClamp)
        super().__init__(
            game=game,
            shader=_spark_shader(),
            columns=_SPARK_COLUMNS,
            texture=texture,
            additive=True,  # additive blending for a bright glow
            bin_order=20,
            task_name="spark_update",
        )

    def spawn(
        self,
        position: Point3,
        normal: Vec3,
        base_velocity: Vec3,
        preset: SparkPreset,
    ) -> None:
        """
        Emit one burst of hit sparks.

        Each spark's colour is premixed here (``color_outer`` → ``color_inner``
        by its size, a proxy for launch speed) and written per-particle, so
        concurrent bursts of different presets do not repaint each other.

        :param position:      World-space hit position.
        :param normal:        Surface normal at the hit point; sparks are
                              emitted in a cone around it.
        :param base_velocity: World velocity of the hit object, added to every
                              spark so they ride a moving target.
        :param preset:        Look + emission parameters (:data:`METAL`,
                              :data:`ICE`, :data:`ROCK`, :data:`MAGIC`).
        """
        if normal is None:
            return  # no impact surface to emit from

        # Work in numpy for the emission maths; convert the normal once (callers
        # pass a Panda Vec3). base_velocity is already a world-velocity array.
        normal_np = np.array([normal[0], normal[1], normal[2]], dtype=float)
        normal_np, tangent, bitangent = build_orthogonal_basis(normal_np)

        half_angle = preset.spread * (np.pi * 0.5) * SPARK_JET_ANGLE_SCALE
        # Apply the global tuning multipliers on top of the preset.
        base_size = preset.size * SPARK_SIZE_SCALE
        base_speed = preset.speed * SPARK_SPEED_SCALE
        max_size = base_size * 1.8
        inner = np.array(preset.color_inner)
        outer = np.array(preset.color_outer)
        # Every spark in the burst starts at the same point; build it once.
        pos = Point3(position[0], position[1], position[2])

        for _ in range(preset.count):
            slot_index = self.alloc_slot()
            if slot_index is None:
                break  # pool full — drop the rest of the burst

            direction = sample_direction_in_cone(
                normal=normal_np,
                tangent=tangent,
                bitangent=bitangent,
                half_angle_rad=half_angle,
            )
            velocity = (
                direction * random.uniform(base_speed * 0.3, base_speed) + base_velocity
            )
            size = base_size * random.uniform(0.5, 1.8)
            lifetime = random.uniform(preset.lifetime * 0.4, preset.lifetime)
            # Larger sparks launch faster, so size / max_size proxies "hot".
            hot = min(size / max_size, 1.0)
            color = outer + (inner - outer) * hot

            self.write_slot(
                slot_index,
                pos=pos,
                velocity=velocity,
                size=float(size),
                lifetime=float(lifetime),
                gravity=preset.gravity,
                spark_color=color,
            )
