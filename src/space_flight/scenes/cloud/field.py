"""
field.py — A field of in-scene billboard clouds: geometry, shaders, sorting,
wind/recycling, plus the game-facing wrapper.

Clouds are ordinary 3D geometry parented under a node in render.  They
depth-test against whatever is already in the depth buffer, so occlusion by
ships / terrain / cockpit is handled by the hardware — no depth prepass, no
composite, no power-of-two handling, no scene-depth plumbing, no near/far
coupling.

Configuration lives in ONE place: :class:`CloudField`'s constructor (and the
per-type :class:`CloudLayer` records it takes).  noise.py owns what a cloud type
LOOKS like (its density field), cloud.py places billboards wherever that field
says there is cloud, and this module turns them into a drawable, animated field.
:class:`Clouds` is a thin game adapter over :class:`CloudField`.

There are no cloud objects
--------------------------
A layer is one continuous density field spanning a slab of sky; the clouds you
see are its features.  So a layer is configured by describing the SKY (how big
the formations are, how much of the sky they cover, how thick the deck is) and
never by a cloud count — how many billboards get placed follows from how much
cloud the field defines (see cloud.sample_field_particles).

Transparency model
------------------
Particles use premultiplied-alpha "over" blending (frag = vec4(rgb*a, a) with
M_add, O_one, O_one_minus_incoming_alpha).  "over" is order-dependent, so the
particles must be drawn back-to-front; the order is kept correct by sorting:

  * Every particle of every layer lives in ONE Geom (4 verts each); the static
    vertex data (local pos, quad corner, radius, sprite rect, cell id) is
    uploaded once and never again — only the triangle INDEX buffer is reordered.
  * The sort is per CELL (segmented): cells are ordered by centre distance,
    particles within a cell by distance.  Intra- and inter-cell ordering are both
    correct; cross-cell interleaving is only approximate where two cells' clouds
    span the boundary between them.
  * Cell populations vary — a cell holds however many billboards its share of the
    field needed — so the particle arrays are RAGGED, with a cell_start offsets
    table.  Padding every cell to the largest would cost about 3x the vertex
    memory at cumulus coverage and buy nothing; the per-frame re-sort stays fully
    vectorised over a ragged layout via one lexsort.
  * The sort + index gather is spread across resort_frames frames in a
    round-robin (see :meth:`CloudField._restage`): one atomic index upload per
    cycle — no per-frame spike, at the cost of a few frames' draw-order latency.

Particle positions are stored RELATIVE to their cell's centre; the centres are
moved each frame by wind and recycled toroidally around the camera, so the heavy
vertex data never changes — only a small per-cell parameter texture is
re-uploaded.  The billboard is built in the vertex shader, so the only per-frame
CPU work is the incremental restage.

Recycling is seamless where it can be: a cell teleports by one box width, and
when that width is a whole number of the field's noise periods it lands where the
field is bit-identical, so no fade is needed to hide the jump (see
cloud.snap_to_noise_period).  Only an anisotropic field, whose two horizontal
periods differ, still needs a fade band.

Draw order vs. the rest of the scene
------------------------------------
The clouds draw in their own "cloud" bin at sort 25, between "opaque" and
"transparent" (see :func:`_ensure_cloud_bins`), writing no depth. Sitting before
the "transparent" bin means every translucent effect in the game (explosions,
sparks, lasers, shields, the 2D planet, speed dust) is drawn after the clouds and
composites over them correctly — with no per-effect bin juggling.

Since the clouds write no depth, an effect BEHIND a dense cloud still paints over
it rather than being hidden by it. Fixing that needs a depth surface, and the
cloud has no single correct one: no billboard is ever opaque on its own, so
opacity only exists as a stack of them.

Mixing types: pass several :class:`CloudLayer` entries (e.g. cumulus + cirrus).
Each has its OWN density field, and they share one Geom, so the single global
sort orders every type together and the premultiplied-over blend superposes their
optical depths along each view ray — which is why no fragment ever has to
evaluate more than one field.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, fields, replace
from typing import Optional

import numpy as np
from panda3d.core import (
    ColorBlendAttrib,
    CullBinManager,
    Geom,
    GeomEnums,
    GeomNode,
    GeomTriangles,
    GeomVertexArrayFormat,
    GeomVertexData,
    GeomVertexFormat,
    InternalName,
    LVecBase4f,
    OmniBoundingVolume,
    PTA_LVecBase4f,
    SamplerState,
    Shader,
    Texture,
    TransparencyAttrib,
    Vec3,
)

from space_flight import DATAFILES_PATH
from space_flight.scenes.cloud.cloud import (
    PRESETS,
    CloudQuality,
    CloudType,
    at_quality,
    atlas_mean_alpha,
    load_cloud_atlas,
    sample_field_particles_iter,
    snap_to_noise_period,
)
from space_flight.scenes.cloud.noise import (
    LAYER_VEC4S,
    MAX_LAYERS,
    NOISE_SIZE,
    CloudOptics,
    DensityField,
    build_noise_texture,
    column_peaks,
    fbm_sigma,
    pack_layer_params,
    quantise,
    threshold_from_peaks,
    value_noise_volume,
)

LOGGER = logging.getLogger()

# ── Per-type layer spec (the only structured, repeating config) ─────────────────


@dataclass
class CloudLayer:
    """One cloud type's worth of sky in a field.

    Note what is NOT here: no cloud count, no altitude range, no per-cloud shape
    overrides.  A layer is a density field over a slab; the clouds are its
    features and the billboard count follows from its coverage.  Everything about
    shape lives in the :class:`DensityField`.

    cloud_type       which of :data:`cloud.PRESETS` to start from
    field            override the preset's field outright (None keeps it). This
                     is the shape knob: slab, feature size, threshold, profile.
    optics           override the preset's optics outright (None keeps it): the
                     sun march and the scattering. Unlike the field, these can
                     also be changed after the build — see
                     :meth:`CloudField.set_optics`.
    radius           override the preset's (min, max) billboard radius, metres
    volume_fraction  override the preset's target sphere-volume fraction, which
                     sets how many billboards get placed (not how opaque they
                     are — see cloud.volume_fraction)
    aspect           override the preset's billboard long:short axis ratio. The
                     stretch is area-preserving, so it changes neither the
                     billboard count nor the extinction.
    domain           side of THIS layer's scatter/recycle box; None → the
                     field's.  Snapped down to a whole number of the field's noise
                     periods where possible, which is what makes recycling
                     seamless.
    cell_size        side of one spatial sort/recycle cell, metres.  Smaller
                     cells sort more accurately and recycle in finer steps;
                     the cost is a per-cell centroid and sort rank.
    fade_in          (lo, hi) camera distances this layer fades in over, or None
                     to be present from the camera outward
    fade_out         (lo, hi) camera distances it fades out over, or None to be
                     taken to sky by the horizon haze instead. Used by
                     :func:`lod_shells` to hand adjacent shells a shared band.
    """

    cloud_type: CloudType
    field: Optional[DensityField] = None
    optics: Optional[CloudOptics] = None
    radius: Optional[tuple] = None
    volume_fraction: Optional[float] = None
    aspect: Optional[float] = None
    domain: Optional[float] = None
    cell_size: float = 1000.0
    fade_in: Optional[tuple] = None
    fade_out: Optional[tuple] = None


def lod_shells(
    cloud_type: CloudType,
    count: int = 6,
    domain: float = 32000.0,
    cell_size: float = 1000.0,
    crossfade: tuple = (0.62, 0.85),
    **overrides,
):
    """Nested camera-centred shells carrying one cloud type out to the horizon.

    A uniform field cannot reach the horizon: particle count grows with the
    domain's AREA, so the 32 km deck that costs ~52 k billboards would cost 830 k
    at 128 km.  Shells fix that with an observation about optical depth.  A ray's
    total depth through billboards of radius r at number density n goes as
    ``n * r^3`` (cross-section ``pi*r^2`` times a chord proportional to r), so:

        doubling the radius allows one EIGHTH the count per unit volume.

    Quadruple the area and eighth the density and each successive shell costs
    HALF its predecessor — 52 k, 26 k, 13 k, 6.5 k, … — and because that series
    converges, reach is very nearly free after the first few: 512 km costs 102 k
    billboards against 97 k for 128 km, about 5% more.  Screen-space billboard size
    stays roughly constant, which is the whole point: a shell is only ever seen at
    distances where its billboards subtend the same handful of pixels.

    Six shells by default because the deck has to reach much further than feels
    intuitive.  Clouds are elevated, so they peek over the horizon: the deck stays
    visible to about ``sqrt(2*R*eye) + sqrt(2*R*altitude)``, which is 286 km from
    1.25 km up and 498 km from 9 km.  Stopping short of that ends the deck BELOW
    the horizon line — bare ground above the farthest cloud, and the deck appearing
    to dip under the ground.

    Conserving optical depth needs nothing special here, because
    :attr:`~cloud.CloudSpec.volume_fraction` IS ``(4/3)*pi*n*<r^3>``: holding it
    constant across shells while scaling the radius makes the count fall as
    ``1/r^3`` on its own, and the extinction each shell derives from its own
    measured value then leaves a ray's total depth unchanged.  That is the thing
    that made LOD risky before it existed.

    Two knock-on scalings the shells do need:

      * ``cell_size`` doubles with the shell, or the outermost would have more
        sort cells than billboards.
      * ``max_optical_depth`` doubles with it too. A shell's billboards have twice
        the chord, so twice the per-fragment depth; leaving the cap alone would
        truncate the outer shells and render distant cloud too thin.

    :param cloud_type: the type to build shells of; all shells share ONE density
        field, which is what lets their crossfades agree
    :param count: number of shells; each doubles the previous one's extent
    :param domain: the innermost shell's domain width, metres
    :param cell_size: the innermost shell's sort-cell size, metres
    :param crossfade: (start, end) as fractions of a shell's half-width, where it
        hands over to the next. The band must complete inside the box, or the
        recycle boundary becomes visible.
    :param overrides: applied to every shell (e.g. a shared ``field``)
    :returns: a list of :class:`CloudLayer`, innermost first
    """
    preset = PRESETS[cloud_type]
    base_radius = overrides.pop("radius", None) or preset.radius
    base_optics = overrides.pop("optics", None) or preset.optics
    # Band k is where shell k hands over to shell k+1. Shell k fades OUT over
    # band k and shell k+1 fades IN over the same band, so their weights sum to
    # exactly 1 there (see cloud.frag).
    bands = [
        (
            crossfade[0] * domain * (2**k) * 0.5,
            crossfade[1] * domain * (2**k) * 0.5,
        )
        for k in range(count)
    ]
    shells = []
    for k in range(count):
        scale = 2.0**k
        shells.append(
            CloudLayer(
                cloud_type,
                radius=(base_radius[0] * scale, base_radius[1] * scale),
                optics=replace(
                    base_optics,
                    max_optical_depth=base_optics.max_optical_depth * scale,
                ),
                domain=domain * scale,
                cell_size=cell_size * scale,
                fade_in=bands[k - 1] if k > 0 else None,
                # The outermost shell is taken to sky by the horizon haze rather
                # than by a crossfade, since there is no next shell to hand to.
                fade_out=bands[k] if k < count - 1 else None,
                **overrides,
            )
        )
    return shells


def _default_layers():
    """:returns: a cumulus deck in LOD shells, reaching to the horizon.

    Cumulus alone, deliberately: it is the type the field's parameters are tuned
    against, and a second deck overhead makes it harder to judge. The others are
    in :data:`cloud.PRESETS`, one :class:`CloudLayer` away.
    """
    return lod_shells(CloudType.CUMULUS)


# ── Cull bins ──────────────────────────────────────────────────────────────────
# Panda's stock bins are background 10 < opaque 20 < transparent 30 < fixed 40.
# The clouds get their own bin between "opaque" and "transparent" so that every
# translucent effect in the game (all of which live at sort >= 30) is drawn AFTER
# the clouds and composites over them correctly.
_CLOUD_BIN = "cloud"
_CLOUD_BIN_SORT = 25


def _ensure_cloud_bins():
    """Register the cloud cull bin, once per process.

    Idempotent: safe to call from every :meth:`CloudField.build`, and safe
    headless (CullBinManager needs no graphics context).  Must run before any
    ``set_bin`` naming this bin — Panda silently ignores an unknown bin name.
    """
    manager = CullBinManager.get_global_ptr()
    if manager.find_bin(_CLOUD_BIN) == -1:
        # BT_fixed: we sort the geometry ourselves (see _restage), so the bin
        # must preserve the order we submit rather than re-sorting by distance.
        manager.add_bin(_CLOUD_BIN, CullBinManager.BT_fixed, _CLOUD_BIN_SORT)


# ── Shaders ────────────────────────────────────────────────────────────────────


def _settings_quality(game) -> CloudQuality:
    """The player's cloud quality, or HIGH if there is nothing to read it from.

    Read here rather than threaded in by the caller, matching how the ocean picks
    up its reflection scale (see scenes/ocean.py).  Deliberately forgiving: the
    demo scripts and the headless tests build a field from a stub game with no
    settings at all, and a missing setting must mean "the authored look", never a
    crash or a silent downgrade.

    :param game: the game object a field was built with
    :returns: the configured :class:`CloudQuality`
    """
    config = getattr(getattr(game, "app", None), "graphics_settings", None)
    name = (getattr(config, "config", None) or {}).get("clouds", {}).get("quality")
    try:
        return CloudQuality(name)
    except ValueError:
        if name is not None:
            LOGGER.warning(f"unknown cloud quality {name!r}; using high")
        return CloudQuality.HIGH


#: The cloud shader is shared by every field; load it once, lazily.
_CLOUD_SHADER = None

#: Coverage calibrations, keyed by (seed, unresolved field). The measurement costs
#: a grid evaluation of the field (~300 ms) but depends on nothing except the field
#: and the noise volume, and the volume is fully determined by the seed — so two
#: fields built from the same seed, in the same process, can share it. That covers
#: rebuilding a scene, two scenes using the same type, and the test suite, all of
#: which otherwise re-measure identical fields.
_COVERAGE_CACHE = {}


def _cloud_shader() -> Shader:
    """
    Load (once) and return the shared cloud colour shader.

    :return: The shared cloud :class:`Shader`.
    """
    global _CLOUD_SHADER
    if _CLOUD_SHADER is None:
        _CLOUD_SHADER = Shader.load(
            Shader.SL_GLSL,
            vertex=DATAFILES_PATH / "shaders/cloud.vert",
            fragment=DATAFILES_PATH / "shaders/cloud.frag",
        )
    return _CLOUD_SHADER


# ── Static vertex format; only the index buffer is reordered per frame ──────────

#: Floats per vertex, and per cell in the cellParams texture. The cell row is
#: [x, y, z, layerId] and must match CELL_PARAMS_STRIDE in cloud.vert.
_VERTEX_FLOATS = 11
_CELL_PARAMS_STRIDE = 4
#: Cells per ROW of the cellParams texture, matching CELLS_PER_ROW in cloud.vert.
#:
#: The texture is deliberately 2D rather than one long row. A single row needs
#: STRIDE * n_cells texels, which quietly walks into GL_MAX_TEXTURE_DIMENSION:
#: at 4 LOD shells that was 13 900 against a limit of 16 384 — 85% of the way
#: there — and adding two more shells took it to 21 024, at which point the
#: texture cannot be created, every cell reads zero, and the whole field collapses
#: to a single blob at the origin with every billboard claiming layer 0.
#: Wrapping into rows makes the width fixed and the limit irrelevant.
_CELLS_PER_ROW = 1024


def _vertex_format() -> GeomVertexFormat:
    """:returns: the interleaved per-vertex format — local position, quad corner,
    radius, sprite rect, and cell id (11 floats / vertex).

    There is deliberately NO colour column: colour is a function of world
    position, so carrying it per particle is both wasted bandwidth and a source
    of quad-shaped seams. Nor is there a layer column — the cloud type is a
    property of a whole cell, so it rides in the cellParams row the vertex shader
    is already fetching. The sprite rect stays, because a sprite is a per-quad
    THICKNESS profile rather than a silhouette, and that is what lets one
    billboard stand in for a lumpy puff instead of a smooth ball.
    """
    fmt = GeomVertexArrayFormat()
    fmt.add_column(
        InternalName.get_vertex(), 3, GeomEnums.NT_float32, GeomEnums.C_point
    )
    fmt.add_column(
        InternalName.get_texcoord(), 2, GeomEnums.NT_float32, GeomEnums.C_texcoord
    )
    fmt.add_column(
        InternalName.make("i_radius"), 1, GeomEnums.NT_float32, GeomEnums.C_other
    )
    fmt.add_column(
        InternalName.make("i_uv_st"), 4, GeomEnums.NT_float32, GeomEnums.C_texcoord
    )
    fmt.add_column(
        InternalName.make("i_cellId"), 1, GeomEnums.NT_float32, GeomEnums.C_other
    )
    combined = GeomVertexFormat()
    combined.add_array(fmt)
    return GeomVertexFormat.register_format(combined)


# Quad corners (CCW): BL, BR, TR, TL — reused as the [-1,+1] offset and UV basis.
_CORNERS = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float32)
# Two triangles per quad, as offsets into a particle's 4-vertex block.
_QUAD_TRIS = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
# Particles per chunk when building/uploading the static vertex buffer, so its
# NumPy work is spread across several frames instead of one.
_VBUF_BLOCK = 20000


class CloudField:
    """A drawable, wind-driven, depth-sorted field of mixed-type billboard clouds.

    All field settings live here (the single configuration surface).  Construct
    with a parent NodePath, a loader (for the atlas), and a list of
    :class:`CloudLayer`; then call :meth:`update` once per frame.
    """

    def __init__(
        self,
        parent,
        game,
        layers=None,
        *,
        domain=32000.0,
        wind=(20.0, 0.0, 0.0),
        sun_direction=(0.2, 1.0, 0.1),
        sun_color=(1.0, 0.95, 0.85),
        sky_color=(0.45, 0.6, 0.85),
        haze_color=None,
        sun_brightness=2.8,
        sky_strength=0.35,
        sky_occlusion=0.55,
        exposure=1.15,
        horizon_distance=400000.0,
        planet_radius=6371000.0,
        near_fade_radii=2.5,
        quality=None,
        resort_frames=8,
        seed=7,
        defer_build=False,
    ):
        """Build the field's geometry and shading from a list of layers.

        Configuration is split three ways, by what a change costs:

          * a layer's :class:`~space_flight.scenes.cloud.noise.DensityField` is
            its SHAPE, and drives placement — changing it needs a rebuild;
          * a layer's :class:`~space_flight.scenes.cloud.noise.CloudOptics` is its
            sun march and scattering, per cloud TYPE because all of it scales with
            the type's own geometry — changeable live via :meth:`set_optics`;
          * everything HERE is scene-wide: the sun, the camera, the domain. Things
            every type genuinely shares.

        :param parent: NodePath the cloud geometry is reparented under
        :param game: the game object (used to load the sprite atlas)
        :param layers: list of :class:`CloudLayer` (defaults to one cumulus deck
            — see :func:`_default_layers`)
        :param domain: side of the camera-centred box clouds scatter/recycle
            within, for any layer that does not set its own. Snapped DOWN to a
            whole number of the layer field's noise period, which is what makes
            recycling seamless; the default is exactly one period at the cumulus
            preset's feature size.
        :param wind: metres/second the clouds drift each frame
        :param sun_direction: vector FROM the scene TOWARD the sun. Live — change
            it any time with :meth:`set_sun`; nothing is baked.
        :param sun_color: RGB of direct sunlight
        :param sky_color: RGB of the ambient sky fill, used as the reference's
            skylight term
        :param haze_color: RGB distant cloud fades toward (defaults to sky_color).
            Should match what the rest of the scene puts at the horizon — the
            ocean takes the same value — or the two will not meet there.
        :param sun_brightness: multiplier on the direct term (the reference's
            sunBrightness). NOT independent of ``exposure``: the soft-knee
            tonemap saturates above about 3, so a bright pair flattens the lit
            and shadowed sides onto the same white — which is exactly how the
            clouds came to look washed out at the reference's own value of 5.
            The defaults are solved for a roughly 0.95 sunlit top against a 0.35
            shadowed base, which is the contrast a real cumulus deck shows.
        :param sky_strength: weight of the ambient sky term. This is what lifts
            the shadowed side of a cloud off black; the phase function's
            forward lobe peaks around 16x, and the ambient plus the tonemap's
            knee are what bring that to something believable.
        :param sky_occlusion: fraction of the sky term that reaches the underside
            of a cloud deck (1 disables the gradient). Skylight comes from above,
            so without this the shadowed base reads as flat fill; with it, a
            cumulus deck gets the flat grey undersides it should have.
        :param exposure: scales cloud radiance before a soft-knee roll-off. This
            exists because the reference tonemaps the WHOLE frame and a
            translucent element inside an existing pipeline cannot; it is the
            handle for overall cloud brightness.
        :param horizon_distance: metres over which distant cloud tends completely
            to ``haze_color``. Aerial perspective, not a fade to transparent — a
            hazed cloud still hides what is behind it. It must complete INSIDE the
            outermost shell's half-width, since a fully hazed cloud is
            indistinguishable from sky and that is what hides the shell's box edge.

            Note how far this has to reach. Because clouds are elevated they peek
            over the horizon, so the deck is visible out to roughly
            ``sqrt(2*R*eye) + sqrt(2*R*altitude)`` — 286 km from 1.25 km up and
            498 km from 9 km. Cutting the haze in much shorter than that ends the
            deck BELOW the horizon line, which reads as the clouds dipping under
            the ground.
        :param planet_radius: metres; the cloud deck droops by
            ``distance^2 / (2 * radius)`` so it sinks behind the horizon instead
            of floating above it. Ignorable for a small field — 80 m at 32 km —
            but not for one reaching the horizon, where the drop grows to 1.3 km
            at 128 km, comparable to the whole slab thickness. Pass 0 (or
            ``float("inf")``) for a flat world.
        :param near_fade_radii: fade a billboard out within this many of its own
            radii of the camera (0 disables). Without it, a billboard the camera
            is inside covers much of the screen as one smeared sprite, and clips
            against the near plane as a hard-edged quad.
        :param quality: a :class:`~space_flight.scenes.cloud.cloud.CloudQuality`
            scaling every layer's billboard budget and sun march (see
            :func:`~space_flight.scenes.cloud.cloud.at_quality`). None reads the
            player's graphics settings, falling back to HIGH — which is what the
            presets ship, so a caller with no settings gets the authored look.

            It scales whatever each layer asked for rather than replacing it, so
            it composes with the per-shell radii :func:`lod_shells` sets and with
            any explicit layer override.
        :param resort_frames: frames to spread one full re-sort over (de-spike)
        :param seed: RNG seed for the noise volume and placement
        :param defer_build: if True, do not build in the constructor; the caller
            must drive :meth:`build` (a generator) instead, one step per frame.
        """
        self._parent = parent
        self._game = game
        self._layers = layers if layers is not None else _default_layers()
        if len(self._layers) > MAX_LAYERS:
            raise ValueError(
                f"at most {MAX_LAYERS} cloud layers (the layerParams uniform "
                f"array is sized for it); got {len(self._layers)}"
            )
        self._domain = domain
        self._wind = np.asarray(wind, dtype=np.float32)
        self._sun_direction = sun_direction
        self._sun_color_arg = sun_color
        self._sky_color_arg = sky_color
        self._haze_color_arg = haze_color
        self._sun_brightness = sun_brightness
        self._sky_strength = sky_strength
        self._sky_occlusion = sky_occlusion
        self._exposure = exposure
        self._horizon_distance = horizon_distance
        # Stored as the shader's 1/(2R), so a zero or infinite radius means flat.
        self._curvature = (
            0.0 if not planet_radius else 1.0 / (2.0 * float(planet_radius))
        )
        self._near_fade_radii = near_fade_radii
        self._quality = quality if quality is not None else _settings_quality(game)
        self._resort_frames = max(1, int(resort_frames))
        self._seed = seed

        # Build immediately unless the caller wants to drive build() per frame.
        if not defer_build:
            for _ in self.build():
                pass

    def build(self):
        """
        Generator that builds the field, yielding between chunks of work so a
        loader can spread the cost across frames rather than freezing on one
        construction.

        Placement dominates the build cost: rejection-sampling a layer against its
        own density field is a few million field evaluations. Each yield ends a
        chunk.
        """
        # The cloud bins must exist before the set_bin below names them.
        _ensure_cloud_bins()

        parent = self._parent
        seed = self._seed

        # The sprites are a per-quad thickness profile, not a silhouette.
        atlas_tex, rects = load_cloud_atlas(self._game)
        sprite_coverage = atlas_mean_alpha(rects)

        # ONE noise volume for every layer; the layers' fields decorrelate by a
        # constant offset in noise space rather than by owning separate textures
        # (see noise.field_offset). Quantised to the 8 bits the GPU copy stores,
        # so the CPU placement and the GPU drawing agree bit for bit -- if they
        # drifted, billboards would land in clear air.
        volume = quantise(value_noise_volume(seed=seed))
        # The sun march's cheap 2-octave fbm is calibrated against this volume's
        # own mean, so it agrees with the field it stands in for.
        octave_mean = float(volume.mean())
        yield "cloud_noise"

        # ── Place each layer against its own field ─────────────────────────────
        locals_, radii_, uv_, centres_, layer_ids_, starts_, wraps_ = (
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        )
        self._layer_params = np.zeros((MAX_LAYERS, LAYER_VEC4S, 4), dtype=np.float32)
        # _layer_specs is the single source of truth for what each layer IS (its
        # field and optics); set_optics re-packs from it. _layer_report holds only
        # what the BUILD measured, so the two cannot drift apart.
        self._layer_specs = []
        self._layer_pack_args = []
        self._layer_report = []
        # Coverage calibration, keyed by the UNRESOLVED field. Holds the sorted
        # column peaks and the fbm's spread, which is everything set_coverage
        # needs to re-derive a threshold without re-measuring the field.
        self._coverage_cal = {}
        particle_base = 0
        for layer_index, layer in enumerate(self._layers):
            overrides = {
                name: value
                for name, value in (
                    ("field", layer.field),
                    ("optics", layer.optics),
                    ("radius", layer.radius),
                    ("volume_fraction", layer.volume_fraction),
                    ("aspect", layer.aspect),
                )
                if value is not None
            }
            spec = replace(PRESETS[layer.cloud_type], **overrides)
            # Quality scales what the layer asked for, so it composes with the
            # per-shell radii lod_shells sets and with any explicit override.
            # Applied before placement, since the billboard budget is what it
            # mostly changes; it does NOT touch the field, so the coverage
            # calibration below is shared across quality levels.
            spec = at_quality(spec, self._quality)
            # Measure this field's coverage calibration, which costs a grid
            # evaluation (~300 ms), as its own build step. Memoised on the field:
            # LOD shells of one type share a field, so a deck of six shells pays
            # this once -- and they MUST get the same threshold, or consecutive
            # shells would disagree about where cloud is across their crossfade.
            if spec.field not in self._coverage_cal:
                cached = _COVERAGE_CACHE.get((seed, spec.field))
                if cached is None:
                    cached = (
                        column_peaks(volume, spec.field),
                        fbm_sigma(volume, spec.field),
                    )
                    _COVERAGE_CACHE[(seed, spec.field)] = cached
                    yield f"cloud_coverage[{layer.cloud_type.value}]"
                self._coverage_cal[spec.field] = cached
            # Resolve the derived threshold BEFORE anything else touches the
            # field, so placement and packing see the same window.
            spec = replace(spec, field=self._resolved_field(volume, spec.field))

            requested = float(layer.domain if layer.domain else self._domain)
            width, seamless = snap_to_noise_period(spec.field, requested)
            # Placed a batch at a time, yielding between batches, so a full-size
            # deck's few hundred thousand field evaluations don't land in one
            # frame.
            placed = None
            for step in sample_field_particles_iter(
                spec,
                volume,
                domain=width,
                cell_size=layer.cell_size,
                atlas_rects=rects,
                seed=seed + 1000 * layer_index,
            ):
                if step is None:
                    yield f"cloud_place[{layer.cloud_type.value}]"
                else:
                    placed = step

            # Extinction is derived, not tuned: dividing the field's density by
            # the placement's own sphere-volume fraction makes a ray through a
            # cloud accumulate that density per metre whatever radii and counts
            # were used, and by the sprites' mean alpha because that is the
            # fraction of each billboard's disc that actually carries thickness.
            # Leaving either out makes every cloud proportionally see-through.
            extinction = spec.field.density / max(placed["phi"] * sprite_coverage, 1e-6)
            self._layer_specs.append(spec)
            self._layer_pack_args.append(
                dict(
                    extinction=extinction,
                    wrap_radius=0.5 * width,
                    # A seamless box needs no fade at all: the cell lands where
                    # the field is identical, so there is nothing to hide.
                    wrap_fade_band=0.0 if seamless else 0.12 * width,
                    octave_mean=octave_mean,
                    aspect=spec.aspect,
                    fade_in=layer.fade_in,
                    fade_out=layer.fade_out,
                )
            )
            self._layer_params[layer_index] = pack_layer_params(
                spec.field, optics=spec.optics, **self._layer_pack_args[layer_index]
            )

            locals_.append(placed["local"])
            radii_.append(placed["radii"])
            uv_.append(placed["uv"])
            centres_.append(placed["cell_centres"])
            n_cells = len(placed["cell_centres"])
            layer_ids_.append(np.full(n_cells, layer_index, dtype=np.float32))
            wraps_.append(np.full(n_cells, 0.5 * width, dtype=np.float32))
            # Concatenating layers shifts every cell's particle range.
            starts_.append(placed["cell_start"][:-1] + particle_base)
            particle_base += len(placed["local"])
            # What the build MEASURED. Deliberately not the field or the optics:
            # those live in _layer_specs, and a second copy here would go stale
            # the first time set_optics changed one.
            self._layer_report.append(
                dict(
                    type=layer.cloud_type,
                    particles=len(placed["local"]),
                    cells=n_cells,
                    domain=width,
                    seamless=seamless,
                    phi=placed["phi"],
                    extinction=extinction,
                )
            )

        # ── Concatenate the layers into one ragged particle array ──────────────
        self._local = np.ascontiguousarray(np.concatenate(locals_), np.float32)
        radii = np.concatenate(radii_)
        uv_rects = np.concatenate(uv_)
        self._cell_centres = np.ascontiguousarray(np.concatenate(centres_), np.float32)
        self._cell_layer = np.concatenate(layer_ids_)
        self._cell_wrap = np.concatenate(wraps_)
        # cell_start has one entry per cell plus a final total, so a cell's
        # particles are exactly [cell_start[c], cell_start[c+1]).
        self._cell_start = np.concatenate(
            [np.concatenate(starts_), [particle_base]]
        ).astype(np.int64)
        self._cell_pop = np.diff(self._cell_start)
        n_particles = int(particle_base)
        self._n = n_particles
        self._n_cells = len(self._cell_centres)
        # Wind advection accumulates in noise coordinates: the field translates
        # WITH the billboards, so a puff keeps its shape as it drifts instead of
        # sliding through the density field and dissolving. One offset serves
        # every layer, because each layer scales it by its own noise_scale.
        # Carried in METRES and scaled per layer in the shader, because the
        # noise-space rate differs per layer: that way layers with different
        # feature sizes all stay locked to their own field.
        self._noise_offset = np.zeros(3, dtype=np.float64)

        # Incremental round-robin restage state.
        self._stage = np.empty(n_particles * 6, dtype=np.uint32)  # staging indices
        self._draw_order = None
        self._buf_offset = None
        self._cyc_cursor = 0
        yield "cloud_assemble"

        # ── Static vertex data: 4 verts per particle, 11 floats each ──────────
        # Built and uploaded in particle-blocks so the NumPy buffer construction
        # + copy is spread across frames instead of one big spike.
        vdata = GeomVertexData("cloud_field", _vertex_format(), GeomEnums.UH_static)
        vdata.set_num_rows(4 * n_particles)
        dst = memoryview(vdata.modify_array(0)).cast("B")
        # Per-particle cell id, from the ragged offsets: cell c owns the
        # contiguous run [cell_start[c], cell_start[c+1]).
        cell_of = np.repeat(np.arange(self._n_cells, dtype=np.float32), self._cell_pop)
        row_bytes = _VERTEX_FLOATS * 4
        for b0 in range(0, n_particles, _VBUF_BLOCK):
            b1 = min(b0 + _VBUF_BLOCK, n_particles)
            m = b1 - b0
            block = np.empty((4 * m, _VERTEX_FLOATS), dtype=np.float32)
            block[:, 0:3] = np.repeat(self._local[b0:b1], 4, axis=0)
            block[:, 3:5] = np.tile(_CORNERS, (m, 1))
            block[:, 5] = np.repeat(radii[b0:b1], 4)
            block[:, 6:10] = np.repeat(uv_rects[b0:b1], 4, axis=0)
            block[:, 10] = np.repeat(cell_of[b0:b1], 4)
            dst[b0 * 4 * row_bytes : b1 * 4 * row_bytes] = memoryview(block).cast("B")
            yield "cloud_vertexbuf"

        # ── Index buffer: reordered every frame (uint32 for >16k verts) ──────
        self._tris = GeomTriangles(GeomEnums.UH_dynamic)
        self._tris.set_index_type(GeomEnums.NT_uint32)
        self._tris.add_next_vertices(6 * n_particles)  # allocate; overwritten below
        # Per-particle base triangle indices: particle p → its 4 verts at 4p..4p+3.
        self._tri_base = (
            np.arange(n_particles, dtype=np.uint32)[:, None] * 4
        ) + _QUAD_TRIS
        # Seed a valid (natural) order BEFORE add_primitive (it validates indices).
        self._stage[:] = self._tri_base.reshape(-1)
        memoryview(self._tris.modify_vertices()).cast("B")[
            : self._stage.nbytes
        ] = self._stage.tobytes()
        yield "cloud_indexbuf"

        geom = Geom(vdata)
        geom.add_primitive(self._tris)

        gnode = GeomNode("cloud_field")
        gnode.add_geom(geom)
        # Billboards extend past their centres; skip culling rather than inflate
        # bounds.
        gnode.set_bounds(OmniBoundingVolume())
        gnode.set_final(True)

        self.node = parent.attach_new_node(gnode)
        self.node.set_texture(atlas_tex)
        self.node.set_transparency(TransparencyAttrib.M_none)  # blend set explicitly
        self.node.set_shader(_cloud_shader())
        self.node.set_depth_test(True)  # occluded by opaque scene geometry
        self.node.set_depth_write(False)  # translucent: no self-occlusion
        self.node.set_bin(_CLOUD_BIN, 0)
        self.node.set_attrib(
            ColorBlendAttrib.make(
                ColorBlendAttrib.M_add,
                ColorBlendAttrib.O_one,
                ColorBlendAttrib.O_one_minus_incoming_alpha,
            )
        )

        # Per-cell parameter texture (R32F: centre xyz then the layer id, wrapped
        # into rows of _CELLS_PER_ROW cells). Single-channel float → no BGRA
        # channel-order ambiguity. Only the centres change per frame.
        self._cell_rows = -(-self._n_cells // _CELLS_PER_ROW)  # ceil
        self._cell_tex = Texture("cloud_cells")
        self._cell_tex.setup_2d_texture(
            _CELL_PARAMS_STRIDE * _CELLS_PER_ROW,
            self._cell_rows,
            Texture.T_float,
            Texture.F_r32,
        )
        self._cell_tex.set_magfilter(SamplerState.FT_nearest)
        self._cell_tex.set_minfilter(SamplerState.FT_nearest)
        self._upload_cells()

        self.node.set_shader_input("camPos", Vec3(0, 0, 0))
        self.node.set_shader_input("viewPos", Vec3(0, 0, 0))
        self.node.set_shader_input("cellParams", self._cell_tex)

        # Per-type field and optics, as a uniform array indexed by the layer id.
        self._upload_layer_params()

        # Scene-wide lighting: all live, nothing baked, so set_sun can move the
        # sun at will.
        self.node.set_shader_input("sunBrightness", float(self._sun_brightness))
        self.node.set_shader_input("skyStrength", float(self._sky_strength))
        self.node.set_shader_input("skyOcclusion", float(self._sky_occlusion))
        self.node.set_shader_input("exposure", float(self._exposure))
        self.node.set_shader_input(
            "horizonFade", 1.0 / max(float(self._horizon_distance), 1.0)
        )
        self.node.set_shader_input("earthCurvature", float(self._curvature))
        self.set_sun(
            self._sun_direction,
            self._sun_color_arg,
            self._sky_color_arg,
            self._haze_color_arg,
        )

        # The density field: one noise octave every layer taps four times.
        self.node.set_shader_input("cloudNoise", build_noise_texture(seed=seed))
        self.node.set_shader_input("noiseSize", float(NOISE_SIZE))
        self.node.set_shader_input("noiseOffset", Vec3(0, 0, 0))
        self.node.set_shader_input("nearFadeRadii", float(self._near_fade_radii))

    # ── Lighting ──────────────────────────────────────────────────────────────

    def _upload_layer_params(self):
        """Push the per-type field and optics into the layerParams uniform array."""
        pta = PTA_LVecBase4f()
        for row in self._layer_params.reshape(-1, 4):
            pta.push_back(LVecBase4f(*(float(v) for v in row)))
        self.node.set_shader_input("layerParams", pta)

    def _resolved_field(self, volume, spec):
        """Resolve one field's derived threshold, measuring it at most once.

        :param volume: the quantised noise volume the field is drawn against
        :param spec: the unresolved :class:`DensityField`
        :returns: a copy with ``threshold`` filled in
        """
        if spec not in self._coverage_cal:
            self._coverage_cal[spec] = (
                column_peaks(volume, spec),
                fbm_sigma(volume, spec),
            )
        peaks, sigma = self._coverage_cal[spec]
        return replace(
            spec,
            threshold=threshold_from_peaks(
                peaks, spec.coverage, spec.edge_softness, sigma
            ),
        )

    def set_coverage(self, layer=None, coverage=None, edge_softness=None):
        """Change how much of the sky one cloud type covers, live.

        Coverage is zenith-projected and PER TYPE, against that type's own slab:
        a column counts as covered if there is cloud at any height in it.  Two
        types at 0.3 each therefore hide 1 - 0.7*0.7 = 0.51 of the sky between
        them, not 0.6.

        Live because the expensive half of the calibration is cached: the sorted
        column peaks measured at build time are the exact inverse of the coverage
        function, so a new threshold is an index into them rather than a fresh
        measurement of the field.

        The catch, and it is a real one: this re-packs the uniforms but does NOT
        re-place billboards, and placement is rejection-sampled against the
        threshold the field was BUILT at.

          * Lowering coverage is exact. The extra billboards simply fall below the
            higher threshold and discard, and because extinction is per-billboard
            the remaining cloud keeps the right optical depth. It costs only the
            fill rate of the billboards now in clear air.
          * Raising it past the built value is NOT. There are no billboards
            covering the cloud the field now wants, so it shows up as cloud that
            is missing rather than as cloud that is thin, and the deck grows holes.

        So this is a tuning and preview knob. To commit a higher coverage, put it
        in the layer's field and rebuild.

        :param layer: index of the layer to change, or None for every layer
        :param coverage: the new zenith-projected cloud fraction, or None to keep
        :param edge_softness: the new window width in sigma, or None to keep
        :returns: the list of resulting :class:`DensityField`, in layer order
        """
        indices = range(len(self._layer_specs)) if layer is None else [layer]
        for index in indices:
            spec = self._layer_specs[index]
            field = spec.field
            # The cache is keyed by the UNRESOLVED field, so strip the derived
            # threshold back off before looking it up or changing the knobs.
            key = replace(field, threshold=None)
            changed = replace(
                key,
                coverage=field.coverage if coverage is None else float(coverage),
                edge_softness=(
                    field.edge_softness
                    if edge_softness is None
                    else float(edge_softness)
                ),
            )
            if key not in self._coverage_cal:
                # Only reachable if the layer was never resolved through build.
                raise RuntimeError("no coverage calibration for this layer")
            peaks, sigma = self._coverage_cal[key]
            self._coverage_cal[changed] = (peaks, sigma)
            spec = replace(
                spec,
                field=replace(
                    changed,
                    threshold=threshold_from_peaks(
                        peaks, changed.coverage, changed.edge_softness, sigma
                    ),
                ),
            )
            self._layer_specs[index] = spec
            self._layer_params[index] = pack_layer_params(
                spec.field, optics=spec.optics, **self._layer_pack_args[index]
            )
        self._upload_layer_params()
        return [spec.field for spec in self._layer_specs]

    def set_optics(self, layer=None, **changes):
        """Change how light travels through one cloud type, or all of them, live.

        Only :class:`~space_flight.scenes.cloud.noise.CloudOptics` fields can be
        set here, and that restriction is the point: optics are read per fragment
        and affect nothing but shading, so they need no rebuild.  Shape lives in
        the :class:`~space_flight.scenes.cloud.noise.DensityField` and drives
        placement, so changing it would put the billboards and the drawn cloud out
        of step — pass a new field to :class:`CloudLayer` and rebuild instead.

        :param layer: index of the layer to change, or None for every layer
        :param changes: CloudOptics field names to override
        :returns: the list of resulting :class:`CloudOptics`, in layer order
        :raises AttributeError: if a name is not a CloudOptics field — better than
            silently ignoring a typo in a tuning session
        """
        unknown = set(changes) - {f.name for f in fields(CloudOptics)}
        if unknown:
            raise AttributeError(
                f"not CloudOptics parameters: {sorted(unknown)}. Shape parameters "
                "live in DensityField and need a rebuild."
            )
        indices = range(len(self._layer_specs)) if layer is None else [layer]
        for index in indices:
            spec = self._layer_specs[index]
            spec = replace(spec, optics=replace(spec.optics, **changes))
            self._layer_specs[index] = spec
            self._layer_params[index] = pack_layer_params(
                spec.field, optics=spec.optics, **self._layer_pack_args[index]
            )
        self._upload_layer_params()
        return [spec.optics for spec in self._layer_specs]

    def set_sun(self, direction, sun_color=None, sky_color=None, haze_color=None):
        """Move the sun and/or restate its colours. Takes effect immediately.

        Nothing about the lighting is baked — the fragment shader marches toward
        the sun through the shared density field every frame — so this is a
        handful of uniform writes, with no geometry or placement rebuild.

        :param direction: vector FROM the scene TOWARD the sun (need not be unit)
        :param sun_color: RGB of direct sunlight, or None to leave it unchanged
        :param sky_color: RGB of the ambient sky fill, or None to leave unchanged
        :param haze_color: RGB distant cloud tends toward. Should match whatever
            the scene puts at the horizon, or the deck will not blend into it.
            Setting sky_color alone also sets this, which is the usual case.
        """
        sun_dir = np.asarray(direction, dtype=float)[:3]
        norm = np.linalg.norm(sun_dir)
        if norm < 1e-9:
            raise ValueError("sun direction must be a non-zero vector")
        self._sun_direction = tuple(float(v) for v in sun_dir)
        self.node.set_shader_input("sunDir", Vec3(*(sun_dir / norm)))
        if sun_color is not None:
            self._sun_color_arg = sun_color
            self.node.set_shader_input(
                "sunColor", Vec3(*np.asarray(sun_color, dtype=float)[:3])
            )
        if sky_color is not None:
            self._sky_color_arg = sky_color
            self.node.set_shader_input(
                "skyColor", Vec3(*np.asarray(sky_color, dtype=float)[:3])
            )
            # The sky is the sensible default for what the horizon looks like; a
            # scene with its own horizon tint overrides it below.
            if haze_color is None:
                haze_color = sky_color
        if haze_color is not None:
            self._haze_color_arg = haze_color
            self.node.set_shader_input(
                "hazeColor", Vec3(*np.asarray(haze_color, dtype=float)[:3])
            )

    # ── Per-frame ─────────────────────────────────────────────────────────────

    def update(self, cam_pos: Vec3, dt: float = 0.0):
        """Advance the field one frame: re-face billboards, drift + recycle the
        cells, and continue the incremental draw-order re-sort.

        :param cam_pos: current camera world position
        :param dt: seconds since the last frame (drives wind drift)
        """
        # Cheap, every frame: billboards re-face the camera (built in the VS).
        self.node.set_shader_input("camPos", cam_pos)
        self.node.set_shader_input("viewPos", cam_pos)
        cam_xyz = np.array([cam_pos.x, cam_pos.y, cam_pos.z], dtype=np.float32)

        if dt:
            self._cell_centres += self._wind * dt  # wind drift
            # Advect the density field by the SAME wind, so a billboard stays at
            # a fixed location in the field and keeps its shape as it drifts.
            # Derived from self._wind rather than taken as its own parameter: if
            # the two ever disagreed, puffs would slide through the field and
            # continuously dissolve. Carried in METRES and scaled per layer in
            # the shader, so layers with different feature sizes each stay
            # locked to their own field.
            self._noise_offset -= self._wind * dt
            self.node.set_shader_input("noiseOffset", Vec3(*self._noise_offset))
        # Toroidal recycle: wrap each cell back into the camera-centred box on
        # X/Y by subtracting the nearest whole box-width. The box is PER LAYER,
        # and where its width is a whole number of noise periods the wrapped cell
        # lands in identical field -- so the teleport is invisible and needs no
        # fade. Unconditional: every field has a box (a zero-width one would have
        # no room to place a billboard in), so there is no static case to guard.
        box_width = 2.0 * self._cell_wrap[:, None]
        rel = self._cell_centres[:, :2] - cam_xyz[:2]
        self._cell_centres[:, :2] = (
            cam_xyz[:2] + rel - box_width * np.round(rel / box_width)
        )
        self._upload_cells()

        self._restage(cam_xyz)

    def remove(self):
        """Detach the cloud geometry from the scene."""
        self.node.removeNode()

    def _upload_cells(self):
        """Push the per-cell parameters into the GPU parameter texture.

        Interleaved as [x, y, z, layerId] per cell, wrapped into rows of
        _CELLS_PER_ROW cells (see that constant for why it is not one long row).
        The tail of the last row is padding no cell id ever addresses. Only the
        centres actually change frame to frame, but the whole image is one small
        contiguous upload either way.
        """
        params = np.zeros(
            (self._cell_rows, _CELLS_PER_ROW, _CELL_PARAMS_STRIDE), dtype=np.float32
        )
        flat = params.reshape(-1, _CELL_PARAMS_STRIDE)
        flat[: self._n_cells, 0:3] = self._cell_centres
        flat[: self._n_cells, 3] = self._cell_layer
        self._cell_tex.set_ram_image(
            np.ascontiguousarray(params.reshape(-1), np.float32).tobytes()
        )

    def _restage(self, cam_xyz):
        """Re-sort and re-upload one round-robin slice of the index buffer.

        Each frame handles n_cells / resort_frames cells; a fresh cell draw-order
        is snapshotted at the start of each cycle, and the index buffer is
        uploaded once per completed cycle.  This spreads both the sort and the
        index gather, so there is no per-frame spike, and the GPU only ever sees a
        fully consistent buffer.

        Cell populations vary, so a cell's slot in the index buffer depends on
        which cells outrank it — hence the cumulative-population table recomputed
        once per cycle.  Within a chunk, the whole ragged gather and sort is one
        lexsort keyed on (cell rank, distance), with no Python loop over cells.

        :param cam_xyz: current camera world position as a 3-float array
        """
        n_cells = self._n_cells
        cells_per_frame = -(-n_cells // self._resort_frames)  # ceil division
        if self._draw_order is None or self._cyc_cursor >= n_cells:
            # New cycle: snapshot the cell draw order, far → near (cheap K-argsort).
            centre_rel = self._cell_centres - cam_xyz
            self._draw_order = np.argsort(
                -np.einsum("ij,ij->i", centre_rel, centre_rel)
            )
            # Where each draw rank's particles land in the index buffer. Ranks are
            # laid out in order, each taking as many slots as its cell has
            # particles, so the whole buffer is filled exactly once.
            self._buf_offset = np.concatenate(
                [[0], np.cumsum(self._cell_pop[self._draw_order])]
            ).astype(np.int64)
            self._cyc_cursor = 0

        start = self._cyc_cursor
        end = min(start + cells_per_frame, n_cells)
        cells = self._draw_order[start:end]  # cells at these draw ranks
        counts = self._cell_pop[cells]
        total = int(counts.sum())
        if total:
            # Ragged gather: turn (start, count) per cell into one flat index array.
            group_start = np.cumsum(counts) - counts
            particle_ids = np.repeat(self._cell_start[cells] - group_start, counts)
            particle_ids = particle_ids + np.arange(total)
            group = np.repeat(np.arange(len(cells)), counts)

            world = (
                self._cell_centres[np.repeat(cells, counts)] + self._local[particle_ids]
            )
            offset = world - cam_xyz
            dist_sq = np.einsum("ij,ij->i", offset, offset)
            # Cells stay in draw-rank order; within a cell, far → near.
            order = np.lexsort((-dist_sq, group))
            lo, hi = self._buf_offset[start], self._buf_offset[end]
            self._stage[lo * 6 : hi * 6] = self._tri_base[particle_ids[order]].reshape(
                -1
            )
        self._cyc_cursor = end

        if end >= n_cells:  # cycle complete → ONE atomic upload
            memoryview(self._tris.modify_vertices()).cast("B")[
                : self._stage.nbytes
            ] = self._stage.tobytes()


# ── Game-facing wrapper ─────────────────────────────────────────────────────────


class Clouds:
    """Drops a :class:`CloudField` into a level following the scene convention:
    construct with the game, register a per-frame update in
    game.method_lists, expose clean.  All CloudField settings (layers,
    domain, wind, sun, lighting, …) pass straight through as keyword arguments.

    Usage::

        from space_flight.scenes.cloud.field import Clouds, CloudLayer
        self.clouds = Clouds(game, sun_direction=Vec3(0.2, 1.0, 0.1))
    """

    def __init__(self, game, layers=None, *, defer_build=False, **field_kwargs):
        self.game = game
        self.id = uuid.uuid4()
        self.field = CloudField(
            parent=game.root_node,
            game=game,
            layers=layers,
            defer_build=defer_build,
            **field_kwargs,
        )
        # When building synchronously the field is ready now; register the
        # per-frame update. Deferred builds register it at the end of build().
        if not defer_build:
            game.method_lists[self.id] = [self.update]

    def build(self):
        """
        Drive the deferred field build a chunk per frame, then register the
        per-frame update once the field is ready. Use with defer_build=True::

            self.clouds = Clouds(game, defer_build=True, ...)
            yield from self.clouds.build()
        """
        yield from self.field.build()
        self.game.method_lists[self.id] = [self.update]

    def update(self):
        """Per-frame: drive wind/recycle/sort against the current camera."""
        cam_pos = self.game.app.camera.get_pos(self.game.app.render)
        dt = self.game.game_time.get_time_step()
        self.field.update(cam_pos, dt)

    def clean(self):
        """Remove the per-frame update and detach the cloud geometry."""
        if self.game.method_lists:
            self.game.method_lists.pop(self.id, None)
        self.field.remove()
        self.game = None
