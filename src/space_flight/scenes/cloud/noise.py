"""
noise.py — The cloud density field, as data.

A cloud type's shape is ONE continuous world-space density function that every
billboard fragment of that type samples (datafiles/shaders/cloud.frag). This
module owns that function: the tileable noise octave it is built from, the per-type
parameters that shape it (:class:`DensityField`), and a NumPy evaluator that
reproduces the shader's result exactly, so placement can be driven by the very
field that is drawn.

Density must be a function of world position ALONE — never per cloud — or
overlapping billboards disagree about where the boundary is. Design notes:
docs/source/scenes.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from panda3d.core import SamplerState, Texture

# Volume resolution, and the random lattice it is upsampled from. NOISE_SIZE must be
# a multiple of NOISE_LATTICE so the result tiles.
NOISE_SIZE = 64
NOISE_LATTICE = 16

# Noise units per lattice cell: one feature of one octave. Divide by noise_scale
# for metres.
NOISE_FEATURE = NOISE_SIZE / NOISE_LATTICE

# Per-octave offsets, so the octaves never re-align into a grid. MUST match
# OCTAVE_n_OFFSET in cloud.frag (a test reads the shader), or billboards get placed
# where the shader draws no cloud.
OCTAVE_OFFSETS = (
    (0.0, 0.0, 0.0),
    (0.31, 0.73, 0.19),
    (-0.57, 0.11, 0.83),
    (0.67, -0.29, 0.41),
)

#: Coverage calibration resolution (see :func:`column_peaks`): within 0.3% of the
#: requested coverage. 96 rather than 128 on purpose: a power of two lands every
#: column on the same phase of the finest octave and biases the measurement.
COVERAGE_GRID = 96
COVERAGE_LEVELS = 32

#: vec4s per cloud type in the layerParams uniform array, and the most layers one
#: field may mix (LOD shells count as layers). Must match cloud.frag / cloud.vert.
LAYER_VEC4S = 12
MAX_LAYERS = 8


@dataclass(frozen=True)
class DensityField:
    """The density field of ONE cloud type: a slab of sky and how it is carved.

    Frozen, because the GPU copy is packed once and must not drift from it.

    slab            (base_z, thickness) metres, shared by every cloud of the type
    density         optical density per metre of fully-dense cloud
    noise_scale     world metres → noise coords, per axis (anisotropy → cirrus)
    octave_scales   the four fbm octave frequencies; INTEGERS, so a recycle by a
                    whole noise period is seamless for every octave
    octave_weights  the four octave amplitudes
    coverage        fraction of the slab's columns (zenith-projected) that hold
                    cloud at any height — the authored amount of cloud
    edge_softness   smoothstep window width, in standard deviations of this field's
                    fbm (see :func:`fbm_sigma`); narrow = crisp cauliflower edge
    threshold       (lo, hi) window DERIVED from coverage and edge_softness against
                    a noise volume; None until :func:`resolve_field`
    base_ramp       how abruptly density fills in above the base (flat undersides)
    top_erosion     how far the threshold rises by the slab top (bulging tops)
    top_exponent    the curve of that rise
    offset          noise-space translation decorrelating types that share one
                    volume (see :func:`field_offset`)
    """

    slab: tuple = (1000.0, 600.0)
    density: float = 0.03
    noise_scale: tuple = (0.001, 0.001, 0.001)
    octave_scales: tuple = (1.0, 2.0, 7.0, 16.0)
    octave_weights: tuple = (0.5, 0.25, 0.125, 0.0625)
    coverage: float = 0.29
    edge_softness: float = 0.48
    threshold: tuple = None
    base_ramp: float = 5.0
    top_erosion: float = 0.40
    top_exponent: float = 3.0
    offset: tuple = (0.0, 0.0, 0.0)

    @property
    def feature_size(self) -> tuple:
        """:returns: per-axis world size in metres of the field's largest feature."""
        return tuple(NOISE_FEATURE / s for s in self.noise_scale)


@dataclass(frozen=True)
class CloudOptics:
    """How light travels through ONE cloud type. Per-fragment only, so unlike the
    field it can be changed live (:meth:`CloudField.set_optics`).

    sun_steps           steps of the per-fragment sun march (0 = no self-shadow)
    sun_step_length     metres per step; steps x length ≈ one cloud's depth
    shadow_strength     scales the sunward optical depth (1 = physical)
    multiple_scattering sky-coloured, NOT phase-weighted fill for shadowed cloud
    powder_strength     empirical darkening of optically thin cloud (0 = off)
    powder_length       metres turning LOCAL density into the powder's optical depth
    max_optical_depth   cap on what one billboard contributes, so a quad never
                        becomes a hard-edged opaque blob
    forward_gain        brightness looking into the sun, relative to side-on (1)
    backward_gain       brightness with the sun behind you, relative to side-on
    forward_anisotropy  forward lobe's Henyey-Greenstein g: the falloff SHAPE only;
                        the gains are pinned by :func:`phase_weights`
    """

    sun_steps: int = 4
    sun_step_length: float = 160.0
    shadow_strength: float = 1.0
    multiple_scattering: float = 0.12
    powder_strength: float = 0.6
    powder_length: float = 200.0
    max_optical_depth: float = 1.5
    forward_gain: float = 4.72
    backward_gain: float = 1.52
    forward_anisotropy: float = 0.4


#: Anisotropy of the phase function's fixed backward lobe.
BACKWARD_ANISOTROPY = -0.4
#: The HG peak diverges as g → 1. The CLAMPED value is what gets packed, so the
#: shader evaluates the same basis the weights were solved against.
FORWARD_ANISOTROPY_MAX = 0.95
#: Single-scattering Mie asymmetry of cloud droplets (OPAC); see delta_eddington.
MIE_ASYMMETRY_WATER = 0.85
MIE_ASYMMETRY_ICE = 0.80


def delta_eddington(asymmetry: float, applicability: float = 1.0) -> float:
    """The delta-Eddington similarity scaling, ``g -> g / (1 + g)``.

    Raw Mie asymmetry fed to a single-scattering shader saturates the sunward sky;
    the scaled value stands in for the flatter phase function multiple scattering
    produces (water 0.85 → 0.46). Thin cloud is near single scattering, so
    *applicability* (1 = thick, 0 = thin) blends back toward the raw value.
    """
    scaled = asymmetry / (1.0 + asymmetry)
    return asymmetry + (scaled - asymmetry) * applicability


def henyey_greenstein(cos_angle, anisotropy: float):
    """The Henyey-Greenstein phase function, matching the shader's ``hgPhase``.

    :param cos_angle: cosine between the light and the view ray (1 = into the light)
    :param anisotropy: the lobe's g; positive scatters forward
    """
    g = anisotropy
    g2 = g * g
    return 0.25 * (1.0 - g2) * (1.0 + g2 - 2.0 * g * np.asarray(cos_angle)) ** -1.5


def clamped_anisotropy(optics: CloudOptics) -> float:
    """:returns: the forward anisotropy in force, shared by solve, pack and CPU."""
    return min(max(optics.forward_anisotropy, 0.0), FORWARD_ANISOTROPY_MAX)


def _basis(g: float, cos_angle) -> np.ndarray:
    """:returns: (..., 3) forward-lobe, backward-lobe and isotropic phase terms."""
    cos_angle = np.asarray(cos_angle, dtype=np.float64)
    return np.stack(
        [
            henyey_greenstein(cos_angle, g),
            henyey_greenstein(cos_angle, BACKWARD_ANISOTROPY),
            np.full_like(cos_angle, 0.25),
        ],
        axis=-1,
    )


def phase_weights(optics: CloudOptics):
    """Solve the three lobe weights that hit this type's gains exactly.

    Two lobes alone leave one degree of freedom for two observables, so the forward
    and backward brightness fight each other. The isotropic term makes it an exact
    3x3 solve pinning 0° → forward_gain, 180° → backward_gain, 90° → 1.

    :returns: (forward, backward, isotropic) weights
    :raises ValueError: if the phase would go negative anywhere (a dark hole)
    """
    g = clamped_anisotropy(optics)
    weights = np.linalg.solve(
        _basis(g, [1.0, -1.0, 0.0]),
        np.array([optics.forward_gain, optics.backward_gain, 1.0]),
    )
    # Check the whole range: a dip would fall between the pinned angles.
    sweep = _basis(g, np.linspace(-1.0, 1.0, 361)) @ weights
    if sweep.min() < 0.0:
        raise ValueError(
            f"forward_gain={optics.forward_gain} with "
            f"backward_gain={optics.backward_gain} makes the phase function go "
            f"negative ({sweep.min():.3f}) at some angle, which renders as a dark "
            "hole. Move the gains closer together, or raise forward_anisotropy to "
            "concentrate the forward lobe."
        )
    return tuple(float(w) for w in weights)


def phase(optics: CloudOptics, cos_angle):
    """The shader's phase function on the CPU; 1 when side-lit (90°).

    :param cos_angle: cosine between the sun and the view ray (1 = into the sun)
    """
    basis = _basis(clamped_anisotropy(optics), cos_angle)
    forward, backward, isotropic = phase_weights(optics)
    return (
        basis[..., 0] * forward + basis[..., 1] * backward + basis[..., 2] * isotropic
    )


def streak_direction(spec: DensityField) -> tuple:
    """:returns: the horizontal unit axis (x, y) the field's features are longest
    along. Derived, so stretched billboards cannot comb against the field."""
    return (1.0, 0.0) if spec.noise_scale[0] <= spec.noise_scale[1] else (0.0, 1.0)


def field_offset(seed: int) -> tuple:
    """:returns: a decorrelating (x, y, z) noise-space offset for a cloud type.

    A shifted copy of the stationary, repeat-wrapped volume is an independent field
    with identical statistics, for the cost of one add.
    """
    rng = np.random.default_rng(0x51EED ^ int(seed))
    return tuple(float(v) for v in rng.uniform(0.0, NOISE_SIZE, 3))


# ── The noise volume ───────────────────────────────────────────────────────────


def _axis_weights(size: int, lattice: int):
    """:returns: (i0, i1, t) wrapping lattice indices and smoothstep weights."""
    coord = np.arange(size, dtype=np.float64) * (lattice / size)
    i0 = np.floor(coord).astype(np.int64) % lattice
    frac = coord - np.floor(coord)
    # Smoothstep keeps the field C1 across lattice cells: a narrow threshold window
    # would show every crease of a plain linear upsample.
    return i0, (i0 + 1) % lattice, (frac * frac * (3.0 - 2.0 * frac)).astype(np.float32)


def value_noise_volume(
    size: int = NOISE_SIZE, lattice: int = NOISE_LATTICE, seed: int = 0
) -> np.ndarray:
    """One tileable octave of 3D value noise, normalised to [0,1].

    Value noise, as the reference shader uses: the lattice's blobbiness is what the
    low octaves carry the formations with.

    :returns: (size, size, size) float32, indexed [z, y, x]
    """
    if size % lattice != 0:
        raise ValueError(f"size {size} must be a whole multiple of lattice {lattice}")

    rng = np.random.default_rng(seed)
    grid = rng.random((lattice, lattice, lattice), dtype=np.float32)
    i0, i1, t = _axis_weights(size, lattice)

    # Separable lerps, x then y then z: identical arithmetic to a per-corner blend.
    gx = grid[:, :, i0] + (grid[:, :, i1] - grid[:, :, i0]) * t[None, None, :]
    gy = gx[:, i0, :] + (gx[:, i1, :] - gx[:, i0, :]) * t[None, :, None]
    volume = gy[i0] + (gy[i1] - gy[i0]) * t[:, None, None]

    # Span the full [0,1]: the threshold window is absolute, and the upload is 8-bit.
    lo, hi = float(volume.min()), float(volume.max())
    return ((volume - lo) / max(hi - lo, 1e-9)).astype(np.float32)


def quantise(volume: np.ndarray) -> np.ndarray:
    """:returns: *volume* rounded to the 8 bits per texel the GPU copy stores, so
    CPU placement and GPU drawing cannot drift apart at the silhouette."""
    return (np.round(volume * 255.0) / 255.0).astype(np.float32)


def build_noise_texture(volume: np.ndarray) -> Texture:
    """Wrap a noise volume in a repeat-wrapped, linearly filtered 3D texture.

    Needs no graphics context. A 3D RAM image is page-major, i.e. numpy's [z, y, x].

    :param volume: a (n, n, n) volume in [0,1], quantised or not
    """
    size = volume.shape[0]
    texture = Texture("cloud_noise")
    texture.setup_3d_texture(size, size, size, Texture.T_unsigned_byte, Texture.F_red)
    texture.set_ram_image(
        np.ascontiguousarray(np.round(volume * 255.0), np.uint8).tobytes()
    )
    for set_wrap in (texture.set_wrap_u, texture.set_wrap_v, texture.set_wrap_w):
        set_wrap(Texture.WM_repeat)
    texture.set_magfilter(SamplerState.FT_linear)
    # NOT mipmapped: a 3D mip chain averages the 16x octave away to a constant.
    texture.set_minfilter(SamplerState.FT_linear)
    return texture


# ── The field, evaluated on the CPU exactly as the shader evaluates it ─────────


def sample_volume(volume: np.ndarray, coords: np.ndarray) -> np.ndarray:
    """Sample *volume* as ``texture(cloudNoise, coord / NOISE_SIZE)`` does:
    trilinear and repeat-wrapped, including hardware linear's half-texel offset
    (coordinate u addresses texel centre u*size - 0.5). Getting that wrong shifts
    every octave by half its texel (250 m for the lowest cumulus octave), moving
    placement off the drawn cloud.

    :param volume: (n, n, n) float array indexed [z, y, x]
    :param coords: (..., 3) sample positions in noise coords
    """
    size = volume.shape[0]
    coords = np.asarray(coords, dtype=np.float64)
    texel = coords - 0.5
    base = np.floor(texel)
    frac = texel - base
    i0 = base.astype(np.int64) % size
    i1 = (i0 + 1) % size
    x0, y0, z0 = i0[..., 0], i0[..., 1], i0[..., 2]
    x1, y1, z1 = i1[..., 0], i1[..., 1], i1[..., 2]
    tx, ty, tz = frac[..., 0], frac[..., 1], frac[..., 2]

    c000, c100 = volume[z0, y0, x0], volume[z0, y0, x1]
    c010, c110 = volume[z0, y1, x0], volume[z0, y1, x1]
    c001, c101 = volume[z1, y0, x0], volume[z1, y0, x1]
    c011, c111 = volume[z1, y1, x0], volume[z1, y1, x1]
    c00 = c000 + (c100 - c000) * tx
    c01 = c010 + (c110 - c010) * tx
    c10 = c001 + (c101 - c001) * tx
    c11 = c011 + (c111 - c011) * tx
    c0 = c00 + (c01 - c00) * ty
    c1 = c10 + (c11 - c10) * ty
    return c0 + (c1 - c0) * tz


def fbm(volume: np.ndarray, coords: np.ndarray, spec: DensityField) -> np.ndarray:
    """The four-octave fbm of the shader's ``cloudFbm``.

    :param coords: (..., 3) noise coords (world * noise_scale + offset)
    """
    total = np.zeros(np.shape(coords)[:-1], dtype=np.float64)
    for scale, weight, offset in zip(
        spec.octave_scales, spec.octave_weights, OCTAVE_OFFSETS
    ):
        total += sample_volume(volume, coords * scale + np.asarray(offset)) * weight
    return total


def threshold_lift(spec: DensityField, h: np.ndarray) -> np.ndarray:
    """How far the threshold has risen at normalised slab height *h*.

    Raising the THRESHOLD, not fading density, is what makes tops bulge: strong
    columns keep clearing the rising bar and tower, weak ones stop short. Fading
    density could only slice every cloud off at one altitude. Once the lift passes
    the fbm's maximum nothing is cloud, which bounds the slab with no hard clamp.
    """
    return spec.top_erosion * np.clip(h, 0.0, 1.0) ** spec.top_exponent


def fbm_sigma(volume: np.ndarray, spec: DensityField) -> float:
    """Standard deviation of the field's fbm, the unit of ``edge_softness``.

    Treating octaves as independent samples: std(volume) * sqrt(sum(w²)). Derived
    so retuning the octave weights does not silently change edge crispness.
    """
    weights = np.asarray(spec.octave_weights, dtype=np.float64)
    return float(volume.std() * np.sqrt((weights**2).sum()))


def column_peaks(
    volume: np.ndarray,
    spec: DensityField,
    grid: int = COVERAGE_GRID,
    levels: int = COVERAGE_LEVELS,
) -> np.ndarray:
    """The per-column peak of ``fbm - threshold_lift``, SORTED ascending.

    A column holds cloud exactly when its peak exceeds threshold_lo, so this sorted
    array is the inverse of the coverage function: the (1 - coverage) quantile IS
    the threshold. (base_ramp scales density, never whether a column is cloud, so
    it drops out.) Sampled on a half-offset grid over one full noise period, which
    is the whole toroidal population, and deterministic.

    :param levels: samples through the slab; under-sampling misses thin peaks and
        biases coverage low, so this must resolve the finest octave (~125 m
        features at the cumulus scale against a 1000 m slab)
    :returns: (grid*grid,) sorted peaks, in raw fbm units
    """
    base, thickness = spec.slab
    step = (np.arange(grid) + 0.5) / grid
    period = [NOISE_SIZE / s for s in spec.noise_scale[:2]]
    x, y = np.meshgrid(step * period[0], step * period[1], indexing="ij")
    h = (np.arange(levels) + 0.5) / levels
    points = np.empty((grid * grid, levels, 3), dtype=np.float64)
    points[..., 0] = x.reshape(-1, 1)
    points[..., 1] = y.reshape(-1, 1)
    points[..., 2] = base + h[None, :] * thickness
    coords = points * np.asarray(spec.noise_scale) + np.asarray(spec.offset)
    peaks = (fbm(volume, coords, spec) - threshold_lift(spec, h)[None, :]).max(axis=1)
    peaks.sort()
    return peaks


def threshold_from_peaks(
    peaks: np.ndarray, coverage: float, edge_softness: float, sigma: float
) -> tuple:
    """Read the (lo, hi) threshold window off measured, sorted column peaks.

    The peaks never change for a field, so caching them makes a coverage change an
    array index — which is what lets coverage be swept live.
    """
    width = float(edge_softness) * float(sigma)
    # Exact endpoints: a 0/1 quantile lands ON an observed peak, and the test is
    # strict, so "everything" would miss the strongest column.
    if coverage >= 1.0:
        lo = float(peaks[0]) - width
    elif coverage <= 0.0:
        lo = float(peaks[-1]) + width
    else:
        index = (1.0 - coverage) * (len(peaks) - 1)
        low = int(np.floor(index))
        frac = index - low
        lo = float(
            peaks[low] * (1.0 - frac) + peaks[min(low + 1, len(peaks) - 1)] * frac
        )
    return lo, lo + width


def with_threshold(spec: DensityField, peaks: np.ndarray, sigma: float) -> DensityField:
    """:returns: *spec* with its threshold derived from already-measured peaks."""
    return replace(
        spec,
        threshold=threshold_from_peaks(peaks, spec.coverage, spec.edge_softness, sigma),
    )


def resolve_field(volume: np.ndarray, spec: DensityField) -> DensityField:
    """Fill in a field's derived ``threshold`` so it can be drawn and placed.

    :param volume: the noise octave (quantised, to match the GPU copy)
    """
    return with_threshold(spec, column_peaks(volume, spec), fbm_sigma(volume, spec))


def measure_coverage(volume: np.ndarray, spec: DensityField) -> float:
    """:returns: the coverage a resolved field actually achieves — the round trip
    that makes the knob trustworthy."""
    _require_resolved(spec)
    return float((column_peaks(volume, spec) > spec.threshold[0]).mean())


def _require_resolved(spec: DensityField):
    """Fail loudly: a None threshold would otherwise surface far away, or read as 0
    and turn the whole slab into solid cloud."""
    if spec.threshold is None:
        raise ValueError(
            "this DensityField's threshold is still derived-but-unresolved; call "
            "noise.resolve_field(volume, spec) first (the threshold for a given "
            "coverage depends on the noise volume, so a field alone cannot know it)"
        )


def density(volume: np.ndarray, spec: DensityField, points: np.ndarray) -> np.ndarray:
    """The shader's ``cloudDensity`` on the CPU, which drives billboard placement.

    Flat bases scale DENSITY (condensation starts at one altitude); bulging tops
    raise the THRESHOLD (see :func:`threshold_lift`).

    :param volume: the noise octave (quantised, to match the GPU bit for bit)
    :param points: (..., 3) world positions in metres
    :returns: (...) density in [0, 1]
    """
    _require_resolved(spec)
    points = np.asarray(points, dtype=np.float64)
    base, thickness = spec.slab
    h = (points[..., 2] - base) / max(thickness, 1e-3)
    coords = points * np.asarray(spec.noise_scale) + np.asarray(spec.offset)
    raw = fbm(volume, coords, spec)
    lift = threshold_lift(spec, h)
    lo, hi = spec.threshold[0] + lift, spec.threshold[1] + lift
    t = np.clip((raw - lo) / np.maximum(hi - lo, 1e-9), 0.0, 1.0)
    coverage = t * t * (3.0 - 2.0 * t)
    base_fill = 1.0 - np.exp2(-spec.base_ramp * np.clip(h, 0.0, 1.0))
    inside = (h > 0.0) & (h < 1.0)
    return np.where(inside, coverage * base_fill, 0.0)


# ── The GPU copy of a field's parameters ───────────────────────────────────────


def shadow_calibration(spec: DensityField, octave_mean: float):
    """Affine correction making the sun march's 2-octave fbm match the full field.

    The two lowest octaves correlate with the full fbm at 0.97 but have the wrong
    mean and spread, so uncorrected the march sees 1.65x the cloud (grey tops in
    full sun). Treating octaves as independent (mean m, sd s): the gain matches the
    spreads sqrt(Σw²)/sqrt(w0²+w1²), the bias then matches the means.

    :returns: (gain, bias) for ``gain * two_octave_sum + bias``
    """
    weights = np.asarray(spec.octave_weights, dtype=np.float64)
    full_sd = np.sqrt((weights**2).sum())
    pair_sd = np.sqrt((weights[:2] ** 2).sum())
    gain = full_sd / max(pair_sd, 1e-9)
    bias = octave_mean * (weights.sum() - gain * weights[:2].sum())
    return float(gain), float(bias)


def pack_layer_params(
    spec: DensityField,
    extinction: float,
    wrap_radius: float,
    wrap_fade_band: float,
    octave_mean: float = 0.5,
    optics: CloudOptics = CloudOptics(),
    aspect: float = 1.0,
    fade_in: tuple = None,
    fade_out: tuple = None,
):
    """Flatten one type into its LAYER_VEC4S rows of the layerParams array.

    The row layout IS the contract with cloud.frag's getField; change both together.

    :param extinction: per-BILLBOARD extinction (density / volume fraction; see
        cloud.volume_fraction)
    :param wrap_radius: half-width of the toroidal recycle box, metres
    :param wrap_fade_band: metres of fade at the box face (0 when seamless)
    :param octave_mean: noise volume mean, for :func:`shadow_calibration`
    :param aspect: billboard long:short ratio (area-preserving, so no recalibration)
    :param fade_in: (lo, hi) camera distances the layer fades in over, None = none
    :param fade_out: (lo, hi) it fades out over, None = to the horizon haze
    :returns: a (LAYER_VEC4S, 4) float32 array
    """
    _require_resolved(spec)
    gain, bias = shadow_calibration(spec, octave_mean)
    forward, backward, isotropic = phase_weights(optics)
    # "No fade" sentinels make the shader's smoothsteps degenerate to 1 branch-free.
    fade_in = fade_in if fade_in is not None else (-1.0, 0.0)
    fade_out = fade_out if fade_out is not None else (1e9, 2e9)
    o = optics
    return np.array(
        [
            (*spec.noise_scale, spec.threshold[0]),
            spec.octave_scales,
            spec.octave_weights,
            (*spec.offset, spec.threshold[1]),
            (spec.slab[0], spec.slab[1], spec.base_ramp, spec.top_erosion),
            # Two extinctions: the billboard sum's, and the FIELD's for the sun
            # march, a continuous integral that must not be scaled by 1/phi.
            (extinction, spec.density, wrap_radius, wrap_fade_band),
            (spec.top_exponent, gain, bias, o.max_optical_depth),
            (o.sun_steps, o.sun_step_length, o.shadow_strength, o.multiple_scattering),
            (o.powder_strength, o.powder_length, forward, backward),
            (isotropic, clamped_anisotropy(o), 0.0, 0.0),
            (aspect, *streak_direction(spec), 0.0),
            (*fade_in, *fade_out),
        ],
        dtype=np.float32,
    )
