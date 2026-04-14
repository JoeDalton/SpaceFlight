from __future__ import annotations

import math
import random

import numpy as np
from panda3d.core import Point3, Vec3, Vec4

from space_flight import DATAFILES_PATH
from space_flight.fx import ParticleBuffer, load_atlas
from space_flight.utils import (
    build_orthogonal_basis,
    sample_direction_in_cone,
    sample_unit_sphere,
)

# ===========================================================================
# EXPLOSION FX
# ===========================================================================

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

#: Number of fire / smoke particles emitted per explosion.
_FIRE_COUNT = 8
_SMOKE_COUNT = 8

#: Per-particle lifetime ranges (seconds).
_FIRE_LIFE_MIN, _FIRE_LIFE_MAX = 1.0, 1.5
_SMOKE_LIFE_MIN, _SMOKE_LIFE_MAX = 3.0, 5.0

#: Launch speed ranges along the emission direction (world units/s),
#: scaled by the explosion's *scale* parameter at spawn time.
_FIRE_SPEED_MIN, _FIRE_SPEED_MAX = 0.3, 1.5
_SMOKE_SPEED_MIN, _SMOKE_SPEED_MAX = 0.3, 1.5

#: Billboard half-size ranges (world units), scaled by *scale*.
_FIRE_SIZE_MIN, _FIRE_SIZE_MAX = 0.6, 1.5
_SMOKE_SIZE_MIN, _SMOKE_SIZE_MAX = 0.8, 2.0

#: Maximum absolute spin rate (radians/s). Actual spin is sampled uniformly
#: from ``[-_SPIN_MAX, +_SPIN_MAX]`` and packed into ``color.w``.
_SPIN_MAX = 3.0

#: Multiplier used when packing size into the integer part of ``color.w``.
#: Gives 0.01 world-unit precision and supports sizes up to ~999 units.
_SIZE_SCALE = 100.0

#: Smoke particles become visible this many seconds after fire.
#: Implemented as a future ``spawn_time`` offset in vertex data — no CPU
#: bookkeeping required.
_SMOKE_DELAY = 0.3

#: Radius of the random positional bias sphere, in units of *scale*.
#: Gives the burst a volumetric feel rather than all particles starting from
#: a single point.
_FIRE_POS_BIAS = 0.3
_SMOKE_POS_BIAS = 0.5

#: Fade-in duration as a fraction of each particle's total lifetime.
#: 0.3 means the particle reaches full opacity at 30% of its life.
_FIRE_FADEIN = 0.3
_SMOKE_FADEIN = 0.7

#: Paths to sprite atlas assets (PNG image + JSON rect descriptor).
_ATLAS_FIRE = DATAFILES_PATH / "sprites/particles/fire_atlas.png"
_ATLAS_SMOKE = DATAFILES_PATH / "sprites/particles/smoke_atlas.png"
_JSON_FIRE = DATAFILES_PATH / "sprites/particles/fire_atlas.json"
_JSON_SMOKE = DATAFILES_PATH / "sprites/particles/smoke_atlas.json"


# ---------------------------------------------------------------------------
# Explosion GLSL
# ---------------------------------------------------------------------------


def build_expl_vert(size_curve: str, fadein: float) -> str:
    """
    Generates the explosion vertex shader source.

    The shader is parameterised at Python level rather than using runtime
    ``#define`` values so that :func:`Shader.make` can cache the exact source
    string.

    **Unpacking** (inverse of the CPU-side packing in
    :meth:`_ExplosionBuffer.spawn_particle`):

    .. code-block:: glsl

        // color.w  →  size_spin
        base_size = floor(size_spin) / 100.0;
        spin_rate = (fract(size_spin) * 2.0 - 1.0) * SPIN_MAX;

        // texcoord.w  →  tile_life
        tile_index = floor(tile_life);
        lifetime   = fract(tile_life) * 10.0;

    :param size_curve: A GLSL expression (in terms of ``base_size`` and
                       ``frac``) that controls billboard size over the
                       particle's lifetime. Example::

                           "base_size * (0.3 + frac * 0.7)"  # grows from 30% to 100%

    :param fadein:     Fraction of lifetime over which alpha ramps 0 → 1.
                       ``0.0`` = instant appearance.
    :returns:          GLSL vertex shader source string.
    """
    return f"""
#version 140

in vec3 p3d_Vertex;           // world-space spawn position
in vec4 p3d_Color;            // velocity.xyz | size_spin.w
in vec4 p3d_MultiTexCoord0;   // corner.xy | spawn_time.z | tile_life.w

uniform mat4  p3d_ModelViewProjectionMatrix;
uniform float uTime;      // buffer clock (seconds since buffer creation)
uniform vec3  uCamRight;  // world-space camera right axis (billboard)
uniform vec3  uCamUp;     // world-space camera up    axis (billboard)

out vec4  vUV;    // xy = remapped corner in [0,1], z = tile_index (float)
out float vAlpha; // combined fade-out * fade-in * alive gate

void main() {{
    vec3  vel       = p3d_Color.xyz;
    float size_spin = p3d_Color.w;

    // --- Unpack color.w → base_size + spin_rate ---
    // int  part: size stored as round(size * 100), so divide by 100.
    // frac part: spin was normalised to [0,1) via (spin/SPIN_MAX+1)/2, invert that.
    float base_size = floor(size_spin) / 100.0;
    float spin_rate = (fract(size_spin) * 2.0 - 1.0) * {_SPIN_MAX:.4f};

    vec2  corner     = p3d_MultiTexCoord0.xy;
    float spawn_time = p3d_MultiTexCoord0.z;   // absolute clock value at birth
    float tile_life  = p3d_MultiTexCoord0.w;

    // --- Unpack texcoord.w → tile_index + lifetime ---
    // int  part: atlas sprite index (0, 1, 2 …)
    // frac part: lifetime / 10.0, so multiply back by 10 to get seconds.
    float tile_index = floor(tile_life);
    float lifetime   = fract(tile_life) * 10.0;

    // --- Particle age ---
    // t < 0 during the spawn_delay window → particle is not yet born.
    float t = uTime - spawn_time;
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;
    float frac  = clamp(t / max(lifetime, 0.001), 0.0, 1.0);

    // --- Fade-in ramp ---
    // Alpha rises linearly from 0 to 1 over the first fadein_end fraction of lifetime.
    float fadein_end = {fadein:.4f};
    float fade_in    = (fadein_end > 0.0)
                       ? clamp(frac / fadein_end, 0.0, 1.0)
                       : 1.0;

    // --- World-space centre position (linear motion, no gravity) ---
    // max(t, 0) prevents the particle from moving backwards during the delay.
    vec3 pos = p3d_Vertex + vel * max(t, 0.0);

    // --- Billboard size (caller-supplied growth curve, zeroed when dead) ---
    float sz = ({size_curve}) * alive;

    // --- Spin: rotate corner around quad centre ---
    float angle = spin_rate * max(t, 0.0);
    float cs = cos(angle), sn = sin(angle);
    vec2 rot = vec2(cs * corner.x - sn * corner.y,
                    sn * corner.x + cs * corner.y);

    // --- Billboard: project rotated corner onto camera axes ---
    pos += uCamRight * rot.x * sz + uCamUp * rot.y * sz;

    gl_Position = p3d_ModelViewProjectionMatrix * vec4(pos, 1.0);

    // Remap corner [-1,1] → [0,1] for UV interpolation in the fragment shader.
    // tile_index is passed as a float in z; the fragment shader recovers it
    // with int(vUV.z + 0.5) to avoid float rounding errors.
    vUV    = vec4(corner * 0.5 + 0.5, tile_index, 0.0);
    vAlpha = (1.0 - frac) * fade_in * alive;
}}
"""


def build_expl_frag(n_tiles: int) -> str:
    """
    Generates the explosion fragment shader source.

    Because GLSL 140 forbids dynamic indexing into uniform arrays with a
    non-constant index, each atlas rect is uploaded as a separate uniform
    (``uTileRect0``, ``uTileRect1``, …) and selected at runtime via an
    ``if / else`` chain.

    :param n_tiles: Number of sprite frames in the atlas. Controls how many
                    ``uTileRect`` uniforms are declared and how long the
                    selection chain is.
    :returns:       GLSL fragment shader source string.
    """
    # One uniform vec4 per tile: (u_min, v_min, u_size, v_size) in UV space.
    uniforms = "\n".join(f"uniform vec4 uTileRect{i};" for i in range(n_tiles))
    # Runtime selection chain — the only way to index by a non-const in GLSL 140.
    branches = "\n    ".join(
        f"{'if' if i == 0 else 'else if'} (idx == {i}) rect = uTileRect{i};"
        for i in range(n_tiles)
    )
    return f"""
#version 140

uniform sampler2D p3d_Texture0;  // sprite atlas (auto-bound via default TextureStage)
{uniforms}

in vec4  vUV;    // xy = [0,1] corner UV,  z = tile_index as float
in float vAlpha; // combined opacity from the vertex shader

out vec4 fragColor;

void main() {{
    // Early discard avoids the texture fetch for fully invisible fragments.
    if (vAlpha <= 0.001) discard;

    // Recover integer tile index; +0.5 before truncation guards against
    // minor floating-point drift accumulated across the pipeline.
    int  idx  = int(vUV.z + 0.5);
    vec4 rect = uTileRect0;   // default; overwritten by the branch below
    {branches}

    // rect.xy = bottom-left UV corner of the selected tile in the atlas.
    // rect.zw = width / height of the tile in UV space.
    // vUV.xy  = interpolated [0,1] position within the billboard quad.
    vec2 uv  = rect.xy + vUV.xy * rect.zw;
    vec4 tex = texture(p3d_Texture0, uv);

    fragColor = vec4(tex.rgb, tex.a * vAlpha);
}}
"""


# ---------------------------------------------------------------------------
# Explosion buffer
# ---------------------------------------------------------------------------


class _ExplosionBuffer(ParticleBuffer):
    """
    Thin :class:`ParticleBuffer` sub-class for one explosion layer (fire or smoke).

    Extends the base class by uploading atlas rect uniforms at construction
    time and providing :meth:`spawn_particle` with the explosion-specific
    packing logic.

    :param game:     Parent game
    :param vert_src:  Vertex shader source (from :func:`_expl_vert`).
    :param frag_src:  Fragment shader source (from :func:`_expl_frag`).
    :param texture:   Sprite atlas :class:`Texture`.
    :param tile_rects: List of ``(u, v, uw, vh)`` atlas rect tuples.
    :param bin_order: Transparent bin sort order.
    :param additive:  Whether to use additive blending.
    :param task_name: Unique Panda3D task name.
    """

    def __init__(
        self,
        game,
        vert_src,
        frag_src,
        texture,
        tile_rects,
        bin_order,
        additive,
        task_name,
    ):
        super().__init__(
            game=game,
            vert_src=vert_src,
            frag_src=frag_src,
            texture=texture,
            additive=additive,
            bin_order=bin_order,
            task_name=task_name,
        )
        # Upload each atlas rect as an individual uniform because GLSL 140
        # does not support dynamic uniform-array indexing.
        for i, (u, v, uw, vh) in enumerate(tile_rects):
            self.set_input(f"uTileRect{i}", Vec4(u, v, uw, vh))
        self._n_tiles = len(tile_rects)

    def spawn_particle(
        self,
        pos: np.ndarray,
        vel: np.ndarray,
        size: float,
        lifetime: float,
        tile_index: int,
        spin_rate: float,
        delay: float = 0.0,
    ):
        """
        Allocate a free slot and write one explosion particle.

        **Packing** applied before calling :meth:`~ParticleBuffer.write_slot`:

        .. code-block:: text

            color.w (size_spin):
                int  part = round(size * 100)          max size ≈ 999 units
                frac part = (spin_rate / SPIN_MAX + 1) / 2   mapped to [0, 1)

            texcoord.w (tile_life):
                int  part = tile_index
                frac part = lifetime / 10.0            max lifetime = 9.99 s

        :param pos:        World-space spawn position (positional bias already
                           applied by the caller).
        :param vel:        Initial velocity in world units per second.
        :param size:       Billboard half-size in world units.
        :param lifetime:   Particle lifetime in seconds (max 9.99).
        :param tile_index: Atlas sprite index.
        :param spin_rate:  Rotation speed in radians/s; negative = CCW.
        :param delay:      Seconds before the particle appears (smoke offset).
        """
        slot_index = self.alloc_slot()
        if slot_index is None:
            return  # pool full — silently drop this particle

        # Pack size (int part) and spin (frac part) into a single float.
        # spin_norm maps [-SPIN_MAX, +SPIN_MAX] → [0, 1) so it fits cleanly
        # in the fractional part without colliding with the integer size.
        spin_norm = (spin_rate / _SPIN_MAX + 1.0) * 0.5
        color_w = float(round(size * _SIZE_SCALE)) + min(spin_norm, 0.999)

        # Pack tile_index (int part) and lifetime/10 (frac part) into one float.
        texcoord_w = float(int(tile_index)) + min(lifetime / 10.0, 0.999)

        self.write_slot(
            slot_index=slot_index,
            pos=Point3(*pos),
            vel=Vec3(*vel),
            color_w=color_w,
            texcoord_w=texcoord_w,
            spawn_delay=delay,
            slot_duration=lifetime,  # explicit — avoids the default frac*10 decode
        )


# ---------------------------------------------------------------------------
# Explosion pool
# ---------------------------------------------------------------------------


class ExplosionPool:
    """
    Top-level manager that owns the fire and smoke :class:`_ExplosionBuffer` instances.

    :param game: The game whose root node is the parent scene
    """

    def __init__(self, game):
        self.game = game
        fire_tex, self._fire_rects = load_atlas(
            game=self.game, texture_path=_ATLAS_FIRE, json_path=_JSON_FIRE
        )
        smoke_tex, self._smoke_rects = load_atlas(
            game=self.game, texture_path=_ATLAS_SMOKE, json_path=_JSON_SMOKE
        )

        # Fire grows slightly over its lifetime; smoke does the same but with
        # a longer fade-in so it appears to emerge from the dissipating fire.
        self._fire = _ExplosionBuffer(
            game,
            build_expl_vert("base_size * (0.3 + frac * 0.7)", _FIRE_FADEIN),
            build_expl_frag(len(self._fire_rects)),
            fire_tex,
            self._fire_rects,
            bin_order=20,
            additive=False,
            task_name="exp_fire_update",
        )
        self._smoke = _ExplosionBuffer(
            game,
            build_expl_vert("base_size * (0.3 + frac * 0.7)", _SMOKE_FADEIN),
            build_expl_frag(len(self._smoke_rects)),
            smoke_tex,
            self._smoke_rects,
            bin_order=20,
            additive=False,
            task_name="exp_smoke_update",
        )

    def spawn(
        self, position: Point3, scale: float, base_velocity: Vec3, normal: Vec3 = None
    ):
        """
        Emit one explosion burst.

        :param position:      World-space explosion centre.
        :param scale:    Overall size / speed multiplier applied to particle
                         sizes, speeds, and positional bias radii.
        :param base_velocity: Inherited velocity added to all particles (e.g. from
                         a moving object at the moment of impact).
        :param normal:   Surface normal at the impact point. Particles are
                         emitted in a hemisphere biased toward this direction.
                         Fire uses a wider cone (0.55π) than smoke (0.45π).
        """
        normal, tangent, bitangent = build_orthogonal_basis(normal)

        for _ in range(_FIRE_COUNT):
            vel = (
                sample_direction_in_cone(
                    normal=normal,
                    tangent=tangent,
                    bitangent=bitangent,
                    half_angle_rad=math.pi * 0.55,
                )
                * random.uniform(_FIRE_SPEED_MIN, _FIRE_SPEED_MAX)
                * scale
                + base_velocity
            )
            bias = sample_unit_sphere() * (_FIRE_POS_BIAS * scale)
            self._fire.spawn_particle(
                pos=position + bias,
                vel=vel,
                size=random.uniform(_FIRE_SIZE_MIN, _FIRE_SIZE_MAX) * scale,
                lifetime=random.uniform(_FIRE_LIFE_MIN, _FIRE_LIFE_MAX),
                tile_index=random.randrange(len(self._fire_rects)),
                spin_rate=random.uniform(0.3, 2.0) * random.choice([-1, 1]),
                delay=0.0,  # fire is immediate
            )

        for _ in range(_SMOKE_COUNT):
            vel = (
                sample_direction_in_cone(
                    normal=normal,
                    tangent=tangent,
                    bitangent=bitangent,
                    half_angle_rad=math.pi * 0.45,
                )
                * random.uniform(_SMOKE_SPEED_MIN, _SMOKE_SPEED_MAX)
                * scale
                + base_velocity
            )
            bias = sample_unit_sphere() * (_SMOKE_POS_BIAS * scale)
            self._smoke.spawn_particle(
                pos=position + bias + base_velocity * _SMOKE_DELAY,
                vel=vel,
                size=random.uniform(_SMOKE_SIZE_MIN, _SMOKE_SIZE_MAX) * scale,
                lifetime=random.uniform(_SMOKE_LIFE_MIN, _SMOKE_LIFE_MAX),
                tile_index=random.randrange(len(self._smoke_rects)),
                spin_rate=random.uniform(0.1, 0.6) * random.choice([-1, 1]),
                delay=_SMOKE_DELAY,  # smoke trails fire by _SMOKE_DELAY s
            )

    def clean(self):
        """
        Destroy both particle buffers and their update tasks.
        """
        self._fire.clean()
        self._smoke.clean()
