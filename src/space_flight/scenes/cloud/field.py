"""
field.py — A drawable field of billboard clouds: geometry, shaders, sorting,
wind/recycling, plus the game-facing :class:`Clouds` wrapper.

Clouds are ordinary geometry that depth-tests against the scene, so ships and
terrain occlude them with no depth plumbing. Every particle of every layer lives in
ONE Geom whose vertex data never changes after the build; the camera-facing quad is
built in the vertex shader, cell centres move in a small per-cell texture (wind +
toroidal recycling), and only the INDEX buffer is re-sorted, back to front for
premultiplied-over blending, spread round-robin over ``resort_frames`` frames.

The clouds draw in their own "cloud" bin, between "opaque" and "transparent", with
no depth write: every translucent effect composites over them, but an effect behind
a dense cloud is not hidden by it. Design notes: docs/source/scenes.md.
"""

from __future__ import annotations

import functools
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

from space_flight import DATAFILES_PATH, PLANET_RADIUS_M
from space_flight.scenes.cloud.cloud import (
    PRESETS,
    CloudQuality,
    CloudType,
    at_quality,
    atlas_mean_alpha,
    load_cloud_atlas,
    sample_field_particles,
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
    value_noise_volume,
    with_threshold,
)

LOGGER = logging.getLogger()


@dataclass
class CloudLayer:
    """One cloud type's worth of sky in a field.

    No cloud count and no altitude range: the billboard count follows from the
    field's coverage, and the altitude IS the field's slab.

    cloud_type       which of :data:`cloud.PRESETS` to start from
    field, optics, radius, volume_fraction, aspect
                     override the preset's value (None keeps it)
    domain           side of this layer's scatter/recycle box; None → the field's.
                     Snapped down to whole noise periods where possible (seamless)
    cell_size        side of one sort/recycle cell, metres
    fade_in          (lo, hi) camera distances the layer fades in over, or None
    fade_out         (lo, hi) it fades out over, or None for the horizon haze
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


_SPEC_OVERRIDES = ("field", "optics", "radius", "volume_fraction", "aspect")


def lod_shells(
    cloud_type: CloudType,
    count: int = 6,
    domain: float = 32000.0,
    cell_size: float = 1000.0,
    crossfade: tuple = (0.62, 0.85),
    **overrides,
):
    """Nested camera-centred shells carrying one cloud type out to the horizon.

    Optical depth through billboards goes as n·r³, so doubling each shell's radius
    allows an eighth the density: with four times the area, each shell costs HALF
    the previous and reach is nearly free (512 km ≈ 5% more than 128 km). Holding
    volume_fraction fixed does exactly that. Six shells, because an elevated deck
    stays visible to sqrt(2R·eye) + sqrt(2R·altitude), ~500 km from 9 km up.

    cell_size and max_optical_depth double with the radius too (a doubled chord
    doubles each fragment's depth).

    :param crossfade: (start, end) fractions of a shell's half-width where it hands
        over to the next; must complete inside the box to hide the recycle edge
    :param overrides: applied to every shell (e.g. a shared ``field``)
    :returns: a list of :class:`CloudLayer`, innermost first
    """
    preset = PRESETS[cloud_type]
    base_radius = overrides.pop("radius", None) or preset.radius
    base_optics = overrides.pop("optics", None) or preset.optics
    # Shell k fades out over band k while shell k+1 fades in over it: weights sum to 1.
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
                fade_out=bands[k] if k < count - 1 else None,
                **overrides,
            )
        )
    return shells


def _default_layers():
    """:returns: a cumulus deck in LOD shells — the type the field is tuned on."""
    return lod_shells(CloudType.CUMULUS)


# Panda's stock bins: background 10 < opaque 20 < transparent 30 < fixed 40.
_CLOUD_BIN = "cloud"
_CLOUD_BIN_SORT = 25


def _ensure_cloud_bins():
    """Register the cloud cull bin once; Panda silently ignores unknown bin names."""
    manager = CullBinManager.get_global_ptr()
    if manager.find_bin(_CLOUD_BIN) == -1:
        # BT_fixed: _restage sorts the geometry, so the bin must keep our order.
        manager.add_bin(_CLOUD_BIN, CullBinManager.BT_fixed, _CLOUD_BIN_SORT)


def _settings_quality(game) -> CloudQuality:
    """The player's cloud quality, or HIGH when there is no setting to read (the
    demo and the tests build from a stub game): never a crash or a downgrade."""
    config = getattr(getattr(game, "app", None), "graphics_settings", None)
    name = (getattr(config, "config", None) or {}).get("clouds", {}).get("quality")
    try:
        return CloudQuality(name)
    except ValueError:
        if name is not None:
            LOGGER.warning(f"unknown cloud quality {name!r}; using high")
        return CloudQuality.HIGH


@functools.cache
def _cloud_shader() -> Shader:
    return Shader.load(
        Shader.SL_GLSL,
        vertex=DATAFILES_PATH / "shaders/cloud.vert",
        fragment=DATAFILES_PATH / "shaders/cloud.frag",
    )


@functools.cache
def _noise_volume(seed: int) -> np.ndarray:
    """The noise octave quantised to the GPU's 8 bits, so CPU placement and GPU
    drawing agree bit for bit."""
    return quantise(value_noise_volume(seed=seed))


@functools.cache
def _calibration(seed: int, field: DensityField):
    """(sorted column peaks, fbm sigma) for an unresolved field: ~300 ms to measure,
    determined by field and seed alone, so shared across shells, scenes and tests."""
    volume = _noise_volume(seed)
    return column_peaks(volume, field), fbm_sigma(volume, field)


#: Floats per vertex, and per cell in cellParams ([x, y, z, layerId]); the latter
#: must match CELL_PARAMS_STRIDE in cloud.vert.
_VERTEX_FLOATS = 11
_CELL_PARAMS_STRIDE = 4
#: Cells per ROW of cellParams (CELLS_PER_ROW in cloud.vert). One long row walks
#: into GL_MAX_TEXTURE_DIMENSION at six shells, and every cell then reads zero.
_CELLS_PER_ROW = 1024


def _vertex_format() -> GeomVertexFormat:
    """:returns: local position, quad corner, radius, sprite rect and cell id.

    No colour column (colour is a function of world position) and no layer column
    (it rides in the cellParams row the vertex shader already fetches).
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


# Quad corners (CCW): BL, BR, TR, TL — the [-1,+1] offset and UV basis.
_CORNERS = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float32)
# Two triangles per quad, as offsets into a particle's 4-vertex block.
_QUAD_TRIS = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)


def _vec3(value) -> Vec3:
    return Vec3(*np.asarray(value, dtype=float)[:3])


class CloudField:
    """A drawable, wind-driven, depth-sorted field of mixed-type billboard clouds.

    Built in the constructor; call :meth:`update` once per frame. A layer's field
    is its shape (rebuild to change); its optics, coverage and the sun can be
    changed live with :meth:`set_optics`, :meth:`set_coverage`, :meth:`set_sun`.
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
        planet_radius=PLANET_RADIUS_M,
        near_fade_radii=2.5,
        quality=None,
        resort_frames=8,
        seed=7,
    ):
        """
        :param parent: NodePath the cloud geometry goes under
        :param game: the game object (sprite atlas, graphics settings)
        :param layers: list of :class:`CloudLayer` (default: a cumulus deck)
        :param domain: recycle-box side for layers that don't set one; the default
            is exactly one noise period at the cumulus feature size
        :param wind: metres/second drift
        :param sun_direction: vector FROM the scene TOWARD the sun
        :param sun_color: RGB of direct sunlight
        :param sky_color: RGB of the ambient sky fill
        :param haze_color: RGB distant cloud fades toward (default sky_color);
            should match what the ocean fades to
        :param sun_brightness: direct-term gain. NOT independent of ``exposure``:
            the tonemap knee saturates above ~3 and flattens lit onto shadowed
        :param sky_strength: ambient sky weight, lifting shadowed cloud off black
        :param sky_occlusion: fraction of sky light reaching a deck's underside
        :param exposure: cloud radiance scale before the soft-knee roll-off
        :param horizon_distance: metres over which cloud tends fully to haze_color.
            Must complete inside the outermost shell, and not much short of the
            ~500 km an elevated deck stays visible, or it dips under the horizon
        :param planet_radius: metres; the deck droops by d²/2R (0 = flat)
        :param near_fade_radii: fade a billboard within this many of its radii of
            the camera, so it never smears across the screen or clips (0 = off)
        :param quality: a :class:`CloudQuality`; None reads the graphics settings
            (HIGH if absent). Scales each layer's own request, so it composes with
            lod_shells and explicit overrides
        :param resort_frames: frames one full re-sort is spread over
        :param seed: RNG seed for the noise volume and placement
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
        # The shader's 1/(2R), so a zero or infinite radius means flat.
        self._curvature = (
            0.0 if not planet_radius else 1.0 / (2.0 * float(planet_radius))
        )
        self._near_fade_radii = near_fade_radii
        self._quality = quality if quality is not None else _settings_quality(game)
        self._resort_frames = max(1, int(resort_frames))
        self._seed = seed
        self._build()

    def _layer_spec(self, layer: CloudLayer):
        overrides = {
            name: getattr(layer, name)
            for name in _SPEC_OVERRIDES
            if getattr(layer, name) is not None
        }
        return at_quality(
            replace(PRESETS[layer.cloud_type], **overrides), self._quality
        )

    def _build(self):
        _ensure_cloud_bins()
        atlas_tex, rects = load_cloud_atlas(self._game)
        sprite_coverage = atlas_mean_alpha()
        # ONE volume for every layer; types decorrelate by a noise-space offset.
        volume = _noise_volume(self._seed)
        octave_mean = float(volume.mean())

        self._layer_params = np.zeros((MAX_LAYERS, LAYER_VEC4S, 4), dtype=np.float32)
        # _layer_specs is what each layer IS (set_* re-pack from it); _layer_report
        # only what the build measured, so the two cannot drift apart.
        self._layer_specs = []
        self._layer_cal = []
        self._layer_pack_args = []
        self._layer_report = []
        placements = []
        for index, layer in enumerate(self._layers):
            spec = self._layer_spec(layer)
            # Shared calibration, so LOD shells of one type get the SAME threshold
            # and agree about where cloud is across their crossfades.
            cal = _calibration(self._seed, spec.field)
            spec = replace(spec, field=with_threshold(spec.field, *cal))
            width, seamless = snap_to_noise_period(
                spec.field, float(layer.domain or self._domain)
            )
            placed = sample_field_particles(
                spec,
                volume,
                domain=width,
                cell_size=layer.cell_size,
                atlas_rects=rects,
                seed=self._seed + 1000 * index,
            )
            # Derived, not tuned: divided by the placement's own phi and by the
            # sprites' mean alpha, or every cloud comes out proportionally thin.
            extinction = spec.field.density / max(placed["phi"] * sprite_coverage, 1e-6)
            self._layer_specs.append(spec)
            self._layer_cal.append(cal)
            self._layer_pack_args.append(
                dict(
                    extinction=extinction,
                    wrap_radius=0.5 * width,
                    wrap_fade_band=0.0 if seamless else 0.12 * width,
                    octave_mean=octave_mean,
                    aspect=spec.aspect,
                    fade_in=layer.fade_in,
                    fade_out=layer.fade_out,
                )
            )
            self._repack(index)

            n_cells = len(placed["cell_centres"])
            placed["layer"] = np.full(n_cells, index, dtype=np.float32)
            placed["wrap"] = np.full(n_cells, 0.5 * width, dtype=np.float32)
            placed["pop"] = np.diff(placed["cell_start"])
            placements.append(placed)
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

        def cat(key):
            return np.concatenate([placed[key] for placed in placements])

        # One ragged particle array: cell c owns [cell_start[c], cell_start[c+1]).
        self._local = np.ascontiguousarray(cat("local"), np.float32)
        self._cell_centres = np.ascontiguousarray(cat("cell_centres"), np.float32)
        self._cell_layer = cat("layer")
        self._cell_wrap = cat("wrap")
        self._cell_pop = cat("pop")
        self._cell_start = np.concatenate([[0], np.cumsum(self._cell_pop)]).astype(
            np.int64
        )
        n = self._n = len(self._local)
        self._n_cells = len(self._cell_centres)
        # Wind advection of the field, in METRES (each layer scales it by its own
        # noise_scale in the shader), so billboards stay locked to their field.
        self._noise_offset = np.zeros(3, dtype=np.float64)

        # ── Static vertex data: 4 verts per particle ──────────────────────────
        per_particle = np.empty((n, _VERTEX_FLOATS), dtype=np.float32)
        per_particle[:, 0:3] = self._local
        per_particle[:, 5] = cat("radii")
        per_particle[:, 6:10] = cat("uv")
        per_particle[:, 10] = np.repeat(
            np.arange(self._n_cells, dtype=np.float32), self._cell_pop
        )
        verts = np.repeat(per_particle, 4, axis=0)
        verts[:, 3:5] = np.tile(_CORNERS, (n, 1))
        vdata = GeomVertexData("cloud_field", _vertex_format(), GeomEnums.UH_static)
        vdata.set_num_rows(4 * n)
        memoryview(vdata.modify_array(0)).cast("B")[: verts.nbytes] = memoryview(
            verts
        ).cast("B")

        # ── Index buffer, re-sorted by _restage (uint32 for >16k verts) ────────
        self._tris = GeomTriangles(GeomEnums.UH_dynamic)
        self._tris.set_index_type(GeomEnums.NT_uint32)
        self._tris.add_next_vertices(6 * n)
        # A valid natural order BEFORE add_primitive, which validates indices.
        self._stage = (np.arange(n, dtype=np.uint32)[:, None] * 4 + _QUAD_TRIS).ravel()
        self._upload_indices()
        # Round-robin state; a cursor at the end starts a cycle on the first update.
        self._draw_order = None
        self._buf_offset = None
        self._cyc_cursor = self._n_cells

        geom = Geom(vdata)
        geom.add_primitive(self._tris)
        gnode = GeomNode("cloud_field")
        gnode.add_geom(geom)
        # Billboards extend past their centres; skip culling rather than inflate.
        gnode.set_bounds(OmniBoundingVolume())
        gnode.set_final(True)

        self.node = self._parent.attach_new_node(gnode)
        self.node.set_texture(atlas_tex)
        self.node.set_transparency(TransparencyAttrib.M_none)  # blend set below
        self.node.set_shader(_cloud_shader())
        self.node.set_depth_test(True)
        self.node.set_depth_write(False)
        self.node.set_bin(_CLOUD_BIN, 0)
        self.node.set_attrib(
            ColorBlendAttrib.make(
                ColorBlendAttrib.M_add,
                ColorBlendAttrib.O_one,
                ColorBlendAttrib.O_one_minus_incoming_alpha,
            )
        )

        # Per-cell [x, y, z, layerId] as R32F (no BGRA ambiguity), wrapped into
        # rows; the layer ids are fixed, only the centres change per frame.
        self._cell_rows = -(-self._n_cells // _CELLS_PER_ROW)
        self._cell_params = np.zeros(
            (self._cell_rows * _CELLS_PER_ROW, _CELL_PARAMS_STRIDE), dtype=np.float32
        )
        self._cell_params[: self._n_cells, 3] = self._cell_layer
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

        self._upload_layer_params()
        self.node.set_shader_inputs(
            camPos=Vec3(0, 0, 0),
            cellParams=self._cell_tex,
            sunBrightness=float(self._sun_brightness),
            skyStrength=float(self._sky_strength),
            skyOcclusion=float(self._sky_occlusion),
            exposure=float(self._exposure),
            horizonFade=1.0 / max(float(self._horizon_distance), 1.0),
            earthCurvature=float(self._curvature),
            cloudNoise=build_noise_texture(volume),
            noiseSize=float(NOISE_SIZE),
            noiseOffset=Vec3(0, 0, 0),
            nearFadeRadii=float(self._near_fade_radii),
        )
        self.set_sun(
            self._sun_direction,
            self._sun_color_arg,
            self._sky_color_arg,
            self._haze_color_arg,
        )

    # ── Live edits ────────────────────────────────────────────────────────────

    def _repack(self, index):
        spec = self._layer_specs[index]
        self._layer_params[index] = pack_layer_params(
            spec.field, optics=spec.optics, **self._layer_pack_args[index]
        )

    def _upload_layer_params(self):
        pta = PTA_LVecBase4f()
        for row in self._layer_params.reshape(-1, 4):
            pta.push_back(LVecBase4f(*(float(v) for v in row)))
        self.node.set_shader_input("layerParams", pta)

    def _edit_layers(self, layer, edit):
        """Apply ``edit(index, spec) -> spec`` to one layer (or all), re-pack and
        re-upload."""
        indices = range(len(self._layer_specs)) if layer is None else [layer]
        for index in indices:
            self._layer_specs[index] = edit(index, self._layer_specs[index])
            self._repack(index)
        self._upload_layer_params()

    def set_coverage(self, layer=None, coverage=None, edge_softness=None):
        """Change how much of the sky one cloud type (or all) covers, live.

        A new threshold is an index into the cached column peaks, but billboards
        are NOT re-placed: lowering coverage is exact (the surplus discards),
        raising it past the built value grows holes. A tuning knob; rebuild to
        commit a higher coverage.

        :param layer: layer index, or None for every layer
        :param coverage: new zenith-projected cloud fraction, or None to keep
        :param edge_softness: new window width in sigma, or None to keep
        :returns: the resulting :class:`DensityField` per layer
        """

        def edit(index, spec):
            field = spec.field
            changed = replace(
                field,
                coverage=field.coverage if coverage is None else float(coverage),
                edge_softness=(
                    field.edge_softness
                    if edge_softness is None
                    else float(edge_softness)
                ),
            )
            return replace(spec, field=with_threshold(changed, *self._layer_cal[index]))

        self._edit_layers(layer, edit)
        return [spec.field for spec in self._layer_specs]

    def set_optics(self, layer=None, **changes):
        """Change :class:`CloudOptics` fields of one layer (or all), live. Shape
        lives in the DensityField and needs a rebuild.

        :returns: the resulting :class:`CloudOptics` per layer
        :raises AttributeError: for a name that is not a CloudOptics field
        """
        unknown = set(changes) - {f.name for f in fields(CloudOptics)}
        if unknown:
            raise AttributeError(
                f"not CloudOptics parameters: {sorted(unknown)}. Shape parameters "
                "live in DensityField and need a rebuild."
            )
        self._edit_layers(
            layer,
            lambda index, spec: replace(spec, optics=replace(spec.optics, **changes)),
        )
        return [spec.optics for spec in self._layer_specs]

    def set_sun(self, direction, sun_color=None, sky_color=None, haze_color=None):
        """Move the sun and/or restate its colours; nothing is baked, so this is a
        few uniform writes.

        :param direction: vector FROM the scene TOWARD the sun (need not be unit)
        :param sun_color: RGB of direct sunlight, or None to keep
        :param sky_color: RGB of the ambient sky, or None to keep; also sets the
            haze colour unless *haze_color* is given
        :param haze_color: RGB distant cloud tends toward, or None to keep
        """
        sun_dir = np.asarray(direction, dtype=float)[:3]
        norm = np.linalg.norm(sun_dir)
        if norm < 1e-9:
            raise ValueError("sun direction must be a non-zero vector")
        self._sun_direction = tuple(float(v) for v in sun_dir)
        self.node.set_shader_input("sunDir", Vec3(*(sun_dir / norm)))
        if sky_color is not None and haze_color is None:
            haze_color = sky_color
        for name, attr, value in (
            ("sunColor", "_sun_color_arg", sun_color),
            ("skyColor", "_sky_color_arg", sky_color),
            ("hazeColor", "_haze_color_arg", haze_color),
        ):
            if value is not None:
                setattr(self, attr, value)
                self.node.set_shader_input(name, _vec3(value))

    # ── Per-frame ─────────────────────────────────────────────────────────────

    def update(self, cam_pos: Vec3, dt: float = 0.0):
        """Advance one frame: drift + recycle the cells and continue the re-sort.

        :param cam_pos: camera world position
        :param dt: seconds since the last frame (drives wind drift)
        """
        self.node.set_shader_input("camPos", cam_pos)
        cam_xyz = np.array([cam_pos.x, cam_pos.y, cam_pos.z], dtype=np.float32)

        if dt:
            self._cell_centres += self._wind * dt
            # The field drifts with the SAME wind, so a puff keeps its shape.
            self._noise_offset -= self._wind * dt
            self.node.set_shader_input("noiseOffset", Vec3(*self._noise_offset))
        # Toroidal recycle into each layer's camera-centred box; seamless where the
        # box is a whole number of noise periods.
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
        self._cell_params[: self._n_cells, 0:3] = self._cell_centres
        self._cell_tex.set_ram_image(self._cell_params.tobytes())

    def _upload_indices(self):
        memoryview(self._tris.modify_vertices()).cast("B")[
            : self._stage.nbytes
        ] = self._stage.tobytes()

    def _restage(self, cam_xyz):
        """Re-sort one round-robin slice of cells into the staged index buffer.

        A cell draw order (far → near) is snapshotted per cycle, with each rank's
        slot range from the cumulative ragged populations; within a slice the whole
        gather and sort is one lexsort on (cell rank, distance). The buffer is
        uploaded once per completed cycle, so the GPU only sees consistent orders.
        """
        n_cells = self._n_cells
        cells_per_frame = -(-n_cells // self._resort_frames)
        if self._cyc_cursor >= n_cells:
            centre_rel = self._cell_centres - cam_xyz
            self._draw_order = np.argsort(
                -np.einsum("ij,ij->i", centre_rel, centre_rel)
            )
            self._buf_offset = np.concatenate(
                [[0], np.cumsum(self._cell_pop[self._draw_order])]
            ).astype(np.int64)
            self._cyc_cursor = 0

        start = self._cyc_cursor
        end = min(start + cells_per_frame, n_cells)
        cells = self._draw_order[start:end]
        counts = self._cell_pop[cells]
        total = int(counts.sum())
        if total:
            # Ragged gather: (start, count) per cell → one flat particle-id array.
            group_start = np.cumsum(counts) - counts
            particle_ids = np.repeat(self._cell_start[cells] - group_start, counts)
            particle_ids = particle_ids + np.arange(total)
            group = np.repeat(np.arange(len(cells)), counts)

            world = (
                self._cell_centres[np.repeat(cells, counts)] + self._local[particle_ids]
            )
            offset = world - cam_xyz
            dist_sq = np.einsum("ij,ij->i", offset, offset)
            order = np.lexsort((-dist_sq, group))
            lo, hi = self._buf_offset[start], self._buf_offset[end]
            self._stage[lo * 6 : hi * 6] = (
                particle_ids[order][:, None] * 4 + _QUAD_TRIS
            ).ravel()
        self._cyc_cursor = end

        if end >= n_cells:
            self._upload_indices()


class Clouds:
    """A :class:`CloudField` under ``game.root_node`` following the scene
    convention: per-frame update via game.method_lists, and clean(). Keyword
    arguments pass straight through to CloudField.
    """

    def __init__(self, game, layers=None, **field_kwargs):
        self.game = game
        self.id = uuid.uuid4()
        self.field = CloudField(
            parent=game.root_node, game=game, layers=layers, **field_kwargs
        )
        game.method_lists[self.id] = [self.update]

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
