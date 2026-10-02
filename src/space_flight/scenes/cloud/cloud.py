"""
cloud.py — Where a cloud type's billboards go (CPU only).

There is no "cloud" object: a cloud type is one density field over a slab of sky
(noise.py), clouds are its features, and a billboard is a marker saying "there is
cloud here, come and sample it". :func:`sample_field_particles` places them by
rejection-sampling the very field the shader draws, so the field alone bounds each
cloud and its crisp edge is the field's edge.

Particles are grouped into spatial CELLS, the units of draw-order sorting and
toroidal recycling (field.py), stored ragged with an offsets table.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import Filename, PNMImage, Texture

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

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class CloudType(Enum):
    CUMULUS = "cumulus"
    STRATUS = "stratus"
    CIRRUS = "cirrus"
    CUMULONIMBUS = "cumulonimbus"


@dataclass(frozen=True)
class CloudSpec:
    """Everything that defines one cloud type.

    field            its :class:`DensityField` — shape; drives placement, so a
                     change needs a rebuild
    optics           its :class:`CloudOptics` — shading only, changeable live
    radius           (min, max) billboard radius, metres; match the finest octave
    volume_fraction  target sphere volume per unit of cloud volume: sets how
                     UNIFORMLY billboards cover the volume, not how opaque it is
                     (extinction is derived from it — see :func:`volume_fraction`)
    aspect           billboard long:short ratio. Area-preserving (sqrt(a) by
                     1/sqrt(a)), so extinction and count are untouched; the long
                     axis follows noise.streak_direction
    """

    field: DensityField
    optics: CloudOptics = CloudOptics()
    radius: tuple = (70.0, 140.0)
    volume_fraction: float = 2.5
    aspect: float = 1.0


# Octave scales stay the integer defaults (1/2/7/16): a recycle shifts an octave of
# scale k by k noise periods, which is seamless only for whole k.
PRESETS = {
    CloudType.CUMULUS: CloudSpec(
        # 2 km isotropic features over a 1 km slab; scattered fair-weather puffs,
        # well below the percolation point.
        field=DensityField(
            slab=(1000.0, 1000.0),
            noise_scale=(0.002, 0.002, 0.002),
            coverage=0.3,
            edge_softness=1.3,
            base_ramp=6.0,
            offset=field_offset(0),
        ),
        optics=CloudOptics(
            shadow_strength=0.3,
            # 8x stays clear of the tonemap's knee; the reference's 24x washes a
            # dusk deck into one flat colour.
            forward_gain=8.0,
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_WATER),
        ),
    ),
    CloudType.STRATUS: CloudSpec(
        # Overcast: a flat-topped sheet with holes, soft-edged.
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
        # Optically thickest: phase washed out, no silver lining to speak of.
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
        # Anisotropy IS the fibrous look: 10 km along X, 1.6 km along Y, 130 m in Z.
        # Unequal horizontal periods mean no seamless recycle (a fade band instead).
        field=DensityField(
            slab=(8000.0, 400.0),
            density=0.008,
            noise_scale=(0.0004, 0.0025, 0.03),
            # A veil over most of the sky that hides almost none of it.
            coverage=0.81,
            edge_softness=0.76,
            base_ramp=3.0,
            top_erosion=0.10,
            top_exponent=2.0,
            offset=field_offset(2),
        ),
        # Thin ice cloud: near single scattering, so it keeps most of its raw
        # anisotropy and lights up strongly around the sun.
        optics=CloudOptics(
            sun_steps=2,
            sun_step_length=120.0,
            shadow_strength=0.6,
            multiple_scattering=0.45,
            powder_strength=0.25,
            powder_length=300.0,
            max_optical_depth=0.8,
            forward_gain=12.0,
            backward_gain=1.1,
            forward_anisotropy=delta_eddington(MIE_ASYMMETRY_ICE, applicability=0.15),
        ),
        radius=(90.0, 200.0),
        volume_fraction=1.5,
        # Gentler than the field's 6.25:1, or the anisotropy is double-counted.
        aspect=3.5,
    ),
    CloudType.CUMULONIMBUS: CloudSpec(
        # Few isolated towers; low erosion over a deep slab flattens into an anvil.
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
        # A long march to reach the near-black base of a storm tower.
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
    ),
}


# ── Quality ────────────────────────────────────────────────────────────────────


class CloudQuality(Enum):
    """How much the clouds are allowed to cost. HIGH is what the presets ship."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"
    ULTRA = "ultra"


#: (billboard-count scale, sun-march-step scale) relative to HIGH. The count is
#: where the frame time is and costs no opacity; the march carries the clouds'
#: form, so it is stepped far more gently.
QUALITY_SCALES = {
    CloudQuality.LOW: (0.25, 4.0 / 9.0),
    CloudQuality.MID: (0.5, 2.0 / 3.0),
    CloudQuality.HIGH: (1.0, 1.0),
    CloudQuality.ULTRA: (2.0, 1.5),
}


def at_quality(spec: CloudSpec, quality: CloudQuality) -> CloudSpec:
    """Rescale one cloud type's COST, leaving its look as nearly alone as possible.

    * The march's REACH (steps x length) is held constant; only its resolution
      changes. A coarser sampling of the same path approximates Beer-Lambert well;
      a shorter path does not.
    * The count changes through the RADIUS, not volume_fraction: at fixed
      volume_fraction the count falls as radius⁻³ (the lod_shells trade). Cutting
      volume_fraction instead strips billboards from cloud fringes and loses
      silhouette (measured -18% vs -8.8% at LOW).

    :returns: a scaled copy (*spec* itself at HIGH)
    :raises KeyError: for an unknown level
    """
    count, march = QUALITY_SCALES[quality]
    if count == 1.0 and march == 1.0:
        return spec
    optics = spec.optics
    # int(x + 0.5), not round(): half-to-even would make a 3-step type lose a step
    # going UP to ULTRA.
    steps = max(1, int(optics.sun_steps * march + 0.5))
    reach = optics.sun_steps * optics.sun_step_length
    return replace(
        spec,
        radius=tuple(r * count ** (-1.0 / 3.0) for r in spec.radius),
        optics=replace(optics, sun_steps=steps, sun_step_length=reach / steps),
    )


# ── Optical calibration ───────────────────────────────────────────────────────


def volume_fraction(radii: np.ndarray, cloud_volume: float) -> float:
    """Sphere volume per unit of cloud volume, phi = (4/3)·π·Σr³ / V.

    A ray crosses n·πr² billboards per metre, each with mean chord 4r/3, so
    ``extinction = field.density / phi`` makes the billboard sum accumulate the
    field's own optical depth per metre, whatever the count and radii. Exact, since
    V comes from the rejection-sampling accept rate. Values above 1 are normal.

    :returns: phi (0 for no billboards or no volume)
    """
    radii = np.asarray(radii, dtype=np.float64)
    if len(radii) == 0 or cloud_volume <= 0.0:
        return 0.0
    return float((4.0 / 3.0 * np.pi) * (radii**3).sum() / cloud_volume)


def snap_to_noise_period(spec: DensityField, requested: float) -> tuple[float, bool]:
    """The largest recycle-box width up to *requested* that recycles seamlessly.

    A box a whole number of noise periods wide teleports cells to bit-identical
    field, so no fade is needed. Impossible for an anisotropic field (two periods),
    and not attempted below one period (the fade band covers it).

    :returns: (width, seamless)
    """
    scale_x, scale_y = spec.noise_scale[0], spec.noise_scale[1]
    if abs(scale_x - scale_y) > 1e-12 or scale_x <= 0.0:
        return float(requested), False
    period = NOISE_SIZE / scale_x
    multiple = int(requested // period)
    if multiple < 1:
        return float(requested), False
    return float(multiple * period), True


# ── Placement ──────────────────────────────────────────────────────────────────


def sample_field_particles(
    spec: CloudSpec,
    volume: np.ndarray,
    domain: float,
    cell_size: float,
    atlas_rects: list,
    seed: int = 0,
    batch: int = 50_000,
) -> dict:
    """Place this type's billboards wherever its density field is non-zero.

    Keeps points on ``density > 0`` rather than in proportion to density: the
    shader already modulates each fragment by density, so weighting placement too
    would double-count and starve the edges. The accept rate measures the cloud
    volume, which is what makes the extinction exact (:func:`volume_fraction`).

    :param volume: the noise octave, already quantised to the GPU's 8 bits
    :param domain: square domain width, metres (see :func:`snap_to_noise_period`)
    :param cell_size: side of one spatial cell, metres
    :param atlas_rects: sprite rects (u, v, du, dv) to draw thickness profiles from
    :param batch: rejection-sampling batch size
    :returns: dict with ``local`` (n,3) offsets from each particle's cell centre,
        ``radii`` (n,), ``uv`` (n,4), ``cell_centres`` (k,3), ``cell_start``
        (k+1,) ragged offsets, ``phi`` and ``cloud_volume``
    """
    rng = np.random.default_rng(seed)
    field = spec.field
    half = domain * 0.5
    base_z, thickness = field.slab
    slab_volume = domain * domain * thickness

    # E[r³] for r uniform on [a,b] is (b⁴-a⁴)/(4(b-a)); the mean CUBE, not the
    # cube of the mean.
    r_lo, r_hi = spec.radius
    mean_r3 = (r_hi**4 - r_lo**4) / (4.0 * (r_hi - r_lo)) if r_hi > r_lo else r_lo**3
    sphere = (4.0 / 3.0) * np.pi * mean_r3

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
        if tried > 500 * batch:  # a runaway guard, not an expected path
            break
    points = np.concatenate(kept)[:target]

    cloud_volume = slab_volume * (accepted / tried)
    radii = rng.uniform(r_lo, r_hi, len(points)).astype(np.float32)
    uv = np.asarray(atlas_rects, dtype=np.float32)[
        rng.integers(len(atlas_rects), size=len(points))
    ]

    # Sorting by flat cell index makes each cell's particles a contiguous slice,
    # which keeps the per-frame ragged re-sort loop-free.
    n_side = max(1, int(round(domain / cell_size)))
    step = domain / n_side
    ix = np.clip(((points[:, 0] + half) / step).astype(np.int64), 0, n_side - 1)
    iy = np.clip(((points[:, 1] + half) / step).astype(np.int64), 0, n_side - 1)
    flat = ix * n_side + iy
    order = np.argsort(flat, kind="stable")
    points, radii, uv, flat = points[order], radii[order], uv[order], flat[order]

    population = np.bincount(flat, minlength=n_side * n_side)
    # Empty cells (over a fifth at cumulus coverage) would still cost a sort rank.
    occupied = np.flatnonzero(population)
    cell_start = np.concatenate([[0], np.cumsum(population[occupied])]).astype(np.int64)
    centres = np.empty((len(occupied), 3), np.float32)
    centres[:, 0] = -half + (occupied // n_side + 0.5) * step
    centres[:, 1] = -half + (occupied % n_side + 0.5) * step
    centres[:, 2] = base_z + 0.5 * thickness

    local = (points - np.repeat(centres, population[occupied], axis=0)).astype(
        np.float32
    )
    return dict(
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


def load_cloud_atlas(game: FlightState) -> tuple[Texture, list]:
    """Load the cloud sprite atlas through the game's asset_manager.

    The sprites are a per-quad THICKNESS profile, not a silhouette: their alpha
    scales how much volume a fragment stands for, while the density field decides
    where the cloud ends.

    :returns: (Texture, rects) with rects a list of (u, v, du, dv)
    """
    return load_atlas(game, ATLAS_PNG, ATLAS_JSON)


def atlas_rects() -> list:
    """:returns: the atlas rects (u, v, du, dv), read from the JSON with no GL."""
    with open(ATLAS_JSON) as handle:
        return [
            (r["u_min"], r["v_min"], r["u_size"], r["v_size"])
            for r in json.load(handle)
        ]


@functools.cache
def atlas_mean_alpha() -> float:
    """Mean sprite alpha over the atlas: the fraction of a billboard's disc that
    carries thickness, which the extinction must be divided by or every cloud comes
    out proportionally see-through. Read from the PNG, so it works headless.
    """
    image = PNMImage()
    if not image.read(Filename.from_os_specific(str(ATLAS_PNG))):
        raise OSError(f"could not read the cloud atlas at {ATLAS_PNG}")
    if not image.has_alpha():
        return 1.0
    width, height = image.get_x_size(), image.get_y_size()
    totals = []
    for u_min, v_min, u_size, v_size in atlas_rects():
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
    return float(np.mean(totals)) if totals else 1.0
