"""
cloud.py — Where a cloud type's billboards go.

This module owns the data side of the clouds (no GPU).  There is no such object
as "a cloud" here, and that is the point: a cloud type is ONE continuous density
field spanning a slab of sky (see noise.py), individual clouds are the features
of that field, and a billboard is simply a marker saying "there is cloud here,
come and sample it".  :func:`sample_field_particles` places those markers by
rejection-sampling the very field the shader will draw.

That is a deliberate reversal of the older design, which built discrete cloud
"templates" -- particles packed into a per-cloud envelope -- and scattered them
about.  Two things forced the change:

  * A cloud's OUTLINE was then wherever its billboards ran out, not where the
    field crossed its threshold, so the silhouette stayed soft over about one
    billboard radius however well the field was tuned.
  * Worse, each cloud carried its own vertical slab, which made density a
    function of WHICH CLOUD you asked as well as of position. Overlapping clouds
    disagreed, and the profile's cut at one cloud's ceiling sliced a flat plane
    through its neighbour -- hard-edged plates and straight-sided holes.

With placement following the field, the field alone bounds the cloud, and the
crisp cauliflower edge is the field's edge.

Particles are grouped into spatial CELLS, which are the units of draw-order
sorting and of toroidal recycling (see field.py).  Cell populations vary with how
much cloud each cell contains and are fixed at build time, so the field stores
them ragged with an offsets table rather than padding every cell to the largest
-- padding to the maximum costs about 3x the vertex memory for this
distribution, and buys nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

import numpy as np
from panda3d.core import Filename, PNMImage

from space_flight.fx import load_atlas
from space_flight.scenes.cloud.noise import (
    MIE_ASYMMETRY_ICE,
    MIE_ASYMMETRY_WATER,
    NOISE_SIZE,
    CloudOptics,
    DensityField,
    delta_eddington,
    density,
    field_offset,
)

# ── Cloud type ──────────────────────────────────────────────────────────────────


class CloudType(Enum):
    CUMULUS = "cumulus"
    STRATUS = "stratus"
    CIRRUS = "cirrus"
    CUMULONIMBUS = "cumulonimbus"


@dataclass(frozen=True)
class CloudSpec:
    """Everything that defines one cloud type.

    The split between the three is by CONSEQUENCE, not by topic:

    field            the type's :class:`DensityField` — its shape. Drives
                     placement, so a change needs a rebuild.
    optics           the type's :class:`CloudOptics` — its sun march and
                     scattering. Read per fragment and affects nothing else, so
                     it can be changed live (:meth:`CloudField.set_optics`).
    radius           (min, max) billboard radius in metres. Match this to the
                     field's FINEST octave: billboards much larger than the
                     smallest feature cannot resolve it, and much smaller are
                     paying fill rate for detail the field does not have.
    volume_fraction  target sphere-volume per unit of cloud volume, which sets
                     how many billboards get placed. It does NOT change how
                     opaque a cloud is (extinction is derived from it — see
                     :func:`volume_fraction`); it controls how UNIFORMLY the
                     volume is covered. Too low and the gaps between billboards
                     show as speckle.
    aspect           billboard long:short axis ratio, 1 for square. Stretching is
                     what lets a fibrous type read as wisps instead of as a line
                     of puffs: it is specifically the ROUNDNESS of a billboard
                     that makes the eye resolve it as a discrete object, so an
                     elongated quad stops being countable even with the same
                     sprite drawn on it.

                     The stretch is AREA-PRESERVING — the long axis grows by
                     sqrt(aspect) and the short one shrinks by the same factor —
                     which is why it needs no optical recalibration at all. A
                     billboard's contribution is (footprint area) x (chord), the
                     chord still comes from ``i_radius``, and sqrt(a) * 1/sqrt(a)
                     is 1, so the footprint is EXACTLY unchanged. Extinction, phi
                     and the billboard count are all untouched by this knob.

                     The long axis follows the field's own streak direction (see
                     noise.streak_direction), not the billboard's local X, or the
                     wisps would swing around as the camera turned.
    """

    field: DensityField
    optics: CloudOptics = CloudOptics()
    radius: tuple = (70.0, 140.0)
    volume_fraction: float = 2.5
    aspect: float = 1.0


# ── Per-type presets ────────────────────────────────────────────────────────────
# One entry per type, and every shape parameter lives inside its DensityField.
# This replaces a table of envelope/tower/anvil/Worley geometry knobs: shape is
# now a property of a field, so it is described the way a field is described.
#
# The octave scales are the reference shader's own 1 / 2 / 7 / 16, and they are
# INTEGERS for a load-bearing reason: the toroidal recycle shifts a cell by a
# whole noise period, and an octave at scale k then shifts by k periods, which is
# seamless only if k is a whole number. A non-integer scale (an earlier version
# used 4.7) puts a discontinuity at every recycle.
PRESETS = {
    CloudType.CUMULUS: CloudSpec(
        # 2 km features, isotropic, over a 1 km slab.
        #
        # Isotropic is the right choice here for a slightly subtle reason. The
        # threshold lift turns HORIZONTAL variation in the field into variation in
        # cloud-top HEIGHT (see noise.threshold_lift), so the size of a
        # cauliflower lobe is set by the horizontal octaves — the vertical scale
        # does not have to be fine to get vertical structure. Making it finer was
        # tried and is worse: it adds a pebbling that competes with the lobes
        # instead of enlarging them.
        #
        # The top_erosion is set past the fbm's measured maximum minus the
        # threshold (0.28), so no column ever clips against the ceiling; the
        # exponent keeps the lift small through the lower slab, so clouds still
        # have body rather than tapering away from the base up.
        field=DensityField(
            slab=(1000.0, 1000.0),
            density=0.03,
            noise_scale=(0.002, 0.002, 0.002),
            # Scattered fair-weather cumulus: well below the percolation point, so
            # the clouds read as separate puffs rather than a broken sheet.
            coverage=0.3,
            edge_softness=1.3,
            base_ramp=6.0,
            top_erosion=0.40,
            top_exponent=3.0,
            offset=field_offset(0),
        ),
        # 4 x 160 m spans about one cloud's depth, which is what the march needs
        # to reach full shadow at the base of a tower.
        optics=CloudOptics(
            sun_steps=4,
            sun_step_length=160.0,
            shadow_strength=0.3,
            multiple_scattering=0.12,
            powder_strength=0.6,
            powder_length=200.0,
            max_optical_depth=1.5,
            # The gains are independent: setting either leaves the other exactly
            # where it was (see noise.phase_weights). 8x is well clear of the
            # tonemap's saturating region, which the reference's own phase settings
            # were not -- those put the peak at 24x, where everything toward the sun
            # clips to one colour and a dusk deck reads as a flat wash.
            forward_gain=8.0,
            backward_gain=1.52,
            # Optically thick water cloud, so the similarity scaling applies in
            # full: 0.85 -> 0.46.
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_WATER),
        ),
        radius=(70.0, 140.0),
        volume_fraction=2.5,
    ),
    CloudType.STRATUS: CloudSpec(
        # Overcast is the same field asked for more of itself: well past the
        # percolation point, so the deck is a connected sheet with holes in it
        # rather than a crowd of clouds. Little erosion — a stratus deck genuinely
        # IS flat-topped, which is the one case where a ceiling is the right
        # answer. The soft edge suits a sheet, whose boundaries are gradual.
        field=DensityField(
            slab=(600.0, 300.0),
            density=0.05,
            noise_scale=(0.0015, 0.0015, 0.006),
            coverage=0.25,
            edge_softness=2,
            base_ramp=8.0,
            top_erosion=0.12,
            top_exponent=2.0,
            offset=field_offset(1),
        ),
        # A 300 m slab needs a short march; and an overcast deck really is dim
        # underneath, so the shadow floor stays low.
        #
        # Optically the THICKEST type here, so multiple scattering has washed the
        # phase function out almost entirely: the similarity scaling applies in
        # full, and the forward gain is low because an overcast sky genuinely has
        # no silver lining to speak of.
        optics=CloudOptics(
            sun_steps=3,
            sun_step_length=90.0,
            multiple_scattering=0.10,
            powder_length=150.0,
            max_optical_depth=1.8,
            forward_gain=2.2,
            backward_gain=1.3,
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_WATER),
        ),
        radius=(90.0, 180.0),
        volume_fraction=2.0,
    ),
    CloudType.CIRRUS: CloudSpec(
        # Anisotropy IS the fibrous look: features 10 km along X, 1.6 km along Y,
        # 130 m in Z. That replaces the old 1-D sinusoidal shear outright, and it
        # comes free — it is three numbers in the coordinate scale.
        #
        # Note the cost: unequal horizontal scales mean unequal noise periods, so
        # this type cannot have a period-snapped recycle box and falls back to a
        # fade band at the box face (see field.py).
        field=DensityField(
            slab=(8000.0, 400.0),
            density=0.008,
            noise_scale=(0.0004, 0.0025, 0.03),
            # A high veil covers most of the sky while hiding almost none of it:
            # coverage is how much sky has cirrus over it, not how opaque that
            # cirrus is -- the thinness lives in `density` and the optics.
            coverage=0.81,
            edge_softness=0.76,
            base_ramp=3.0,
            top_erosion=0.10,
            top_exponent=2.0,
            offset=field_offset(2),
        ),
        # Ice cloud, and thin: it barely shadows itself, so two short steps are
        # plenty and the floor sits high. Strongly forward-scattering, which is
        # why cirrus lights up so brightly around the sun.
        optics=CloudOptics(
            sun_steps=2,
            sun_step_length=120.0,
            shadow_strength=0.6,
            multiple_scattering=0.45,
            powder_strength=0.25,
            powder_length=300.0,
            max_optical_depth=0.8,
            # The one THIN type, and that changes which anisotropy is right. The
            # similarity scaling assumes multiple scattering has run to completion;
            # cirrus sits at optical depths near 1, so it is close to pure single
            # scattering and keeps most of its raw ice anisotropy -- hence an
            # applicability near zero, and a value far above the 0.44 the fully
            # scaled maths would give.
            #
            # Being thin is also why cirrus lights up around the sun far more than
            # cumulus does -- far more forward-scattered light survives to the eye
            # -- so the forward gain is high and the backward one almost absent.
            forward_gain=12.0,
            backward_gain=1.1,
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_ICE, applicability=0.15),
        ),
        radius=(90.0, 200.0),
        volume_fraction=1.5,
        # Deliberately LESS anisotropic than the field's own 6.25:1. The field
        # already supplies the long-scale streaking; the billboard only has to
        # stop fighting it, and matching the field's ratio would double-count the
        # anisotropy into something combed. At 3.5 the quads come out roughly
        # 170-370 m along the streak by 50-110 m across.
        aspect=3.5,
    ),
    CloudType.CUMULONIMBUS: CloudSpec(
        # Tall and rare: a LOW coverage makes for few, isolated towers, and a low
        # erosion over a very deep slab is what keeps density all the way up to
        # the ceiling, so the flattening there reads as an anvil spreading against
        # the tropopause. The one type whose ceiling should be flat.
        #
        # The hardest edge of any type, because a tower's flank against clear sky
        # is genuinely sharp.
        field=DensityField(
            slab=(800.0, 2400.0),
            density=0.04,
            noise_scale=(0.0012, 0.0012, 0.0006),
            coverage=0.15,
            edge_softness=0.38,
            base_ramp=6.0,
            top_erosion=0.08,
            top_exponent=4.0,
            offset=field_offset(3),
        ),
        # A 2.4 km slab: the march has to be long to reach shadow at the base of
        # a storm tower, and those bases genuinely go near-black. Thick water
        # cloud again, so the similarity scaling applies in full; the low forward
        # gain suits a mass dense enough that little gets through it.
        optics=CloudOptics(
            sun_steps=6,
            sun_step_length=320.0,
            multiple_scattering=0.05,
            powder_length=250.0,
            max_optical_depth=2.0,
            forward_gain=2.6,
            backward_gain=1.4,
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_WATER),
        ),
        radius=(90.0, 180.0),
        volume_fraction=2.5,
    ),
}


# ── Quality ────────────────────────────────────────────────────────────────────


class CloudQuality(Enum):
    """How much the clouds are allowed to cost. HIGH is what the presets ship."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"
    ULTRA = "ultra"


#: (billboard-count scale, march-step scale) per level, relative to HIGH.
#:
#: Two knobs, because the cloud's two costs scale differently and only one of them
#: is free of look consequences:
#:
#:   * The BILLBOARD count is where the frame time is, so it takes the full 4x
#:     spread. It costs no OPACITY, because extinction is derived from the
#:     placement's own measured sphere-volume fraction: fewer, bigger billboards
#:     each carry proportionally more extinction, and a view ray accumulates
#:     exactly the same optical depth (see :func:`volume_fraction`).
#:   * The SUN MARCH is not free of consequences: it is what makes clouds shadow
#:     each other and themselves, which is most of what gives them form. So it is
#:     stepped much more gently, by 2/3 a level rather than by half. Halving would
#:     put cumulus at one sample by LOW, which stops being a coarse integral and
#:     starts being a different look.
#:
#: The march's total REACH is preserved as the step count changes (see
#: :func:`at_quality`) -- only its resolution varies.
QUALITY_SCALES = {
    CloudQuality.LOW: (0.25, 4.0 / 9.0),
    CloudQuality.MID: (0.5, 2.0 / 3.0),
    CloudQuality.HIGH: (1.0, 1.0),
    CloudQuality.ULTRA: (2.0, 1.5),
}


def at_quality(spec: CloudSpec, quality: CloudQuality) -> CloudSpec:
    """Rescale one cloud type's COST, leaving its look as nearly alone as possible.

    Both knobs are relative rather than absolute, so a type keeps its own
    character: cirrus marches fewer steps than cumulonimbus at every level, because
    that difference is about the types' geometry, not about quality.

    **The march's reach is held constant** while its resolution changes.
    ``sun_steps * sun_step_length`` is how far sunward the march looks, and for
    cumulus that product is tuned to about one cloud's depth -- what it takes to
    reach full shadow at the base of a tower. Dropping steps alone would shorten
    the reach and wash the self-shadowing out. Beer-Lambert exponentiates the
    integral, so a coarser sampling of the same path approximates it well; a
    shorter path approximates nothing.

    **The count is changed through the RADIUS, not through volume_fraction**,
    which is the non-obvious part. Since ``volume_fraction`` is
    ``(4/3)*pi*n*<r^3>``, holding it constant while scaling the radius makes the
    count fall as the cube -- the same conservation law :func:`~field.lod_shells`
    uses for distance, so quality is simply that trade applied globally instead of
    per shell. A count scale *c* is therefore ``radius * c**(-1/3)``.

    Cutting ``volume_fraction`` instead was the obvious approach and is worse. It
    holds optical depth exactly, but only where billboards still reach: at a
    cloud's FRINGE, where one or two covered the field, removing them removes the
    silhouette rather than thinning it. Measured at LOW, against scaling the radius
    for the same count:

        volume_fraction  silhouette -18.1%   grain 1.57x HIGH
        radius            silhouette  -8.8%   grain 0.90x HIGH

    -- and no cheaper, since at these counts the cost is count-driven rather than
    fill-driven. Keeping volume_fraction fixed also keeps ray overlap fixed, which
    is the quantity that shows as speckle when it gets too low.

    The reason bigger billboards cost so little is worth stating, because it is
    specific to this design: a billboard is not a sprite. Density is evaluated PER
    FRAGMENT from the field, so lateral detail and the silhouette are unaffected by
    how big the quad is. What a bigger radius does coarsen is the CHORD -- one
    billboard stands in for a longer stretch of volume from a single mid-chord
    sample -- so what degrades is resolution along the view ray. That is the thing
    to look for when flying through a cloud at LOW, and it is the same reason ULTRA
    reads better: smaller radii resolve depth structure that HIGH's cannot.

    :param spec: the type's shipped :class:`CloudSpec`
    :param quality: the level to scale to
    :returns: a copy scaled for that level (*spec* itself, if HIGH)
    :raises KeyError: if *quality* is not a known level
    """
    count, march = QUALITY_SCALES[quality]
    if count == 1.0 and march == 1.0:
        return spec
    optics = spec.optics
    # int(x + 0.5) rather than round(), which is half-to-EVEN: round(4.5) is 4, so
    # a 3-step type would lose a step going UP to ULTRA.
    steps = max(1, int(optics.sun_steps * march + 0.5))
    reach = optics.sun_steps * optics.sun_step_length
    return replace(
        spec,
        radius=tuple(r * count ** (-1.0 / 3.0) for r in spec.radius),
        optics=replace(optics, sun_steps=steps, sun_step_length=reach / steps),
    )


# ── Optical calibration ───────────────────────────────────────────────────────


def volume_fraction(radii: np.ndarray, cloud_volume: float) -> float:
    """Sphere volume per unit of cloud volume, for the placement just made.

    This is the number the shader's extinction must be divided by, and it is
    derivable rather than tunable.  Each billboard fragment contributes optical
    depth ``extinction * density * chord``.  Summed along a view ray, the
    expected total is ``extinction * density * phi`` per metre, where phi is
    exactly this quantity (crossings per metre ``n*pi*r^2`` times a sphere's mean
    chord ``4r/3`` gives ``(4/3)*pi*n*<r^3>``).

    So ``extinction = field.density / phi`` makes a ray through a cloud
    accumulate the same optical depth per metre as the reference raymarch's
    ``cloudDensity``, whatever billboard count and radii were used.  Values above
    1 are normal and correct — the billboards overlap, and what matters is the
    volume they sum to, not the volume they fill.

    Measured against the volume the field says is CLOUD, not against a bounding
    box: with placement driven by the field, that volume is known exactly from
    the rejection-sampling accept rate, which makes this exact rather than an
    estimate over an envelope.

    :param radii: (n,) billboard radii in metres
    :param cloud_volume: cubic metres of cloud the billboards were placed in
    :returns: the sphere-volume fraction (> 0)
    """
    radii = np.asarray(radii, dtype=np.float64)
    if len(radii) == 0 or cloud_volume <= 0.0:
        return 0.0
    return float((4.0 / 3.0 * np.pi) * (radii**3).sum() / cloud_volume)


def snap_to_noise_period(spec: DensityField, requested: float):
    """The largest recycle-box width up to *requested* that recycles seamlessly.

    The toroidal recycle teleports a cell by one box width.  If that width is a
    whole multiple of the field's noise period, the cell lands where the field is
    bit-identical, so the teleport is invisible and needs no fade to hide it —
    which removes the fade band's cost of dissolving clouds at the domain edge.

    Only possible when the two horizontal noise scales agree; an anisotropic
    field (cirrus) has two different horizontal periods and cannot have one
    square box that is a whole multiple of both.

    :param spec: the type's density field
    :param requested: the domain width the caller asked for, in metres
    :returns: (width, seamless) — the width to use, and whether it recycles with
        no fade needed
    """
    scale_x, scale_y = spec.noise_scale[0], spec.noise_scale[1]
    if abs(scale_x - scale_y) > 1e-12 or scale_x <= 0.0:
        return float(requested), False
    period = NOISE_SIZE / scale_x
    multiple = int(requested // period)
    if multiple < 1:
        # The caller wants a domain smaller than one period. Honour the request
        # rather than silently quadrupling the particle count; the fade band
        # covers the recycle.
        return float(requested), False
    return float(multiple * period), True


# ── Placement ──────────────────────────────────────────────────────────────────


def sample_field_particles(spec: CloudSpec, *args, **kwargs) -> dict:
    """Place this type's billboards, in one call.

    See :func:`sample_field_particles_iter`, whose parameters and result this
    shares; use the generator form when the cost needs spreading across frames.

    :param spec: the cloud type to place
    :returns: the placement dict
    """
    placed = None
    for step in sample_field_particles_iter(spec, *args, **kwargs):
        placed = step if step is not None else placed
    return placed


def sample_field_particles_iter(
    spec: CloudSpec,
    volume: np.ndarray,
    domain: float,
    cell_size: float,
    atlas_rects: list,
    seed: int = 0,
    batch: int = 50_000,
):
    """Place this type's billboards wherever its density field is non-zero.

    A generator, so a loader can spread the cost across frames: it yields None
    after each rejection-sampling batch (a few hundred thousand field evaluations
    in total for a full-size deck) and finally yields the placement dict.

    Rejection-samples the slab uniformly and keeps the points the field calls
    cloud.  Keeping on ``density > 0`` rather than in proportion to density is
    deliberate: the field's own density already modulates each fragment's optical
    depth, so weighting placement by it as well would double-count and starve the
    cloud's edges of the billboards that draw them.

    The accept rate measures the cloud's volume directly, which is what makes the
    extinction calibration exact (see :func:`volume_fraction`).

    Points are grouped into square cells of *cell_size* in XY, one cell per sort
    segment and per recycle unit.  Populations vary and are returned ragged.

    :param spec: the cloud type to place
    :param volume: the noise octave, already quantised to the GPU's 8 bits
    :param domain: width of the square domain, metres (see
        :func:`snap_to_noise_period`)
    :param cell_size: side of one spatial cell, metres
    :param atlas_rects: sprite rects (u, v, du, dv) to draw thickness profiles from
    :param seed: RNG seed for placement and radii
    :param batch: rejection-sampling batch size, i.e. the granularity the cost
        is spread at
    :yields: None per batch, then a dict with
        ``local`` (n,3) each particle's offset from ITS cell's centre,
        ``radii`` (n,), ``uv`` (n,4), ``cell_centres`` (k,3),
        ``cell_start`` (k+1,) offsets into the particle arrays,
        ``phi`` the achieved sphere-volume fraction, and
        ``cloud_volume`` the cubic metres of cloud the field defines.
    """
    rng = np.random.default_rng(seed)
    field = spec.field
    half = domain * 0.5
    base_z, thickness = field.slab
    slab_volume = domain * domain * thickness

    # How many particles the requested volume fraction needs. E[r^3] for a radius
    # uniform on [a,b] is (b^4-a^4)/(4(b-a)); using the mean CUBE rather than the
    # cube of the mean matters here, since volume goes as the cube.
    r_lo, r_hi = spec.radius
    mean_r3 = (
        (r_hi**4 - r_lo**4) / (4.0 * (r_hi - r_lo)) if r_hi > r_lo else r_lo**3
    )
    sphere = (4.0 / 3.0) * np.pi * mean_r3

    # ── Rejection-sample, tracking the accept rate so the cloud volume (and
    # hence the target count) is measured rather than guessed. ──
    kept, tried, accepted = [], 0, 0
    target = None
    while target is None or accepted < target:
        points = np.empty((batch, 3))
        points[:, 0] = rng.uniform(-half, half, batch)
        points[:, 1] = rng.uniform(-half, half, batch)
        points[:, 2] = rng.uniform(base_z, base_z + thickness, batch)
        inside = points[density(volume, field, points) > 0.0]
        tried += batch
        accepted += len(inside)
        kept.append(inside)
        if target is None:
            rate = accepted / tried
            if rate <= 0.0:
                raise ValueError(
                    f"{spec.field} is empty over its slab: nothing to place. "
                    "The threshold window is probably above the fbm's range."
                )
            target = int(slab_volume * rate * spec.volume_fraction / sphere)
        yield None  # one batch done; let a loader draw a frame
        if tried > 500 * batch:  # a runaway guard, not an expected path
            break
    points = np.concatenate(kept)[:target]

    cloud_volume = slab_volume * (accepted / tried)
    radii = rng.uniform(r_lo, r_hi, len(points)).astype(np.float32)
    uv = np.asarray(atlas_rects, dtype=np.float32)[
        rng.integers(len(atlas_rects), size=len(points))
    ]

    # ── Group into cells. Sorting by flat cell index makes each cell's particles
    # a contiguous slice, which is what lets the per-frame re-sort work on ragged
    # populations without a Python loop over cells. ──
    n_side = max(1, int(round(domain / cell_size)))
    step = domain / n_side
    ix = np.clip(((points[:, 0] + half) / step).astype(np.int64), 0, n_side - 1)
    iy = np.clip(((points[:, 1] + half) / step).astype(np.int64), 0, n_side - 1)
    flat = ix * n_side + iy
    order = np.argsort(flat, kind="stable")
    points, radii, uv, flat = points[order], radii[order], uv[order], flat[order]

    population = np.bincount(flat, minlength=n_side * n_side)
    # Drop empty cells: over a fifth of them are empty at cumulus coverage, and
    # an empty cell would still cost a centroid, a distance and a sort rank.
    occupied = np.flatnonzero(population)
    cell_start = np.concatenate([[0], np.cumsum(population[occupied])]).astype(np.int64)
    centres = np.empty((len(occupied), 3), np.float32)
    centres[:, 0] = -half + (occupied // n_side + 0.5) * step
    centres[:, 1] = -half + (occupied % n_side + 0.5) * step
    centres[:, 2] = base_z + 0.5 * thickness

    local = (points - np.repeat(centres, population[occupied], axis=0)).astype(
        np.float32
    )
    yield dict(
        local=local,
        radii=radii,
        uv=uv,
        cell_centres=centres,
        cell_start=cell_start,
        phi=volume_fraction(radii, cloud_volume),
        cloud_volume=cloud_volume,
    )


# ── Sprite atlas ──────────────────────────────────────────────────────────────

_ASSET_DIR = Path(__file__).parent
ATLAS_PNG = _ASSET_DIR / "cloud_atlas.png"
ATLAS_JSON = _ASSET_DIR / "cloud_atlas.json"


def load_cloud_atlas(game):
    """Load the packaged cloud sprite atlas.

    The sprites are used as a per-quad THICKNESS profile, not as a silhouette:
    their alpha scales how much volume a fragment stands for, while the world
    density field still decides where the cloud ends. That split is what lets the
    atlas cut the billboard count without bringing back per-quad silhouettes.

    Delegates to :func:`space_flight.fx.load_atlas`, so the texture is loaded
    (and cached) through the game's asset_manager like every other particle
    atlas, instead of going straight to the Panda3D loader.

    :param game: the game object (exposes app.asset_manager)
    :returns: (Texture, rects) where rects is a list of (u, v, du, dv) tuples
    """
    return load_atlas(game, ATLAS_PNG, ATLAS_JSON)


def atlas_rects() -> list:
    """Read the atlas rects straight from the packaged JSON, with no GL context.

    :returns: list of (u, v, du, dv) tuples
    """
    with open(ATLAS_JSON) as handle:
        return [
            (r["u_min"], r["v_min"], r["u_size"], r["v_size"])
            for r in json.load(handle)
        ]


_MEAN_ALPHA_CACHE = {}


def atlas_mean_alpha(rects=None) -> float:
    """Mean sprite alpha over the atlas rects, i.e. the fraction of a billboard's
    disc that actually carries thickness.

    This has to be measured, not assumed. The sprites' alpha scales how many
    metres of cloud a fragment stands for, so a mean of (say) 0.4 means every
    billboard delivers 40% of the optical depth its radius implies. Without
    folding that into the extinction, a cloud comes out proportionally
    see-through — which is exactly how it looked before this was accounted for.

    Read straight from the PNG rather than the GPU texture, so it works headless
    and needs no graphics context.

    :param rects: atlas rects (u, v, du, dv); None reads them from the JSON
    :returns: mean alpha in (0, 1]
    """
    if rects is None:
        rects = atlas_rects()
    key = tuple(tuple(rect) for rect in rects)
    if key in _MEAN_ALPHA_CACHE:  # a per-pixel scan; once per process is plenty
        return _MEAN_ALPHA_CACHE[key]
    image = PNMImage()
    if not image.read(Filename.from_os_specific(str(ATLAS_PNG))):
        raise OSError(f"could not read the cloud atlas at {ATLAS_PNG}")
    if not image.has_alpha():
        return 1.0
    width, height = image.get_x_size(), image.get_y_size()
    totals = []
    for u_min, v_min, u_size, v_size in rects:
        # UVs are bottom-left origin; PNMImage rows are top-down.
        x0 = int(round(u_min * width))
        x1 = max(x0 + 1, int(round((u_min + u_size) * width)))
        y0 = int(round((1.0 - v_min - v_size) * height))
        y1 = max(y0 + 1, int(round((1.0 - v_min) * height)))
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        alphas = [image.get_alpha(x, y) for y in range(y0, y1) for x in range(x0, x1)]
        if alphas:
            totals.append(sum(alphas) / len(alphas))
    mean = float(np.mean(totals)) if totals else 1.0
    _MEAN_ALPHA_CACHE[key] = mean
    return mean
