from __future__ import annotations

import math
import random
from collections import namedtuple
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import Point3, Shader, Texture, Vec3

from space_flight import DATAFILES_PATH
from space_flight.fx import ParticleBuffer, load_atlas
from space_flight.utils import (
    build_orthogonal_basis,
    sample_direction_in_cone,
    sample_unit_sphere,
)

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ===========================================================================
# FIRE + SMOKE FX
# ===========================================================================
#
# One shared fire/smoke billboard pool (:class:`FireSmokePool`) feeding three
# effects: one-shot explosions (burst), laser-hit puffs (hit_burst), and the
# continuous per-ship damage/death trail (trail_smoke / trail_fire, driven from
# fx/damage_fx.py). The "explosion" naming below survives only where it names the
# literal shader asset (shaders/explosion.vert) and the death-explosion tunables.

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
# Public (no leading underscore): these are the look/behaviour knobs meant to be
# tuned. Structural constants (asset paths, vertex columns, the shader) stay
# module-private.

#: Number of fire / smoke particles emitted per death explosion.
FIRE_COUNT = 8
SMOKE_COUNT = 8

#: Per-particle lifetime ranges (seconds).
FIRE_LIFE_MIN, FIRE_LIFE_MAX = 1.0, 1.5
SMOKE_LIFE_MIN, SMOKE_LIFE_MAX = 3.0, 5.0

#: Launch speed ranges along the emission direction (world units/s),
#: scaled by the explosion's *scale* parameter at spawn time.
FIRE_SPEED_MIN, FIRE_SPEED_MAX = 0.3, 1.5
SMOKE_SPEED_MIN, SMOKE_SPEED_MAX = 0.3, 1.5

#: Billboard half-size ranges (world units), scaled by *scale*.
FIRE_SIZE_MIN, FIRE_SIZE_MAX = 0.6, 1.5
SMOKE_SIZE_MIN, SMOKE_SIZE_MAX = 0.8, 2.0

#: Smoke particles become visible this many seconds after fire.
#: Implemented as a future spawn_time offset in vertex data — no CPU
#: bookkeeping required.
SMOKE_DELAY = 0.3

#: Radius of the random positional bias sphere, in units of *scale*.
#: Gives the burst a volumetric feel rather than all particles starting from
#: a single point.
FIRE_POS_BIAS = 0.3
SMOKE_POS_BIAS = 0.5

#: Fade-in duration as a fraction of each particle's total lifetime.
#: 0.3 means the particle reaches full opacity at 30% of its life.
#: Uploaded to the shader as the uFadein uniform.
FIRE_FADEIN = 0.3
SMOKE_FADEIN = 0.7

#: Paths to sprite atlas assets (PNG image + JSON rect descriptor).
_ATLAS_FIRE = DATAFILES_PATH / "sprites/particles/fire_atlas.png"
_ATLAS_SMOKE = DATAFILES_PATH / "sprites/particles/smoke_atlas.png"
_JSON_FIRE = DATAFILES_PATH / "sprites/particles/fire_atlas.json"
_JSON_SMOKE = DATAFILES_PATH / "sprites/particles/smoke_atlas.json"

# ---------------------------------------------------------------------------
# Hit-explosion knobs
# ---------------------------------------------------------------------------
# A small secondary explosion triggered on *some* laser hits (see
# FireSmokePool.hit_burst and collisions.py). Tune these to taste.

#: Explosion scale multiplier for a hit burst. Multiplies the particle sizes /
#: speeds / bias radii above; not a literal metre radius.
HIT_EXPLOSION_SCALE = 2.0

#: Billboard counts for a hit burst — kept well below a death explosion's
#: (FIRE_COUNT / SMOKE_COUNT) because hits are frequent (performance).
HIT_EXPLOSION_FIRE_COUNT = 3
HIT_EXPLOSION_SMOKE_COUNT = 2

#: Launch-speed multiplier for a hit burst (lower than a death explosion, so
#: the burst stays tight around the impact rather than spraying out).
HIT_EXPLOSION_SPEED_SCALE = 0.5

#: Emission-cone (jet) half-angle multiplier for a hit burst (1.0 = the same
#: fire/smoke cones a death explosion uses).
HIT_EXPLOSION_JET_ANGLE_SCALE = 1.0


# ---------------------------------------------------------------------------
# Explosion shader
# ---------------------------------------------------------------------------

#: The explosion shader is shared by both buffers (fire and smoke); load it
#: once, lazily. Fire and smoke differ only by the uFadein uniform.
_EXPLOSION_SHADER = None


def _explosion_shader() -> Shader:
    """
    Load (once) and return the shared explosion GLSL shader.

    :return: The shared explosion :class:`Shader`.
    """
    global _EXPLOSION_SHADER
    if _EXPLOSION_SHADER is None:
        _EXPLOSION_SHADER = Shader.load(
            Shader.SL_GLSL,
            vertex=DATAFILES_PATH / "shaders/explosion.vert",
            fragment=DATAFILES_PATH / "shaders/explosion.frag",
        )
    return _EXPLOSION_SHADER


# ---------------------------------------------------------------------------
# Explosion buffer
# ---------------------------------------------------------------------------

#: Per-particle vertex columns for the explosion effect, appended to the shared
#: billboard columns owned by :class:`ParticleBuffer`.
_EXPLOSION_COLUMNS = [
    ("velocity", 3),
    ("size", 1),
    ("spin", 1),
    ("lifetime", 1),
    ("tile_rect", 4),
]


class _FireSmokeBuffer(ParticleBuffer):
    """
    Thin :class:`ParticleBuffer` sub-class for one billboard layer (fire or smoke).

    Extends the base class with the shared explosion shader, a per-layer
    fade-in value, and a :meth:`spawn_particle` that resolves each particle's
    atlas tile to its UV rect.

    :param game:       Parent game
    :param texture:    Sprite atlas :class:`Texture`.
    :param tile_rects: List of (u, v, uw, vh) atlas rect tuples.
    :param fadein:     Fraction of lifetime over which alpha ramps 0 → 1,
                       uploaded as the uFadein uniform.
    :param bin_order:  Transparent bin sort order.
    :param additive:   Whether to use additive blending.
    :param task_name:  Unique Panda3D task name.
    """

    def __init__(
        self,
        game: FlightState,
        texture: Texture,
        tile_rects: list,
        fadein: float,
        bin_order: int,
        additive: bool,
        task_name: str,
    ) -> None:
        super().__init__(
            game=game,
            shader=_explosion_shader(),
            columns=_EXPLOSION_COLUMNS,
            texture=texture,
            additive=additive,
            bin_order=bin_order,
            task_name=task_name,
        )
        self.tile_rects = tile_rects
        self.set_input("uFadein", fadein)

    def spawn_particle(
        self,
        pos: np.ndarray,
        vel: np.ndarray,
        size: float,
        lifetime: float,
        tile_index: int,
        spin_rate: float,
        delay: float = 0.0,
    ) -> None:
        """
        Allocate a free slot and write one explosion particle.

        Every value goes straight into its own vertex column (no packing); the
        atlas *tile_index* is resolved to its UV rect here so the shader can
        sample the sprite directly.

        :param pos:        World-space spawn position (positional bias already
                           applied by the caller).
        :param vel:        Initial velocity in world units per second.
        :param size:       Billboard half-size in world units.
        :param lifetime:   Particle lifetime in seconds.
        :param tile_index: Atlas sprite index.
        :param spin_rate:  Rotation speed in radians/s; negative = CCW.
        :param delay:      Seconds before the particle appears (smoke offset).
        """
        slot_index = self.alloc_slot()
        if slot_index is None:
            return  # pool full — silently drop this particle

        self.write_slot(
            slot_index,
            pos=Point3(*pos),
            spawn_delay=delay,
            velocity=Vec3(*vel),
            size=size,
            spin=spin_rate,
            lifetime=lifetime,
            tile_rect=self.tile_rects[tile_index],
        )


# ---------------------------------------------------------------------------
# Per-layer emission config
# ---------------------------------------------------------------------------

#: Bundles the constants that differ between the fire and smoke layers so a
#: single :func:`_emit_layer` drives both. speed / size / life / spin
#: are (min, max) ranges; cone_half_angle is the emission-cone
#: half-angle (radians); delay offsets the layer in time.
_Layer = namedtuple("_Layer", "cone_half_angle speed size life spin pos_bias delay")

_FIRE_LAYER = _Layer(
    cone_half_angle=math.pi * 0.55,
    speed=(FIRE_SPEED_MIN, FIRE_SPEED_MAX),
    size=(FIRE_SIZE_MIN, FIRE_SIZE_MAX),
    life=(FIRE_LIFE_MIN, FIRE_LIFE_MAX),
    spin=(0.3, 2.0),
    pos_bias=FIRE_POS_BIAS,
    delay=0.0,  # fire is immediate
)

_SMOKE_LAYER = _Layer(
    cone_half_angle=math.pi * 0.45,  # narrower than fire
    speed=(SMOKE_SPEED_MIN, SMOKE_SPEED_MAX),
    size=(SMOKE_SIZE_MIN, SMOKE_SIZE_MAX),
    life=(SMOKE_LIFE_MIN, SMOKE_LIFE_MAX),
    spin=(0.1, 0.6),
    pos_bias=SMOKE_POS_BIAS,
    delay=SMOKE_DELAY,  # smoke trails the fire
)

# ---------------------------------------------------------------------------
# Damage / death trail layers
# ---------------------------------------------------------------------------
# Layers for the continuous per-ship damage trail (see fx/damage_fx.py). They
# differ from the explosion layers above only in lifetime and delay: their
# lifetimes are deliberately short so that, emitted every frame across many
# damaged ships into this one shared pool, only a handful are ever alive at once.
# Long-lived trail particles would saturate the pool (starving real explosions)
# and flood the screen with transparent overdraw.

#: Trail particle lifetimes (seconds). Explicit, not scaled from the explosion
#: ranges, so retuning an explosion's lifetime never silently shifts the trail.
TRAIL_SMOKE_LIFE_MIN, TRAIL_SMOKE_LIFE_MAX = 0.7, 1.1
TRAIL_FIRE_LIFE_MIN, TRAIL_FIRE_LIFE_MAX = 0.4, 0.6

_TRAIL_SMOKE_LAYER = _SMOKE_LAYER._replace(
    life=(TRAIL_SMOKE_LIFE_MIN, TRAIL_SMOKE_LIFE_MAX),
    delay=0.0,  # a continuous trail has no fire-to-smoke handoff to wait for
)
_TRAIL_FIRE_LAYER = _FIRE_LAYER._replace(
    life=(TRAIL_FIRE_LIFE_MIN, TRAIL_FIRE_LIFE_MAX),
)


def _emit_layer(
    buffer: _FireSmokeBuffer,
    layer: _Layer,
    count: int,
    position: np.ndarray,
    base_velocity: np.ndarray,
    basis: tuple,
    scale: float,
    speed_scale: float,
    jet_angle_scale: float,
) -> None:
    """
    Emit *count* particles of one layer into *buffer*.

    Each layer (a :data:`_Layer`) carries its own explicit lifetime range, so
    long-lived explosion smoke and short-lived trail smoke are simply different
    layers rather than one range scaled at the call site.

    :param buffer:      The :class:`_FireSmokeBuffer` to spawn into.
    :param layer:       The :data:`_Layer` config for this layer.
    :param count:       Number of particles to emit.
    :param position:    World-space burst centre (numpy array).
    :param base_velocity: Inherited velocity added to every particle (array).
    :param basis:       (normal, tangent, bitangent) from
                        :func:`build_orthogonal_basis`. normal is None
                        for a death explosion or a damage trail (no impact
                        surface): the cone sampler then returns a zero direction,
                        so the particles carry only *base_velocity* plus
                        positional bias and do not fan out.
    :param scale:       Overall size/speed/bias multiplier.
    :param speed_scale: Extra launch-speed multiplier (hit bursts use < 1).
    :param jet_angle_scale: Multiplier on the emission-cone half-angle.
    """
    normal, tangent, bitangent = basis
    speed_min, speed_max = layer.speed
    size_min, size_max = layer.size
    life_min, life_max = layer.life
    spin_min, spin_max = layer.spin

    for _ in range(count):
        direction = sample_direction_in_cone(
            normal=normal,
            tangent=tangent,
            bitangent=bitangent,
            half_angle_rad=layer.cone_half_angle * jet_angle_scale,
        )
        vel = (
            direction * random.uniform(speed_min, speed_max) * scale * speed_scale
            + base_velocity
        )
        bias = sample_unit_sphere() * (layer.pos_bias * scale)
        buffer.spawn_particle(
            pos=position + bias + base_velocity * layer.delay,
            vel=vel,
            size=random.uniform(size_min, size_max) * scale,
            lifetime=random.uniform(life_min, life_max),
            tile_index=random.randrange(len(buffer.tile_rects)),
            spin_rate=random.uniform(spin_min, spin_max) * random.choice([-1, 1]),
            delay=layer.delay,
        )


# ---------------------------------------------------------------------------
# Fire + smoke pool
# ---------------------------------------------------------------------------


class FireSmokePool:
    """
    Shared fire + smoke billboard system.

    Owns the two :class:`_FireSmokeBuffer` layers (fire, smoke) and is the single
    object the rest of the game emits fire/smoke into, through three intents:

    - :meth:`burst` — a one-shot explosion (a ship or subsystem dying).
    - :meth:`hit_burst` — the small secondary puff of a laser impact.
    - :meth:`trail_smoke` / :meth:`trail_fire` — the continuous per-ship damage
      and death trail (see :mod:`space_flight.fx.damage_fx`).

    All three share the same two buffers, so their particles are drawn together
    and compete for the same pool budget.

    :param game: The game whose root node is the parent scene
    """

    def __init__(self, game: FlightState) -> None:
        self.game = game
        fire_tex, self.fire_rects = load_atlas(
            game=self.game, texture_path=_ATLAS_FIRE, json_path=_JSON_FIRE
        )
        smoke_tex, self.smoke_rects = load_atlas(
            game=self.game, texture_path=_ATLAS_SMOKE, json_path=_JSON_SMOKE
        )

        # Fire and smoke share one shader and size-growth curve; they differ
        # only in fade-in (smoke's longer fade makes it appear to emerge from
        # the dissipating fire).
        self.fire = _FireSmokeBuffer(
            game,
            texture=fire_tex,
            tile_rects=self.fire_rects,
            fadein=FIRE_FADEIN,
            bin_order=20,
            additive=False,
            task_name="fire_update",
        )
        self.smoke = _FireSmokeBuffer(
            game,
            texture=smoke_tex,
            tile_rects=self.smoke_rects,
            fadein=SMOKE_FADEIN,
            bin_order=20,
            additive=False,
            task_name="smoke_update",
        )

    # ------------------------------------------------------------------
    # Emitters
    # ------------------------------------------------------------------
    def burst(
        self,
        position: Point3,
        scale: float,
        base_velocity: Vec3,
        normal: Vec3 | None = None,
        *,
        fire_count: int = FIRE_COUNT,
        smoke_count: int = SMOKE_COUNT,
        speed_scale: float = 1.0,
        jet_angle_scale: float = 1.0,
    ) -> None:
        """
        Emit one one-shot explosion burst (both fire and smoke layers).

        :param position: World-space explosion centre (Panda Point3 or a
                         length-3 array).
        :param scale:    Overall size / speed multiplier applied to particle
                         sizes, speeds, and positional bias radii.
        :param base_velocity: Inherited velocity (length-3 array) added to all
                         particles, e.g. from a moving object at impact.
        :param normal:   Surface normal at the impact point (Point3Vec3
                         or array); particles fan out in a cone around it. Pass
                         None (the default, used by death explosions) for no
                         directional spread — see :func:`_emit_layer`.
        :param fire_count:  Number of fire particles (defaults to FIRE_COUNT).
        :param smoke_count: Number of smoke particles (defaults to SMOKE_COUNT).
        :param speed_scale: Extra multiplier on launch speed, on top of *scale*
                         (< 1 keeps the burst tighter — used by hit explosions).
        :param jet_angle_scale: Multiplier on the fire/smoke emission-cone
                         half-angles (1.0 = the default cones).
        """
        position, basis = self._prepare(position, normal)
        _emit_layer(
            self.fire,
            _FIRE_LAYER,
            fire_count,
            position,
            base_velocity,
            basis,
            scale,
            speed_scale,
            jet_angle_scale,
        )
        _emit_layer(
            self.smoke,
            _SMOKE_LAYER,
            smoke_count,
            position,
            base_velocity,
            basis,
            scale,
            speed_scale,
            jet_angle_scale,
        )

    def hit_burst(self, position: Point3, normal: Vec3, base_velocity: Vec3) -> None:
        """
        Emit a small, cheap secondary explosion for a laser hit.

        A contained burst (few billboards, low speed) sized/shaped by the
        HIT_EXPLOSION_* module knobs, biased along the impact *normal* like
        the hit sparks.

        :param position:      World-space impact point.
        :param normal:        Surface normal at the impact point.
        :param base_velocity: Velocity of the hit object, inherited by the burst.
        """
        self.burst(
            position=position,
            scale=HIT_EXPLOSION_SCALE,
            base_velocity=base_velocity,
            normal=normal,
            fire_count=HIT_EXPLOSION_FIRE_COUNT,
            smoke_count=HIT_EXPLOSION_SMOKE_COUNT,
            speed_scale=HIT_EXPLOSION_SPEED_SCALE,
            jet_angle_scale=HIT_EXPLOSION_JET_ANGLE_SCALE,
        )

    def trail_smoke(
        self, position: Vec3, base_velocity: Vec3, scale: float, count: int
    ) -> None:
        """
        Emit one puff of the continuous damage/death *smoke* trail.

        Short-lived (see :data:`_TRAIL_SMOKE_LAYER`) so many ships can trail at
        once without saturating the pool. No directional spread — the puff sits
        where it is laid and rides *base_velocity* (see :mod:`.damage_fx`).

        :param position:      World-space emission point.
        :param base_velocity: Velocity the puff inherits (a fraction of the
                              ship's, so the trail lags behind it).
        :param scale:         Size multiplier for the puff.
        :param count:         Number of smoke billboards to emit.
        """
        position, basis = self._prepare(position, normal=None)
        _emit_layer(
            self.smoke,
            _TRAIL_SMOKE_LAYER,
            count,
            position,
            base_velocity,
            basis,
            scale,
            1.0,
            1.0,
        )

    def trail_fire(
        self, position: Vec3, base_velocity: Vec3, scale: float, count: int
    ) -> None:
        """
        Emit one puff of the continuous damage/death *fire* trail.

        The fire counterpart to :meth:`trail_smoke`, even shorter-lived (see
        :data:`_TRAIL_FIRE_LAYER`); rides fully with the ship at its hull.

        :param position:      World-space emission point.
        :param base_velocity: Velocity the puff inherits (the ship's own).
        :param scale:         Size multiplier for the puff.
        :param count:         Number of fire billboards to emit.
        """
        position, basis = self._prepare(position, normal=None)
        _emit_layer(
            self.fire,
            _TRAIL_FIRE_LAYER,
            count,
            position,
            base_velocity,
            basis,
            scale,
            1.0,
            1.0,
        )

    @staticmethod
    def _prepare(position, normal):
        """
        Normalise a caller's position/normal into the numpy form the emitter
        maths expects, and build the emission basis.

        Callers may pass Panda vectors or numpy arrays; base_velocity is already
        a world-velocity array from every caller.

        :param position: World-space emission point (Point3 or length-3 array)
        :param normal:   Surface normal, or None for no directional spread
        :return: (position array, orthogonal basis tuple)
        """
        position = np.array([position[0], position[1], position[2]], dtype=float)
        if normal is not None:
            normal = np.array([normal[0], normal[1], normal[2]], dtype=float)
        return position, build_orthogonal_basis(normal)

    def clean(self) -> None:
        """
        Destroy both particle buffers and their update tasks.
        """
        self.fire.clean()
        self.smoke.clean()
