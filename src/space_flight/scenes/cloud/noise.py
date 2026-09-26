"""
noise.py — The cloud density field, as data.

A cloud type's shape comes from ONE continuous world-space density function that
every billboard fragment of that type samples (see datafiles/shaders/cloud.frag).
This module owns that function: the tileable noise octave it is built from, the
per-type parameters that shape it (:class:`DensityField`), and a NumPy
evaluator that reproduces the shader's result exactly.

Why the density field is per cloud TYPE, and never per cloud
-----------------------------------------------------------
The crisp silhouette exists because every billboard covering a pixel agrees
where the cloud's boundary is.  That holds only while density is a function of
world position ALONE.  An earlier version scaled the vertical profile by each
cloud's own slab, which broke it: two overlapping clouds at slightly different
altitudes evaluated different density at the same point, and the profile's cut
at the top of one cloud's slab sliced a flat plane through the body of its
neighbour — visible as hard-edged plates and straight-sided holes.

So a cloud type has ONE slab and ONE field spanning the whole sky, exactly as the
reference shader does.  Individual clouds are not objects with their own
parameters; they are the features of the type's field, and the billboards are
merely where it is dense enough to be worth drawing (see cloud.py).

Mixing types is a superposition, and it happens in the BLENDER, not here: each
billboard samples the field of its own type, and the premultiplied-over blend
sums the optical depths of every veil along a view ray.  That is why two types
whose slabs overlap still composite correctly without any fragment ever having
to evaluate more than one field.

Why one octave in a texture, and four taps in the shader rather than a baked fbm:

  * The octaves are sampled at scales 1 / 2 / 7 / 16 with independent offsets.
    Baking them together would freeze their relative phase, and the deliberately
    non-integer 7x scale only decorrelates because the octaves are separate.
  * Resolving the 16x octave in a baked volume would need 16x the resolution --
    1024**3, about a gigabyte.

Four taps into a 256 KB volume stay resident in cache, and hardware trilinear
filtering makes each tap cheaper than the two-tap-plus-mix that a 2D texture
faking a 3D one would need.

The volume is regenerated at load (a few milliseconds) rather than cached to
disk: reading an .npz back costs more than rebuilding it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from panda3d.core import SamplerState, Texture

# Volume resolution, and the random lattice it is smoothly upsampled from.
# NOISE_SIZE must be an integer multiple of NOISE_LATTICE so the result tiles.
NOISE_SIZE = 64
NOISE_LATTICE = 16

# Noise units per lattice cell, i.e. the size of ONE feature of a single octave
# in the shader's `coord` space. Multiply by 1/noise_scale for metres: this is
# the number that turns a desired cloud size into a noise_scale, and it is the
# single most important shape knob there is.
NOISE_FEATURE = NOISE_SIZE / NOISE_LATTICE

# Fixed per-octave offsets, so the octaves never re-align into a grid.
#
# These MUST match OCTAVE_2/3/4_OFFSET in cloud.frag: this module's fbm decides
# where billboards are placed and the shader's decides where the cloud is drawn,
# so if they disagree, billboards land in clear air and clouds go undrawn. A test
# asserts the two agree by reading the shader source.
OCTAVE_OFFSETS = (
    (0.0, 0.0, 0.0),
    (0.31, 0.73, 0.19),
    (-0.57, 0.11, 0.83),
    (0.67, -0.29, 0.41),
)

#: Resolution of the coverage calibration (see :func:`column_peaks`). Measured
#: against an independent high-resolution reference, 96x96 columns by 32 levels
#: lands within 0.3% of the requested coverage across the whole range, with no
#: systematic bias, for about 290 ms per field of build time.
#:
#: 96 rather than a round 128 on purpose. One noise period is NOISE_SIZE/scale
#: metres, so a power-of-two grid puts its columns at an exact multiple of the
#: octave lattice -- at the default cumulus scale, 128 columns is 250 m, precisely
#: octave 16's feature size. That commensurability biases every measurement the
#: same way (+0.4% consistently, against 96's -0.05%), because each column lands
#: on the same phase of the finest octave instead of sampling across it.
COVERAGE_GRID = 96
COVERAGE_LEVELS = 32


# ── Per-type field parameters ──────────────────────────────────────────────────


#: vec4s per cloud type in the layerParams uniform array, and the most types one
#: field may mix.  Must match LAYER_VEC4S / MAX_LAYERS in cloud.frag.
#:
#: A uniform array rather than a texture: a fragment needs two dozen of its
#: type's parameters, which as texelFetches would be two dozen texture reads per
#: pixel, and as varyings would burn most of the interpolator budget.  The layer
#: index is dynamically uniform over a draw, so an indexed uniform read is
#: effectively free.
LAYER_VEC4S = 12
#: Room for a few LOD shells of one type plus another type or two. Shells count as
#: layers, so a 4-shell cumulus deck plus cirrus is already 5.
MAX_LAYERS = 8


@dataclass(frozen=True)
class DensityField:
    """The density field of ONE cloud type: a slab of sky and how it is carved.

    Every field parameter that shapes a cloud lives here, and nothing that
    shapes a cloud lives anywhere else.  Instances are frozen so a field cannot
    be mutated behind the shader's back (the GPU copy is packed once, at build).

    slab            (base_z, thickness) metres — the whole layer's slab, shared
                    by every cloud of this type. NOT per cloud: see the module
                    docstring for why that distinction is load-bearing.
    density         optical density per metre of fully-dense cloud
    noise_scale     world metres → noise coords, PER AXIS. Anisotropy is a real
                    shape tool: stretching X against Z is what turns the same
                    field from cumulus billows into wind-drawn cirrus streaks.
    octave_scales   the four fbm octave frequencies, relative to noise_scale
    octave_weights  the four octave amplitudes (1/f gives the billowy look)
    coverage        the fraction of this type's own slab that is cloud, measured
                    ZENITH-PROJECTED: a column counts if there is cloud at ANY
                    height in the slab. That is the meteorological sense (oktas)
                    and the one you can see, and it is measured PER TYPE against
                    that type's own slab, so a cumulus deck at 0.3 and a cirrus
                    veil at 0.3 each cover three tenths of the sky independently
                    (together they hide 1 - 0.7*0.7 = 0.51 of it, not 0.6).

                    This is the AUTHORED amount of cloud; ``threshold`` below is
                    derived from it. Beware that it is not an independent axis
                    from cloud type: thresholding a 1/f field is a percolation
                    transition, so a low value gives isolated puffs and a high
                    one an overcast sheet with holes. Pushing CUMULUS to 0.9
                    genuinely produces something stratus-like.
    edge_softness   width of the smoothstep window, in standard deviations of
                    this field's own fbm. A NARROW window is the entire source of
                    the crisp cauliflower edge. Expressed in sigma rather than in
                    raw fbm units so that it means the same thing for every type
                    and survives a change of octave weights -- see
                    :func:`fbm_sigma`.
    threshold       (lo, hi) window the fbm is smoothstepped through, DERIVED
                    from coverage and edge_softness; None until resolved.

                    It cannot be authored directly and it cannot be baked into a
                    preset, because which raw fbm value corresponds to a given
                    coverage depends on the noise volume, and that depends on the
                    seed. A field is therefore genuinely incomplete without a
                    volume: call :func:`resolve_field` to fill this in.
    base_ramp       how abruptly density fills in above the slab base, per slab
                    thickness (larger → a flatter, more abrupt cloud base). This
                    scales DENSITY, which is why the underside comes out as a
                    plane — see :func:`base_density`.
    top_erosion     how far the threshold RISES by the top of the slab. This is
                    what makes cumulus tops bulge instead of clipping flat, and
                    it is the one shape parameter whose mechanism differs from
                    every other — see :func:`threshold_lift`.
    top_exponent    the curve of that rise (1 = linear). Above 1 the lift stays
                    small through the lower slab and steepens near the ceiling,
                    which is what lets clouds keep real body while their tops
                    still vary.
    offset          a constant translation in noise coords. This is what makes
                    two types' fields INDEPENDENT while sharing one texture: a
                    translation of a stationary random field is a statistically
                    identical but uncorrelated field, for the cost of an add.
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
        """:returns: the world size in metres, per axis, of this field's LARGEST
        feature — one lattice cell of its lowest octave.  The number to reason
        about when asking "how big will one cloud be?"."""
        return tuple(NOISE_FEATURE / s for s in self.noise_scale)


@dataclass(frozen=True)
class CloudOptics:
    """How light travels through ONE cloud type: the march, and the scattering.

    Split from :class:`DensityField` because the two have different consequences.
    A field parameter changes the SHAPE, which drives where billboards are placed,
    so changing one needs a rebuild.  Everything here is read per fragment and
    affects nothing but shading, so it can be changed live —
    :meth:`CloudField.set_optics` does exactly that, with no rebuild.

    Per TYPE rather than per field because every one of these scales with the
    type's own geometry: a 400 m cirrus sheet and a 2.4 km cumulonimbus tower have
    no business sharing a sun-march step length or an optical-depth cap.

    sun_steps         steps in the per-fragment march toward the sun. This is what
                      makes clouds shadow themselves and each other, and it is the
                      main per-fragment cost; 0 disables self-shadowing.
    sun_step_length   metres per sun-march step. steps x length should span about
                      one cloud's depth, so it belongs to the type.
    shadow_strength   scales the sunward optical depth the march accumulates, i.e.
                      how hard clouds shadow themselves and each other. 1 is the
                      physical value; lower opens up the interiors.
    multiple_scattering
                      SKY-coloured fill for shadowed cloud, standing in for the
                      multiple scattering single scattering cannot represent
                      (0 = pure single scattering, which takes cloud cores to
                      black). Sky-coloured and NOT phase-weighted, both of which
                      matter — see the note in cloud.frag's main().
    powder_strength   how much of the "powder" term to apply (0 disables). Powder
                      is an empirical darkening of optically THIN cloud, from
                      Bouthors et al. via Schneider's Horizon clouds. It patches a
                      known failure of single scattering, which makes thin cloud
                      too bright: it accounts for light removed along the view ray
                      but not for the fact that a thin region has not had room to
                      build the multiple scattering that makes thick cloud glow.
                      The name is the "powdered sugar" observation — a dusted
                      surface looks darker from the direction it is lit.
    powder_length     metres of reference path that turn the LOCAL density into
                      the optical depth the powder term is a function of. Local,
                      because feeding it the sunward depth inverts the term's
                      meaning; and a fixed length rather than the billboard's own
                      chord, or it picks up quad size (see cloud.frag's powder).
    max_optical_depth per-fragment cap: the most any single billboard may
                      contribute. Keeps the accumulation of overlapping
                      billboards smooth — a quad allowed to reach alpha ~1 becomes
                      an opaque hard-edged blob whose own outline shows through
                      the cloud.
    The scattering is parameterised on its OBSERVABLES rather than on lobe
    weights, so the two knobs that matter do not fight each other — see
    :func:`phase_weights` for why the obvious parameterisation could not:

    forward_gain      how much brighter cloud is looking straight INTO the sun
                      than side-on. This is the silver lining, and the number that
                      decides how blinding a view into the sun is. Side-on is 1 by
                      construction, so this is a plain multiple.
    backward_gain     how much brighter cloud is with the sun straight BEHIND you
                      than side-on. Independent of forward_gain: setting either
                      leaves the other exactly where it was.
    forward_anisotropy
                      SHAPE only: the Henyey-Greenstein g of the forward lobe,
                      which sets how fast the gain falls off away from the sun.
                      It cannot change the gains — those are pinned by the solve —
                      so it is safe to adjust independently of both.
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


#: Anisotropy of the phase function's backward lobe. Fixed, unlike the forward
#: one: it is the forward peak that decides how blinding a view into the sun is.
BACKWARD_ANISOTROPY = -0.4

#: Bounds the forward anisotropy. A Henyey-Greenstein g of 1 is a delta spike --
#: the peak diverges as (1-g)^-3, so 0.9 already gives several hundred and
#: anything closer is unusable. Clamped where the weights are solved, and the
#: CLAMPED value is what gets packed, so the shader evaluates the same basis the
#: weights were solved against.
FORWARD_ANISOTROPY_MAX = 0.95

#: Mie asymmetry parameters for cloud particles in the visible, of the kind
#: tabulated by OPAC (Hess et al. 1998). These are SINGLE-SCATTERING values and
#: must not be used directly -- see :func:`delta_eddington`.
MIE_ASYMMETRY_WATER = 0.85
MIE_ASYMMETRY_ICE = 0.80


def delta_eddington(asymmetry: float, applicability: float = 1.0) -> float:
    """The delta-Eddington similarity scaling, ``g -> g / (1 + g)``.

    Why the true Mie asymmetry cannot be used as-is: real cloud droplets scatter
    far more sharply forward than anything a renderer wants.  Water cloud sits
    around g = 0.85 with a forward diffraction peak orders of magnitude tall, and
    feeding that to a SINGLE-scattering shader gives a phase peak that saturates
    the tonemap and washes the whole sunward sky into one flat colour.  Real clouds
    avoid this not because their phase function is gentle but because light
    scatters many times, and the effective phase function after multiple scattering
    is far flatter than the single-scattering one.

    This scaling is the standard way to account for that: it is the similarity
    transformation behind the delta-Eddington approximation, which replaces a
    sharply forward-peaked phase function with a broader equivalent that produces
    the same diffuse radiance field.  For water cloud it gives 0.85 -> 0.46.

    It assumes multiple scattering has run to completion, so it applies in full
    only to optically THICK cloud.  A thin cloud (cirrus, at optical depths near 1)
    is much closer to pure single scattering and keeps most of its raw anisotropy,
    which is what *applicability* is for — and it is why cirrus wants a
    substantially sharper lobe than any of the water-cloud types.

    :param asymmetry: the single-scattering asymmetry parameter g
    :param applicability: how completely the scaling applies — 1 for optically
        thick cloud, 0 for a cloud thin enough to be effectively single-scattering
    :returns: the effective anisotropy to use in a single-scattering shader
    """
    scaled = asymmetry / (1.0 + asymmetry)
    return asymmetry + (scaled - asymmetry) * applicability


def henyey_greenstein(cos_angle, anisotropy: float):
    """The Henyey-Greenstein phase function, matching the shader's ``hgPhase``.

    :param cos_angle: cosine of the angle between the light and the view ray
        (1 = straight toward the light, -1 = straight away)
    :param anisotropy: the lobe's g; positive scatters forward, negative back
    :returns: the phase value, unnormalised
    """
    g = anisotropy
    g2 = g * g
    return 0.25 * (1.0 - g2) * (1.0 + g2 - 2.0 * g * np.asarray(cos_angle)) ** -1.5


def clamped_anisotropy(optics: CloudOptics) -> float:
    """:returns: the forward anisotropy actually used, clamped to a solvable range.

    One function so the solve, the pack and the CPU evaluator cannot disagree about
    which value is in force.

    :param optics: the type's optics
    """
    return min(max(optics.forward_anisotropy, 0.0), FORWARD_ANISOTROPY_MAX)


def phase_weights(optics: CloudOptics):
    """Solve the three lobe weights that hit this type's gains exactly.

    Why a solve at all: the obvious parameterisation — a weight splitting two
    lobes, plus the forward lobe's anisotropy — is COUPLED, and unusably so.  Two
    lobes of fixed shape leave only their weight ratio free, which is one degree
    of freedom for two observables, so the forward and backward brightnesses can
    never be set independently.  Worse, raising the backward weight lowered the
    forward peak AND raising the forward anisotropy raised the backward value
    through the shared normaliser, so every adjustment moved both.

    Adding an ISOTROPIC term supplies the missing degree of freedom, and because
    the phase is linear in the three weights the system is then a 3x3 solve with
    an exact answer.  Pinning the phase at three angles:

        0 degrees   -> forward_gain
        180 degrees -> backward_gain
        90 degrees  -> 1                (the normalisation, now by construction)

    So the gains ARE the observables, exactly and independently, and the shader
    needs no normalising division at all — it is baked into the weights.  The
    anisotropy only reshapes the falloff BETWEEN those three pinned angles, which
    is why it is safe to change without disturbing either gain.

    Nothing is lost by the change of variables: the old two-lobe curve lies in this
    basis's span, so at a matching anisotropy the solve reproduces it exactly with
    a zero isotropic weight.

    :param optics: the type's optics
    :returns: (forward, backward, isotropic) weights
    :raises ValueError: if the gains ask for a phase that goes negative somewhere,
        which would be a black hole in the middle of a cloud
    """
    g = clamped_anisotropy(optics)
    basis = np.array(
        [
            [henyey_greenstein(x, g), henyey_greenstein(x, BACKWARD_ANISOTROPY), 0.25]
            for x in (1.0, -1.0, 0.0)
        ]
    )
    weights = np.linalg.solve(
        basis, np.array([optics.forward_gain, optics.backward_gain, 1.0])
    )
    # A negative phase is not merely unphysical, it renders as a dark hole. Check
    # the whole angular range rather than just the pinned points, since the dip
    # would fall between them.
    sweep = phase_from_weights(weights, g, np.linspace(-1.0, 1.0, 361))
    if sweep.min() < 0.0:
        raise ValueError(
            f"forward_gain={optics.forward_gain} with "
            f"backward_gain={optics.backward_gain} makes the phase function go "
            f"negative ({sweep.min():.3f}) at some angle, which renders as a dark "
            "hole. Move the gains closer together, or raise forward_anisotropy to "
            "concentrate the forward lobe."
        )
    return tuple(float(w) for w in weights)


def phase_from_weights(weights, forward_anisotropy: float, cos_angle):
    """Evaluate the phase function from solved weights, as the shader does.

    :param weights: (forward, backward, isotropic) from :func:`phase_weights`
    :param forward_anisotropy: the g the weights were solved for
    :param cos_angle: cosine of the angle between the sun and the view ray
    :returns: the phase; 1 at 90 degrees by construction
    """
    return (
        weights[0] * henyey_greenstein(cos_angle, forward_anisotropy)
        + weights[1] * henyey_greenstein(cos_angle, BACKWARD_ANISOTROPY)
        + weights[2] * 0.25
    )


def phase(optics: CloudOptics, cos_angle):
    """The phase function the shader uses, evaluated on the CPU.

    :param optics: the type's optics
    :param cos_angle: cosine of the angle between the sun and the view ray
        (1 = straight toward the sun, -1 = straight away)
    :returns: the phase, with side-lit (90 degrees) equal to 1
    """
    return phase_from_weights(
        phase_weights(optics), clamped_anisotropy(optics), cos_angle
    )


def streak_direction(spec: DensityField) -> tuple:
    """The horizontal direction this field's features are LONGEST along.

    Derived from the field rather than authored, and that matters: a stretched
    billboard combing one way while the field streaks another would look combed
    rather than fibrous.  Deriving it guarantees the two agree.

    Axis-aligned, because :attr:`DensityField.noise_scale` is per-axis and so the
    field itself can only stretch along a coordinate axis — there is no diagonal
    to represent.

    :param spec: the type's density field
    :returns: a horizontal unit vector (x, y)
    """
    return (1.0, 0.0) if spec.noise_scale[0] <= spec.noise_scale[1] else (0.0, 1.0)


def field_offset(seed: int) -> tuple:
    """A decorrelating noise-space offset for a cloud type.

    Two types sharing one noise volume would otherwise carve identically wherever
    their octave scales matched.  A translation fixes that at the cost of one
    add, because the volume is stationary and repeat-wrapped: a shifted copy is
    an independent field with identical statistics.

    :param seed: any integer; distinct seeds give uncorrelated fields
    :returns: an (x, y, z) offset in noise coordinates
    """
    rng = np.random.default_rng(0x51EED ^ int(seed))
    # Well over a feature in every axis, so no two types share a lattice cell.
    return tuple(float(v) for v in rng.uniform(0.0, NOISE_SIZE, 3))


# ── The noise volume ───────────────────────────────────────────────────────────


def _axis_weights(size: int, lattice: int):
    """Per-axis lattice indices and smoothstep blend weights for the upsample.

    :param size: output resolution along this axis
    :param lattice: random-lattice resolution along this axis
    :returns: (i0, i1, t) — the two wrapping lattice indices to blend between and
        the smoothstep-shaped blend weight, each of length *size*
    """
    coord = np.arange(size, dtype=np.float64) * (lattice / size)
    i0 = np.floor(coord).astype(np.int64) % lattice
    frac = coord - np.floor(coord)
    # Smoothstep, so the upsampled field is C1 across lattice boundaries. This
    # matters: hardware FT_linear on a raw lattice leaves visible creases, and
    # the shader's threshold window is only 0.05 wide, which would show every one.
    return i0, (i0 + 1) % lattice, (frac * frac * (3.0 - 2.0 * frac)).astype(np.float32)


def value_noise_volume(
    size: int = NOISE_SIZE, lattice: int = NOISE_LATTICE, seed: int = 0
) -> np.ndarray:
    """Generate one tileable octave of 3D value noise, normalised to [0,1].

    Value noise (a random lattice, smoothly interpolated) rather than Perlin:
    the reference shader uses value noise, and the fbm's low octaves are what
    carry the cloud formations, so the lattice's blobbiness is the feature.

    Tiles exactly, because the lattice index wraps and *size* is a whole multiple
    of *lattice*: sampling at index *size* lands back on index 0.

    :param size: output resolution per axis
    :param lattice: random-lattice resolution per axis (must divide *size*)
    :param seed: RNG seed
    :returns: (size, size, size) float32 array in [0,1], indexed [z, y, x]
    """
    if size % lattice != 0:
        raise ValueError(f"size {size} must be a whole multiple of lattice {lattice}")

    rng = np.random.default_rng(seed)
    grid = rng.random((lattice, lattice, lattice), dtype=np.float32)

    z0, z1, tz = _axis_weights(size, lattice)
    y0, y1, ty = _axis_weights(size, lattice)
    x0, x1, tx = _axis_weights(size, lattice)

    def corner(zi, yi, xi):
        return grid[np.ix_(zi, yi, xi)]

    # Trilinear blend, innermost axis first, so each lerp halves the work.
    tx_ = tx[None, None, :]
    ty_ = ty[None, :, None]
    tz_ = tz[:, None, None]
    c00 = corner(z0, y0, x0) + (corner(z0, y0, x1) - corner(z0, y0, x0)) * tx_
    c01 = corner(z0, y1, x0) + (corner(z0, y1, x1) - corner(z0, y1, x0)) * tx_
    c10 = corner(z1, y0, x0) + (corner(z1, y0, x1) - corner(z1, y0, x0)) * tx_
    c11 = corner(z1, y1, x0) + (corner(z1, y1, x1) - corner(z1, y1, x0)) * tx_
    c0 = c00 + (c01 - c00) * ty_
    c1 = c10 + (c11 - c10) * ty_
    volume = c0 + (c1 - c0) * tz_

    # Rescale to actually span [0,1]. This matters twice over: the shader's
    # threshold window is absolute, and the volume is quantised to 8 bits on
    # upload, so any unused range is thrown-away precision.
    lo, hi = float(volume.min()), float(volume.max())
    return ((volume - lo) / max(hi - lo, 1e-9)).astype(np.float32)


def quantise(volume: np.ndarray) -> np.ndarray:
    """Round a volume to the 8 bits per texel the GPU copy actually stores.

    The CPU evaluator must agree with the shader to within the threshold window,
    and 8-bit quantisation is a 1/255 = 0.004 error against a 0.05-wide window —
    small, but free to eliminate, and eliminating it means placement and drawing
    cannot drift apart at the silhouette.

    :param volume: a float volume in [0,1]
    :returns: the same volume as the GPU will see it
    """
    return (np.round(volume * 255.0) / 255.0).astype(np.float32)


def build_noise_texture(
    size: int = NOISE_SIZE, lattice: int = NOISE_LATTICE, seed: int = 0
) -> Texture:
    """Generate the density-field octave and wrap it in a Panda3D 3D texture.

    Needs no graphics context, so it is safe to build headlessly.

    :param size: volume resolution per axis
    :param lattice: random-lattice resolution per axis
    :param seed: RNG seed
    :returns: a repeat-wrapped, linearly filtered single-channel 3D Texture
    """
    volume = value_noise_volume(size, lattice, seed)
    texture = Texture("cloud_noise")
    texture.setup_3d_texture(size, size, size, Texture.T_unsigned_byte, Texture.F_red)
    # Single channel, so there is no BGRA channel-order ambiguity to get wrong.
    # A 3D RAM image is page-major, which is exactly numpy's [z, y, x] order.
    texture.set_ram_image(
        np.ascontiguousarray(np.round(volume * 255.0), np.uint8).tobytes()
    )
    for set_wrap in (texture.set_wrap_u, texture.set_wrap_v, texture.set_wrap_w):
        set_wrap(Texture.WM_repeat)
    texture.set_magfilter(SamplerState.FT_linear)
    # Deliberately NOT mipmapped: a 3D mip chain averages the fbm's 16x octave
    # away to a constant, which is precisely the detail this volume exists for.
    texture.set_minfilter(SamplerState.FT_linear)
    return texture


# ── The field, evaluated on the CPU exactly as the shader evaluates it ─────────


def sample_volume(volume: np.ndarray, coords: np.ndarray) -> np.ndarray:
    """Sample *volume* the way the GPU does: trilinear, repeat-wrapped.

    Reproduces ``texture(cloudNoise, coord / NOISE_SIZE)`` exactly, including the
    half-texel offset a hardware linear fetch applies (texture coordinate u
    addresses texel centre u*size - 0.5).  Getting that half-texel wrong would
    displace placement from drawing by half a texel — 30 m at the scales in use.

    :param volume: (n, n, n) float array indexed [z, y, x]
    :param coords: (..., 3) sample positions in the shader's noise-coord space
    :returns: (...) sampled values
    """
    size = volume.shape[0]
    coords = np.asarray(coords, dtype=np.float64)
    texel = coords - 0.5  # hardware linear addresses texel centres
    base = np.floor(texel)
    frac = texel - base
    i0 = base.astype(np.int64) % size
    i1 = (i0 + 1) % size
    # [..., 0] is x, [..., 2] is z; the volume is indexed [z, y, x].
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
    """The four-octave fbm the shader's ``cloudFbm`` computes.

    :param volume: the noise octave, as returned by :func:`value_noise_volume`
    :param coords: (..., 3) positions in noise coords (world * noise_scale + offset)
    :param spec: the field whose octave scales and weights to use
    :returns: (...) fbm values, in roughly [0, sum(octave_weights)]
    """
    total = np.zeros(np.shape(coords)[:-1], dtype=np.float64)
    for scale, weight, offset in zip(
        spec.octave_scales, spec.octave_weights, OCTAVE_OFFSETS
    ):
        total += sample_volume(volume, coords * scale + np.asarray(offset)) * weight
    return total


def slab_height(spec: DensityField, z: np.ndarray) -> np.ndarray:
    """:returns: normalised height in the type's slab, 0 at the base, 1 at the
    ceiling (unclamped, so callers can test for being outside it).

    Normalised, so every vertical parameter is "per slab" rather than per metre
    and a type keeps its shape whatever its vertical extent.

    :param spec: the field whose slab to measure against
    :param z: world altitudes in metres
    """
    base, thickness = spec.slab
    return (np.asarray(z, dtype=np.float64) - base) / max(thickness, 1e-3)


def base_density(spec: DensityField, h: np.ndarray) -> np.ndarray:
    """How much of full density has filled in at normalised height *h*.

    This is the FLAT BASE, and it works by scaling density: a cumulus has a flat
    underside because condensation begins at one altitude across the whole deck,
    so a multiplier that ramps up from the base is exactly the right model.

    :param spec: the field whose base ramp rate to use
    :param h: normalised slab height
    :returns: a multiplier in [0, 1]
    """
    return 1.0 - np.exp2(-spec.base_ramp * np.asarray(h, dtype=np.float64))


def threshold_lift(spec: DensityField, h: np.ndarray) -> np.ndarray:
    """How much the density threshold has risen by normalised height *h*.

    This is the CAULIFLOWER TOP, and it is the one place the field's vertical
    shaping works on the THRESHOLD rather than on density — which is the whole
    reason the tops bulge.

    Scaling density toward zero can only ever fade a ceiling, never shape one:
    the silhouette's top then sits wherever the multiplier reaches zero, which is
    the same altitude everywhere, and the clouds read as sliced off against a
    plane however gently the fade is done. Raising the threshold instead puts the
    boundary where the field crosses a rising bar, so a column whose field value
    is high keeps clearing it and towers while a weak column stops short. The top
    surface follows the field, and the physical story matches: how high a parcel
    rises depends on how strong the updraft is there.

    It also bounds the slab for free. Once the lift carries the threshold past the
    fbm's maximum, nothing can be cloud — so there is no hard clamp doing that job
    and nothing to see at the ceiling.

    :param spec: the field whose erosion strength and curve to use
    :param h: normalised slab height
    :returns: the amount to add to both ends of the threshold window
    """
    return spec.top_erosion * np.clip(h, 0.0, 1.0) ** spec.top_exponent


def fbm_sigma(volume: np.ndarray, spec: DensityField) -> float:
    """Standard deviation of this field's four-octave fbm.

    The unit ``edge_softness`` is expressed in.  Treating the octaves as
    independent samples of the volume, the weighted sum's variance is the sum of
    the squared weights times the octave's own variance, so this needs only one
    measurement of the volume however the weights are set.

    Why it matters that this is derived: the octave weights are a SHAPE decision,
    but they also move the field's mean and spread.  Authoring the window in raw
    fbm units therefore coupled the two, and retuning the weights silently changed
    how crisp every edge was.

    :param volume: the noise octave, as returned by :func:`value_noise_volume`
    :param spec: the field whose octave weights to use
    :returns: the fbm's standard deviation, in raw fbm units
    """
    weights = np.asarray(spec.octave_weights, dtype=np.float64)
    return float(volume.std() * np.sqrt((weights**2).sum()))


def column_peaks(
    volume: np.ndarray,
    spec: DensityField,
    grid: int = COVERAGE_GRID,
    levels: int = COVERAGE_LEVELS,
) -> np.ndarray:
    """The per-column peak field strength, SORTED ascending.

    This is the statistic that makes coverage exactly invertible.  A column at
    (x, y) contains cloud precisely when

        max over z of [ fbm(x, y, z) - threshold_lift(z) ]  >  threshold_lo

    so the sorted array of those maxima IS the inverse of the coverage function:
    the (1 - coverage) quantile of it is the threshold that yields that coverage,
    read off directly with no solver and no iteration.

    The reduction is only this clean because of how the vertical shaping is split.
    ``top_erosion`` acts on the THRESHOLD, so it moves to the left-hand side as a
    per-height offset; ``base_ramp`` acts on DENSITY, so it changes how dense a
    column is but never whether it is cloud, and drops out entirely.  Had the
    tops been shaped by fading density instead, none of this would separate.

    Sampled on a regular half-offset grid spanning one full noise PERIOD, which
    is the whole population rather than a window of it (the field is toroidal
    there, since the octave scales are integers).  A grid rather than random
    points because it is stratified -- lower error for a smooth field -- and
    because it needs no seed, so the calibration is deterministic.

    :param volume: the noise octave (quantised, to match the GPU copy)
    :param spec: the field to measure; its ``threshold`` is NOT used
    :param grid: columns per horizontal axis
    :param levels: samples through the slab.  Under-sampling here biases coverage
        DOWN, by missing the peak of a thin feature, so this must resolve the
        finest octave: at the default cumulus scale octave 16's features are 250 m
        against a 600 m slab, which 48 levels over-resolves comfortably.
    :returns: (grid*grid,) sorted peak values, in raw fbm units
    """
    base, thickness = spec.slab
    # Half-offset cell centres: one period, and never landing exactly on the
    # noise lattice.
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
    """Read the threshold window off an already-measured peak distribution.

    Split out from :func:`threshold_for_coverage` because the peaks cost a grid
    evaluation to measure but never change, while coverage is a knob: caching the
    sorted array turns a coverage change into an array index, which is what lets
    it be swept live instead of forcing a rebuild.

    :param peaks: sorted per-column peaks, from :func:`column_peaks`
    :param coverage: the fraction of columns that should be cloud
    :param edge_softness: window width, in standard deviations
    :param sigma: the field's fbm standard deviation (see :func:`fbm_sigma`)
    :returns: (lo, hi) in raw fbm units
    """
    width = float(edge_softness) * float(sigma)
    # The endpoints are exact rather than quantiles: a quantile at 0 or 1 lands ON
    # an observed peak, and the test is strict, so "everything" would leave the
    # single strongest column out and "nothing" would let it through.
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


def threshold_for_coverage(volume: np.ndarray, spec: DensityField) -> tuple:
    """The (lo, hi) window that gives *spec* its requested coverage.

    :param volume: the noise octave (quantised, to match the GPU copy)
    :param spec: the field whose coverage and edge_softness to solve for
    :returns: (lo, hi) in raw fbm units
    """
    return threshold_from_peaks(
        column_peaks(volume, spec),
        spec.coverage,
        spec.edge_softness,
        fbm_sigma(volume, spec),
    )


def resolve_field(volume: np.ndarray, spec: DensityField) -> DensityField:
    """Fill in a field's derived ``threshold`` so it can be drawn and placed.

    :param volume: the noise octave (quantised, to match the GPU copy)
    :param spec: the field to resolve
    :returns: a copy with ``threshold`` set
    """
    return replace(spec, threshold=threshold_for_coverage(volume, spec))


def measure_coverage(volume: np.ndarray, spec: DensityField) -> float:
    """Coverage a RESOLVED field actually achieves, measured the same way.

    The round trip that makes the knob trustworthy: this should return what was
    asked for, and it is what the tests assert.

    :param volume: the noise octave (quantised, to match the GPU copy)
    :param spec: a resolved field (see :func:`resolve_field`)
    :returns: the zenith-projected cloud fraction of its slab
    """
    _require_resolved(spec)
    return float((column_peaks(volume, spec) > spec.threshold[0]).mean())


def _require_resolved(spec: DensityField):
    """Guard the CPU/GPU field functions against an unresolved field.

    Fails loudly, because the alternative is silent: a None threshold would
    propagate into the packed uniforms as a TypeError far from the cause, or
    worse, be quietly read as zero and make the whole slab solid cloud.

    :param spec: the field to check
    :raises ValueError: if the field's threshold has not been resolved
    """
    if spec.threshold is None:
        raise ValueError(
            "this DensityField's threshold is still derived-but-unresolved; call "
            "noise.resolve_field(volume, spec) first (the threshold for a given "
            "coverage depends on the noise volume, so a field alone cannot know it)"
        )


def density(volume: np.ndarray, spec: DensityField, points: np.ndarray) -> np.ndarray:
    """The shader's ``cloudDensity``, evaluated on the CPU.

    This is the same function the fragment shader computes, and it exists so that
    billboard PLACEMENT can be driven by the very field that will be DRAWN (see
    cloud.py).  Any disagreement between the two shows up directly as billboards
    in clear air, or as cloud the field wants but no billboard covers.

    The vertical shaping is deliberately two different mechanisms — see
    :func:`base_density` for the flat bottom and :func:`threshold_lift` for the
    bulging top.

    :param volume: the noise octave (pass it through :func:`quantise` to match
        the GPU copy bit for bit)
    :param spec: the cloud type's field
    :param points: (..., 3) world positions in metres
    :returns: (...) density in [0, 1]
    """
    _require_resolved(spec)
    points = np.asarray(points, dtype=np.float64)
    h = slab_height(spec, points[..., 2])
    coords = points * np.asarray(spec.noise_scale) + np.asarray(spec.offset)
    raw = fbm(volume, coords, spec)
    lift = threshold_lift(spec, h)
    lo, hi = spec.threshold[0] + lift, spec.threshold[1] + lift
    t = np.clip((raw - lo) / np.maximum(hi - lo, 1e-9), 0.0, 1.0)
    coverage = t * t * (3.0 - 2.0 * t)
    inside = (h > 0.0) & (h < 1.0)
    return np.where(inside, coverage * base_density(spec, np.clip(h, 0.0, 1.0)), 0.0)


# ── The GPU copy of a field's parameters ───────────────────────────────────────


def shadow_calibration(spec: DensityField, octave_mean: float):
    """Affine correction that makes the 2-octave shadow fbm match the full field.

    The sun march can only afford half the taps, so it sums the two lowest octaves
    — which correlate with the full four-octave field at 0.97 and are therefore a
    fine approximation in SHAPE.  What they are not is calibrated: a plain
    renormalisation by the summed weights leaves the mean AND the spread too high,
    so against the same threshold the march sees 1.65x as much cloud as exists and
    shadows the whole field far too heavily.  That is a bug you see as grey cloud
    tops in full sun, not as a shadow being slightly off.

    The fix is derivable rather than tuned.  Treating the octaves as independent
    samples of the volume (mean m, standard deviation s):

        full field:  mean = m * sum(w),        sd = s * sqrt(sum(w^2))
        two octaves: mean = m * (w0 + w1),     sd = s * sqrt(w0^2 + w1^2)

    so the gain that matches the spreads is the ratio of those square roots, and
    the bias then matches the means.  Both are independent of s, which is why only
    the volume's mean has to be measured.

    :param spec: the field whose octave weights to calibrate for
    :param octave_mean: the mean of the noise volume (see :func:`value_noise_volume`)
    :returns: (gain, bias) to apply as ``gain * raw_two_octave_sum + bias``
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
    optics: CloudOptics = None,
    aspect: float = 1.0,
    fade_in: tuple = None,
    fade_out: tuple = None,
):
    """Flatten one type's field into its six vec4s of the layerParams array.

    The grouping here IS the contract with cloud.frag's LAYER_* accessors; change
    one and you must change the other.

    :param spec: the cloud type's field
    :param extinction: the per-BILLBOARD extinction, i.e. spec.density scaled up
        by 1/(volume fraction) so that a sum over billboard chords integrates to
        spec.density per metre (see cloud.volume_fraction)
    :param wrap_radius: half-width of this type's toroidal recycle box, metres
    :param wrap_fade_band: metres of fade at the box face (0 when the box is a
        whole number of noise periods, since the recycle is then invisible)
    :param octave_mean: mean of the noise volume, for the shadow march's
        calibration (see :func:`shadow_calibration`)
    :param optics: the type's :class:`CloudOptics` (defaults to the class's own
        defaults)
    :param aspect: billboard long:short axis ratio (1 = square). The stretch is
        AREA-PRESERVING, so this needs no change to the extinction calibration —
        see :attr:`cloud.CloudSpec.aspect`.
    :param fade_in: (lo, hi) camera distances this layer fades IN over, or None
        for a layer that is present from the camera outward
    :param fade_out: (lo, hi) camera distances it fades OUT over, or None for the
        outermost layer, which the horizon haze takes to sky instead. Adjacent LOD
        shells share a band — one's fade_out is the next one's fade_in — so their
        weights sum to exactly 1 there (see field.lod_shells).
    :returns: a (LAYER_VEC4S, 4) float32 array
    """
    _require_resolved(spec)
    optics = optics if optics is not None else CloudOptics()
    rows = np.zeros((LAYER_VEC4S, 4), dtype=np.float32)
    rows[0] = (*spec.noise_scale, spec.threshold[0])
    rows[1] = spec.octave_scales
    rows[2] = spec.octave_weights
    rows[3] = (*spec.offset, spec.threshold[1])
    rows[4] = (spec.slab[0], spec.slab[1], spec.base_ramp, spec.top_erosion)
    # The second extinction is the FIELD's, for the sun march. Distinct from the
    # per-billboard one: the march is a continuous path integral, not a sum over
    # chords, so scaling it by 1/(volume fraction) over-counts and drives every
    # fragment into full shadow -- which once made the clouds render unlit.
    rows[5] = (extinction, spec.density, wrap_radius, wrap_fade_band)
    gain, bias = shadow_calibration(spec, octave_mean)
    rows[6] = (spec.top_exponent, gain, bias, optics.max_optical_depth)
    rows[7] = (
        optics.sun_steps,
        optics.sun_step_length,
        optics.shadow_strength,
        optics.multiple_scattering,
    )
    forward, backward, isotropic = phase_weights(optics)
    rows[8] = (optics.powder_strength, optics.powder_length, forward, backward)
    # The CLAMPED anisotropy, matching what the weights were solved against. Packing
    # the raw value would have the shader evaluate a different basis than the solve
    # used, so the gains would come out wrong for any out-of-range setting.
    rows[9] = (isotropic, clamped_anisotropy(optics), 0.0, 0.0)  # .zw spare
    # Billboard shape. The streak direction is derived from the field so the two
    # cannot comb in different directions.
    rows[10] = (aspect, *streak_direction(spec), 0.0)  # .w spare
    # LOD shell crossfade. The "no fade" sentinels are chosen so the shader's two
    # smoothsteps degenerate to 1 without a branch: a fade_in below zero is already
    # complete at any real distance, and a fade_out past the far plane never
    # starts. Equal edges would make smoothstep undefined, hence the offsets.
    rows[11] = (
        *(fade_in if fade_in is not None else (-1.0, 0.0)),
        *(fade_out if fade_out is not None else (1e9, 2e9)),
    )
    return rows
