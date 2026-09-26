"""
Unit tests for the cloud density field (space_flight.scenes.cloud.noise).

Pure NumPy plus a Texture object, so these need no window and no GPU context.

Note what these can and cannot cover: they check the volume's statistics and the
properties the shader relies on, but they cannot check the GLSL that samples it.
Panda's Shader.load succeeds with no graphics context, so a shader compile error
passes here and fails only on a real window — the cloud shaders need a run of the
game (or an offscreen GL context) to validate.
"""

import re
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from panda3d.core import SamplerState, Texture

from space_flight import DATAFILES_PATH
from space_flight.scenes.cloud.cloud import PRESETS
from space_flight.scenes.cloud.noise import (
    BACKWARD_ANISOTROPY,
    FORWARD_ANISOTROPY_MAX,
    LAYER_VEC4S,
    MAX_LAYERS,
    NOISE_FEATURE,
    NOISE_LATTICE,
    NOISE_SIZE,
    OCTAVE_OFFSETS,
    CloudOptics,
    DensityField,
    base_density,
    build_noise_texture,
    column_peaks,
    density,
    fbm,
    fbm_sigma,
    field_offset,
    henyey_greenstein,
    measure_coverage,
    pack_layer_params,
    phase,
    phase_weights,
    quantise,
    resolve_field,
    sample_volume,
    shadow_calibration,
    slab_height,
    threshold_from_peaks,
    threshold_lift,
    value_noise_volume,
)


@pytest.fixture(scope="module")
def volume():
    return value_noise_volume()


# ── The volume itself ───────────────────────────────────────────────────────────


def test_volume_shape_and_range(volume):
    assert volume.shape == (NOISE_SIZE, NOISE_SIZE, NOISE_SIZE)
    assert volume.dtype == np.float32
    assert np.isfinite(volume).all()
    # Rescaled to span [0,1]: the shader's threshold window is absolute, so the
    # distribution's position matters, not just its shape. It also means the
    # 8-bit upload wastes no precision.
    assert volume.min() == pytest.approx(0.0, abs=1e-6)
    assert volume.max() == pytest.approx(1.0, abs=1e-6)


def test_volume_is_deterministic_in_its_seed():
    assert np.array_equal(value_noise_volume(seed=5), value_noise_volume(seed=5))
    assert not np.array_equal(value_noise_volume(seed=5), value_noise_volume(seed=6))


def test_volume_tiles_without_a_seam(volume):
    """The volume is repeat-wrapped, so the step across the wrap must be no
    larger than an ordinary interior step — otherwise every tile boundary shows
    as a crease, and the shader's 0.05-wide threshold window would find them."""
    for axis in range(3):
        interior = np.abs(np.diff(volume, axis=axis)).mean()
        seam = np.abs(np.take(volume, 0, axis) - np.take(volume, -1, axis)).mean()
        assert seam <= interior * 1.5, f"seam on axis {axis}: {seam} vs {interior}"


def test_size_must_be_a_multiple_of_the_lattice():
    with pytest.raises(ValueError):
        value_noise_volume(size=64, lattice=15)


def test_volume_varies_enough_to_carve(volume):
    """The fbm's variation must exceed the threshold window, or the smoothstep
    saturates and nothing is carved at all — the failure mode that makes clouds
    render as uniform blobs. A single octave's spread is the headroom the
    four-octave fbm draws on."""
    assert volume.std() > 0.15


def test_quantise_matches_an_eight_bit_upload(volume):
    """The CPU evaluator must agree with the shader, and the GPU copy is 8 bits.
    Quantising here removes the only systematic difference between the two, which
    is what lets placement land exactly on the silhouette the shader draws."""
    quantised = quantise(volume)
    assert np.abs(quantised - volume).max() <= 0.5 / 255.0 + 1e-7
    uploaded = (
        np.frombuffer(build_noise_texture().get_ram_image().get_data(), np.uint8)
        / 255.0
    )
    np.testing.assert_allclose(uploaded.reshape(volume.shape), quantised, atol=1e-7)


# ── Sampling it the way the GPU does ───────────────────────────────────────────


def test_sample_volume_reproduces_texel_centres(volume):
    """A hardware linear fetch addresses texel CENTRES: texture coordinate u maps
    to index u*size - 0.5. Getting that half-texel wrong displaces placement from
    drawing by half a texel, which is tens of metres at the scales in use."""
    # At coord = i + 0.5 the fetch lands exactly on texel i, with no blending.
    index = np.array([[3.5, 7.5, 11.5]])
    np.testing.assert_allclose(
        sample_volume(volume, index), volume[11, 7, 3], rtol=1e-6
    )


def test_sample_volume_wraps(volume):
    """Repeat wrapping, on every axis, exactly as WM_repeat does."""
    coord = np.array([[2.3, 5.7, 9.1]])
    shifted = coord + NOISE_SIZE
    np.testing.assert_allclose(
        sample_volume(volume, coord), sample_volume(volume, shifted), rtol=1e-6
    )


def test_sample_volume_interpolates_between_texels(volume):
    """Halfway between two texel centres must be their mean."""
    got = sample_volume(volume, np.array([[4.0, 7.5, 11.5]]))
    np.testing.assert_allclose(
        got, 0.5 * (volume[11, 7, 3] + volume[11, 7, 4]), rtol=1e-6
    )


# ── Coverage: the authored amount of cloud ─────────────────────────────────────


def test_a_requested_coverage_is_the_coverage_you_get(volume):
    """The knob's whole contract, across the range and for every type.

    Checked against an INDEPENDENT measurement resolution, because measuring with
    the same grid the threshold was solved on is circular — it would agree to
    machine precision however wrong the grid was.
    """
    for cloud_type, cspec in PRESETS.items():
        # Measured once per type, not once per coverage: the peaks do not depend on
        # the requested coverage, only the index into them does.
        solving = column_peaks(volume, cspec.field)
        sigma = fbm_sigma(volume, cspec.field)
        # A different, deliberately non-power-of-two resolution, so agreement
        # cannot come from sharing a grid.
        checking = column_peaks(volume, cspec.field, grid=101, levels=37)
        for want in (0.1, 0.3, 0.6, 0.85):
            lo, _ = threshold_from_peaks(
                solving, want, cspec.field.edge_softness, sigma
            )
            got = float((checking > lo).mean())
            assert got == pytest.approx(want, abs=0.02), (
                f"{cloud_type.value} asked for {want}, an independent measurement "
                f"says {got:.3f}"
            )


def test_coverage_is_monotone_and_exact_at_the_endpoints(volume):
    """Monotone or the knob would be unusable; exact at the ends because a
    quantile lands ON an observed peak there, and the field's test is strict — so
    "everything" would leave the single strongest column out."""
    spec = DensityField(noise_scale=(0.002,) * 3)
    peaks = column_peaks(volume, spec)
    sigma = fbm_sigma(volume, spec)

    def solve(want):
        return threshold_from_peaks(peaks, want, spec.edge_softness, sigma)[0]

    previous = None
    for want in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
        lo = solve(want)
        assert float((peaks > lo).mean()) == pytest.approx(want, abs=0.001)
        if previous is not None:
            assert lo <= previous
        previous = lo
    # Out of range clamps rather than raising or wrapping.
    assert float((peaks > solve(-0.5)).mean()) == pytest.approx(0.0)
    assert float((peaks > solve(1.5)).mean()) == pytest.approx(1.0)


def test_coverage_survives_a_change_of_octave_weights(volume):
    """The coupling this design removes, and the reason coverage is derived rather
    than authored as a raw threshold.

    Octave weights are a SHAPE decision, but they also move the fbm's mean and
    spread. Against a hand-authored threshold, retuning them silently changed how
    much cloud there was — two independent things sharing one number. Deriving the
    threshold from a measurement makes coverage invariant to them.
    """
    spec = DensityField(noise_scale=(0.002,) * 3)
    quieter = replace(spec, octave_weights=(0.5, 0.25, 0.0625, 0.03125))
    base = resolve_field(volume, spec)
    changed = resolve_field(volume, quieter)
    assert measure_coverage(volume, base) == pytest.approx(spec.coverage, abs=0.005)
    assert measure_coverage(volume, changed) == pytest.approx(spec.coverage, abs=0.005)
    # It held coverage fixed by MOVING the threshold, which is the whole mechanism.
    assert abs(changed.threshold[0] - base.threshold[0]) > 0.02


def test_edge_softness_is_measured_in_sigma(volume):
    """Expressed in the field's own spread so it means the same for every type.
    A raw width could not: it would be a hard edge on one field and a mushy one
    on another with a different octave spectrum."""
    spec = DensityField(noise_scale=(0.002,) * 3)
    field = resolve_field(volume, replace(spec, edge_softness=0.5))
    lo, hi = field.threshold
    assert hi - lo == pytest.approx(0.5 * fbm_sigma(volume, field), rel=1e-6)
    # And softness must not disturb the amount of cloud: the window's LOW edge is
    # what coverage is defined against, so widening it must not move coverage.
    wide = resolve_field(volume, replace(spec, edge_softness=2.0))
    assert wide.threshold[0] == pytest.approx(lo, abs=1e-9)
    assert measure_coverage(volume, wide) == pytest.approx(
        measure_coverage(volume, field)
    )


def test_the_peak_statistic_ignores_the_base_ramp_but_not_the_top_erosion(volume):
    """Why the coverage inversion can be exact rather than iterative.

    top_erosion acts on the THRESHOLD, so it moves into the per-column peak as a
    height-dependent offset. base_ramp acts on DENSITY, so it changes how dense a
    column is but never whether it is cloud, and drops out entirely. Had the tops
    been shaped by fading density instead, neither would separate and the whole
    quantile trick would collapse.
    """
    spec = DensityField(noise_scale=(0.002,) * 3)
    base = column_peaks(volume, spec, grid=48, levels=24)
    ramped = column_peaks(volume, replace(spec, base_ramp=1.0), grid=48, levels=24)
    np.testing.assert_allclose(base, ramped)
    eroded = column_peaks(volume, replace(spec, top_erosion=0.8), grid=48, levels=24)
    assert not np.allclose(base, eroded)
    # More erosion can only ever lower a column's peak.
    assert (eroded <= base + 1e-12).all()


def test_an_unresolved_field_is_refused_rather_than_guessed(volume):
    """A preset carries coverage, not a threshold, and cannot know one without a
    volume. Failing loudly beats the alternatives: a None threshold would surface
    as a TypeError deep inside the packing, or be read as zero and make the whole
    slab solid cloud."""
    spec = DensityField()
    assert spec.threshold is None
    points = np.zeros((4, 3))
    with pytest.raises(ValueError, match="unresolved"):
        density(volume, spec, points)
    with pytest.raises(ValueError, match="unresolved"):
        pack_layer_params(spec, extinction=0.05, wrap_radius=1.0, wrap_fade_band=0.0)
    with pytest.raises(ValueError, match="unresolved"):
        measure_coverage(volume, spec)


def test_threshold_from_peaks_needs_no_field_evaluation(volume):
    """What makes coverage sweepable live: the sorted peaks are the exact inverse
    of the coverage function, so a new threshold is an index into them rather than
    a fresh measurement of the field."""
    spec = DensityField(noise_scale=(0.002,) * 3)
    peaks = column_peaks(volume, spec)
    sigma = fbm_sigma(volume, spec)
    for want in (0.2, 0.5, 0.8):
        cheap = threshold_from_peaks(peaks, want, spec.edge_softness, sigma)
        full = resolve_field(volume, replace(spec, coverage=want)).threshold
        assert cheap == pytest.approx(full)


def test_the_peaks_are_sorted_and_deterministic(volume):
    """Sorted because the quantile reads straight off them; deterministic because
    the grid carries no RNG, so a build is repeatable."""
    spec = DensityField(noise_scale=(0.002,) * 3)
    peaks = column_peaks(volume, spec, grid=32, levels=16)
    assert (np.diff(peaks) >= 0).all()
    np.testing.assert_array_equal(peaks, column_peaks(volume, spec, grid=32, levels=16))


# ── The fbm ────────────────────────────────────────────────────────────────────


def test_fbm_octaves_are_offset_so_they_never_align(volume):
    """The lowest octave has no offset; the rest do, or the octaves would
    re-align into a visible grid."""
    assert OCTAVE_OFFSETS[0] == (0.0, 0.0, 0.0)
    assert len(set(OCTAVE_OFFSETS)) == 4


def test_fbm_octave_scales_are_whole_numbers():
    """A cell recycling across the domain shifts by one noise period, and an
    octave at scale k then shifts by k periods — seamless only if k is an
    integer. A non-integer scale puts a discontinuity at every recycle."""
    for spec in (DensityField(),):
        for scale in spec.octave_scales:
            assert scale == int(scale), f"octave scale {scale} is not whole"


def test_fbm_spans_the_threshold_window(volume):
    """The threshold window must sit inside the fbm's actual range, or the field
    is either everywhere or nowhere."""
    spec = resolve_field(volume, DensityField(noise_scale=(0.002,) * 3))
    rng = np.random.default_rng(0)
    points = rng.uniform([-20000, -20000, 1000], [20000, 20000, 1600], (50_000, 3))
    values = fbm(volume, points * np.asarray(spec.noise_scale), spec)
    lo, hi = spec.threshold
    assert values.min() < lo < hi < values.max()
    # And a sane fraction of the sky is cloud: a cumulus deck, not overcast.
    assert 0.05 < (values > hi).mean() < 0.40


def test_the_shadow_march_agrees_with_the_field_it_approximates(volume):
    """The sun march can only afford two octaves, but it must not therefore see a
    DIFFERENT amount of cloud than exists — it is tested against the same
    threshold.

    This was a real bug with a very visible symptom. Renormalising the two octaves
    by their summed weights (the obvious thing, and what this did at first) leaves
    both the mean and the spread too high, so the march found about 1.65x as much
    cloud as the field contains and shadowed everything far too heavily: sunlit
    cloud tops came out grey in full sun. The affine calibration fixes the
    distribution, not just the scale."""
    spec = resolve_field(volume, DensityField(noise_scale=(0.002,) * 3))
    rng = np.random.default_rng(0)
    points = rng.uniform([-16000, -16000, 1000], [16000, 16000, 2000], (60_000, 3))
    coords = points * np.asarray(spec.noise_scale)

    def octave(index):
        return sample_volume(
            volume,
            coords * spec.octave_scales[index] + np.asarray(OCTAVE_OFFSETS[index]),
        )

    full = sum(octave(i) * spec.octave_weights[i] for i in range(4))
    pair = octave(0) * spec.octave_weights[0] + octave(1) * spec.octave_weights[1]

    # The naive renormalisation, for the record: it over-reports badly.
    naive = pair / (spec.octave_weights[0] + spec.octave_weights[1])
    threshold = spec.threshold[0]
    over_report = (naive > threshold).mean() / (full > threshold).mean()
    assert over_report > 1.4, "the naive renormalisation should over-report"

    gain, bias = shadow_calibration(spec, float(volume.mean()))
    calibrated = pair * gain + bias
    # Same mean, same spread, and therefore the same amount of cloud.
    assert calibrated.mean() == pytest.approx(full.mean(), abs=0.01)
    assert calibrated.std() == pytest.approx(full.std(), rel=0.15)
    ratio = (calibrated > threshold).mean() / (full > threshold).mean()
    assert 0.85 < ratio < 1.15, f"the march sees {ratio:.2f}x the cloud it should"
    # Two octaves are a fine approximation in SHAPE; only the calibration was off.
    assert np.corrcoef(full, calibrated)[0, 1] > 0.9


# ── The vertical shaping: two different mechanisms ─────────────────────────────


def test_slab_height_normalises_to_the_slab():
    """Every vertical parameter is "per slab", so a type keeps its shape whatever
    its vertical extent."""
    spec = DensityField(slab=(1000.0, 600.0))
    np.testing.assert_allclose(
        slab_height(spec, np.array([1000.0, 1300.0, 1600.0, 700.0])),
        [0.0, 0.5, 1.0, -0.5],
    )


def test_base_density_ramps_up_from_the_base():
    """The flat bottom, and it works by scaling DENSITY: condensation begins at
    one altitude across the whole deck, so a multiplier is the right model."""
    spec = DensityField(base_ramp=6.0)
    h = np.linspace(0.0, 1.0, 21)
    ramp = base_density(spec, h)
    assert ramp[0] == pytest.approx(0.0)
    assert (np.diff(ramp) > 0).all()  # monotonic
    assert ramp[-1] > 0.98  # fully filled in well before the ceiling
    # Most of the fill happens low in the slab, which is what makes it read flat.
    assert base_density(spec, 0.25) > 0.6


def test_threshold_lift_rises_to_clear_the_fbm_at_the_ceiling():
    """The cauliflower top. Once the lift carries the threshold past the fbm's
    maximum, nothing can be cloud — so the slab bounds itself and no hard clamp
    is doing that job."""
    spec = DensityField(threshold=(0.55, 0.60), top_erosion=0.40, top_exponent=3.0)
    assert threshold_lift(spec, 0.0) == pytest.approx(0.0)
    assert threshold_lift(spec, 1.0) == pytest.approx(0.40)
    # The measured fbm maximum is about 0.83, so the lift must exceed 0.28.
    assert spec.threshold[0] + threshold_lift(spec, 1.0) > 0.83
    # An exponent above 1 keeps the lift small through the lower slab, so clouds
    # keep body instead of tapering away from the base up.
    assert threshold_lift(spec, 0.5) < 0.25 * threshold_lift(spec, 1.0)


def test_the_cloud_top_follows_the_field(volume):
    """The whole point of lifting the threshold, stated as the property it buys.

    Scaling density toward zero can only put the silhouette's top at one altitude
    everywhere — the clouds then read as sliced off against a plane. Raising the
    threshold puts the boundary where the field crosses a rising bar, so how high
    a column reaches is a function of how strong the field is there. That is what
    is asserted: top height tracks field strength, tightly, and no column is
    pinned against the ceiling."""
    base, thickness = 1000.0, 1000.0
    spec = resolve_field(
        volume,
        DensityField(
            slab=(base, thickness),
            noise_scale=(0.002,) * 3,
            top_erosion=0.40,
            top_exponent=3.0,
        ),
    )
    columns = np.linspace(-6000.0, 6000.0, 80)
    gx, gy = np.meshgrid(columns, columns, indexing="ij")

    top = np.full(gx.shape, np.nan)
    for z in np.linspace(base, base + thickness, 60):
        points = np.stack([gx, gy, np.full(gx.shape, z)], axis=-1)
        top = np.where(density(volume, spec, points) > 0.0, z, top)
    cloudy = ~np.isnan(top)
    height = (top[cloudy] - base) / thickness

    # Field strength per column, taken low in the slab where nothing is eroded.
    low = np.stack([gx, gy, np.full(gx.shape, base + 0.15 * thickness)], axis=-1)
    strength = fbm(volume, low * np.asarray(spec.noise_scale), spec)[cloudy]

    # A strong column towers, a weak one stops short. The correlation measures
    # about 0.57 rather than near 1, and that is expected rather than weak: the
    # field varies vertically as well, so how strong a column is DOWN HERE only
    # partly predicts how strong it is where its top ends up. What matters is that
    # this is the dominant effect, which over several thousand columns it plainly
    # is — a threshold that does not vary with height would give zero.
    correlation = np.corrcoef(strength, height)[0, 1]
    assert (
        correlation > 0.45
    ), f"top height barely follows the field ({correlation:.2f})"
    # Nothing is pinned at the ceiling: the lift carries the threshold past the
    # fbm's maximum before the slab runs out, so the slab bounds itself.
    assert height.max() < 0.99
    # And the tops genuinely vary, rather than all landing at one height.
    assert np.percentile(height, 90) - np.percentile(height, 10) > 0.3


def test_the_base_stays_flat_when_the_top_bulges(volume):
    """The base must NOT be eroded along with the top — a cumulus really does
    have a flat underside, and that was the one part already right."""
    spec = resolve_field(
        volume, DensityField(slab=(1000.0, 1000.0), noise_scale=(0.002,) * 3)
    )
    columns = np.linspace(-6000.0, 6000.0, 90)
    gx, gy = np.meshgrid(columns, columns, indexing="ij")
    # Density just above the base is non-zero wherever the column is cloud at
    # all, so the underside sits at one altitude across the whole deck.
    low = density(volume, spec, np.stack([gx, gy, np.full(gx.shape, 1030.0)], -1))
    mid = density(volume, spec, np.stack([gx, gy, np.full(gx.shape, 1300.0)], -1))
    assert (low > 0.0).sum() >= (mid > 0.0).sum()
    # And nothing at all below it.
    below = density(volume, spec, np.stack([gx, gy, np.full(gx.shape, 999.0)], -1))
    assert (below == 0.0).all()


# ── The field as a whole ───────────────────────────────────────────────────────


def test_density_is_a_function_of_world_position_alone(volume):
    """The property the crisp silhouette depends on. Every billboard covering a
    pixel must agree where the cloud's boundary is, which holds only while the
    field depends on position and nothing else. It was broken once, when each
    cloud carried its own slab: overlapping clouds then disagreed, and one
    cloud's ceiling sliced a flat plane through its neighbour."""
    spec = resolve_field(volume, DensityField(noise_scale=(0.002,) * 3))
    points = np.random.default_rng(1).uniform(
        [-8000, -8000, 1000], [8000, 8000, 1600], (2000, 3)
    )
    first = density(volume, spec, points)
    # Same points, asked in a different order and shape: identical answers.
    shuffled = np.random.default_rng(2).permutation(len(points))
    np.testing.assert_array_equal(
        density(volume, spec, points[shuffled]), first[shuffled]
    )
    np.testing.assert_array_equal(
        density(volume, spec, points.reshape(20, 100, 3)).reshape(-1), first
    )


def test_density_is_periodic_at_the_noise_period(volume):
    """What makes toroidal recycling seamless: a cell teleported by one period
    lands where the field is identical."""
    spec = resolve_field(volume, DensityField(noise_scale=(0.002,) * 3))
    period = NOISE_SIZE / spec.noise_scale[0]
    points = np.random.default_rng(3).uniform(
        [-4000, -4000, 1000], [4000, 4000, 1600], (500, 3)
    )
    shifted = points + np.array([period, 0.0, 0.0])
    np.testing.assert_allclose(
        density(volume, spec, points), density(volume, spec, shifted), atol=1e-6
    )


def test_density_is_bounded_and_carves(volume):
    spec = resolve_field(volume, DensityField(noise_scale=(0.002,) * 3))
    points = np.random.default_rng(4).uniform(
        [-20000, -20000, 1000], [20000, 20000, 1600], (50_000, 3)
    )
    values = density(volume, spec, points)
    assert values.min() == 0.0  # clear sky exists
    assert 0.0 < values.max() <= 1.0
    inside = values > 0.0
    # A believable cumulus sky: cloud somewhere, clear sky mostly.
    assert 0.05 < inside.mean() < 0.45


def test_anisotropic_scale_stretches_the_field(volume):
    """Anisotropy IS the fibrous cirrus look — it replaces a sinusoidal shear
    outright, and it costs three numbers in the coordinate scale."""
    stretched = DensityField(
        slab=(1000.0, 600.0), noise_scale=(0.0004, 0.0025, 0.002), threshold=(0.5, 0.55)
    )
    # Along the stretched axis the field varies far more slowly.
    x = np.stack(
        [np.arange(0, 6000, 50.0), np.zeros(120), np.full(120, 1250.0)], axis=1
    )
    y = np.stack(
        [np.zeros(120), np.arange(0, 6000, 50.0), np.full(120, 1250.0)], axis=1
    )
    along = np.abs(np.diff(density(volume, stretched, x))).mean()
    across = np.abs(np.diff(density(volume, stretched, y))).mean()
    assert across > 2.0 * along


def test_feature_size_converts_scale_to_metres():
    """The number to reason about when asking how big one cloud will be."""
    spec = DensityField(noise_scale=(0.002, 0.004, 0.008))
    np.testing.assert_allclose(
        spec.feature_size,
        (NOISE_FEATURE / 0.002, NOISE_FEATURE / 0.004, NOISE_FEATURE / 0.008),
    )


def test_field_offsets_are_distinct_and_deterministic():
    """Two types sharing one noise volume must not carve identically."""
    assert field_offset(0) == field_offset(0)
    assert field_offset(0) != field_offset(1)
    assert all(0.0 <= v <= NOISE_SIZE for v in field_offset(3))


# ── The GPU copy of a field ────────────────────────────────────────────────────


def test_pack_layer_params_round_trips_the_field():
    """This packing IS the contract with cloud.frag's accessors."""
    spec = DensityField(
        slab=(1234.0, 567.0),
        density=0.037,
        noise_scale=(0.001, 0.002, 0.003),
        octave_scales=(1.0, 2.0, 7.0, 16.0),
        octave_weights=(0.5, 0.25, 0.125, 0.0625),
        threshold=(0.51, 0.58),
        base_ramp=4.5,
        top_erosion=0.37,
        top_exponent=2.5,
        offset=(11.0, 22.0, 33.0),
    )
    rows = pack_layer_params(
        spec, extinction=0.09, wrap_radius=8000.0, wrap_fade_band=0.0
    )
    assert rows.shape == (LAYER_VEC4S, 4)
    np.testing.assert_allclose(rows[0], (0.001, 0.002, 0.003, 0.51))
    np.testing.assert_allclose(rows[1], spec.octave_scales)
    np.testing.assert_allclose(rows[2], spec.octave_weights)
    np.testing.assert_allclose(rows[3], (11.0, 22.0, 33.0, 0.58))
    np.testing.assert_allclose(rows[4], (1234.0, 567.0, 4.5, 0.37))
    gain, bias = shadow_calibration(spec, 0.5)
    np.testing.assert_allclose(
        rows[6], (2.5, gain, bias, CloudOptics().max_optical_depth), rtol=1e-6
    )
    # The two extinctions are DIFFERENT numbers on purpose: the per-billboard one
    # is scaled by 1/(volume fraction) for a sum over chords, while the sun march
    # is a continuous path integral and must use the field's own density.
    np.testing.assert_allclose(rows[5], (0.09, 0.037, 8000.0, 0.0))


def test_pack_layer_params_carries_the_types_optics():
    """Optics are per cloud TYPE, because every one of them scales with the type's
    own geometry — a 400 m cirrus sheet and a 2.4 km tower have no business
    sharing a march length or an optical-depth cap."""
    optics = CloudOptics(
        sun_steps=6,
        sun_step_length=320.0,
        shadow_strength=0.7,
        multiple_scattering=0.08,
        powder_strength=0.4,
        powder_length=250.0,
        max_optical_depth=2.0,
        forward_gain=6.0,
        backward_gain=1.3,
        forward_anisotropy=0.55,
    )
    rows = pack_layer_params(
        # Any resolved window will do: this test is about the optics rows.
        DensityField(threshold=(0.55, 0.60)),
        extinction=0.05,
        wrap_radius=1000.0,
        wrap_fade_band=0.0,
        optics=optics,
    )
    assert rows[6][3] == pytest.approx(2.0)  # max_optical_depth
    np.testing.assert_allclose(rows[7], (6.0, 320.0, 0.7, 0.08))
    # Rows 8-9 carry the PRE-SOLVED phase weights, not the gains themselves: the
    # shader evaluates the basis and needs no normalising divide.
    forward, backward, isotropic = phase_weights(optics)
    np.testing.assert_allclose(rows[8], (0.4, 250.0, forward, backward), rtol=1e-6)
    np.testing.assert_allclose(rows[9], (isotropic, 0.55, 0.0, 0.0), rtol=1e-6)


# ── The phase function ─────────────────────────────────────────────────────────


ANGLES = np.linspace(-1.0, 1.0, 361)


def test_the_gains_are_exactly_the_observables():
    """The whole point of the change of variables: what you set IS what you see.
    Side-lit is 1 by construction, which is also the normalisation — so
    sun_brightness always means the same thing."""
    for forward in (1.0, 2.5, 4.72, 12.0):
        for backward in (0.5, 1.0, 1.52, 3.0):
            optics = CloudOptics(forward_gain=forward, backward_gain=backward)
            assert phase(optics, 1.0) == pytest.approx(forward)
            assert phase(optics, -1.0) == pytest.approx(backward)
            assert phase(optics, 0.0) == pytest.approx(1.0)


def test_the_gains_are_independent_of_each_other():
    """The reason for the reparameterisation. In the old two-lobe form these were
    coupled: raising the backward weight lowered the forward peak, and raising the
    forward anisotropy raised the backward value through the shared normaliser, so
    every adjustment moved both and tuning was a two-variable dance."""
    for backward in (0.5, 1.52, 3.0):
        forward_values = [
            phase(CloudOptics(forward_gain=f, backward_gain=backward), -1.0)
            for f in (1.0, 5.0, 15.0)
        ]
        # Sweeping the forward gain leaves the backward observable untouched.
        assert all(v == pytest.approx(backward) for v in forward_values)
    for forward in (1.0, 4.72, 15.0):
        backward_values = [
            phase(CloudOptics(forward_gain=forward, backward_gain=b), 1.0)
            for b in (0.5, 1.52, 3.0)
        ]
        assert all(v == pytest.approx(forward) for v in backward_values)


def test_the_anisotropy_is_shape_only():
    """It reshapes the falloff BETWEEN the pinned angles, and cannot move the gains
    — so it is safe to adjust without re-tuning either."""
    gains = dict(forward_gain=4.72, backward_gain=1.52)
    for g in (0.2, 0.4, 0.6, 0.8):
        optics = CloudOptics(**gains, forward_anisotropy=g)
        assert phase(optics, 1.0) == pytest.approx(4.72)
        assert phase(optics, -1.0) == pytest.approx(1.52)
        assert phase(optics, 0.0) == pytest.approx(1.0)
    # But it does change the mid-angles, or it would be no knob at all.
    narrow = phase(CloudOptics(**gains, forward_anisotropy=0.8), 0.707)
    broad = phase(CloudOptics(**gains, forward_anisotropy=0.2), 0.707)
    assert broad > narrow * 1.3


def test_the_reparameterisation_is_lossless():
    """The old two-lobe curve lies in the new basis's span, so at a matching
    anisotropy the solve reproduces it exactly with a zero isotropic weight. The
    change of variables therefore threw nothing away."""

    def old_phase(cos_angle, back, g):
        forward = 1.0 - back
        return (
            back * henyey_greenstein(cos_angle, BACKWARD_ANISOTROPY)
            + forward * henyey_greenstein(cos_angle, g)
        ) / (
            back * henyey_greenstein(0.0, BACKWARD_ANISOTROPY)
            + forward * henyey_greenstein(0.0, g)
        )

    # The tuned setting: back_scatter 0.2, forward_anisotropy 0.4.
    optics = CloudOptics(
        forward_gain=float(old_phase(1.0, 0.2, 0.4)),
        backward_gain=float(old_phase(-1.0, 0.2, 0.4)),
        forward_anisotropy=0.4,
    )
    weights = phase_weights(optics)
    assert weights[2] == pytest.approx(0.0, abs=1e-9)  # no isotropic term needed
    np.testing.assert_allclose(
        phase(optics, ANGLES), old_phase(ANGLES, 0.2, 0.4), rtol=1e-9
    )


def test_the_phase_stays_positive_across_the_useful_range():
    """A negative phase renders as a dark hole, and it would fall BETWEEN the
    pinned angles where nothing else would catch it.

    The range checked here is the range the demo's sweep can reach; the ceiling is
    real and is documented in :data:`FORWARD_GAIN_CEILING`."""
    for forward in (1.0, 4.72, 10.0, 15.0):
        for backward in (0.8, 1.52, 3.0):
            optics = CloudOptics(forward_gain=forward, backward_gain=backward)
            assert phase(optics, ANGLES).min() >= 0.0, (forward, backward)


def test_a_broad_lobe_bounds_how_large_the_forward_gain_can_be():
    """A real constraint, not an arbitrary one: a broad forward lobe already lifts
    the mid-angles, so a large gain drives the isotropic weight negative to keep
    90 degrees pinned at 1. Widening the lobe therefore lowers the ceiling, and
    narrowing it raises it."""

    def feasible(forward, anisotropy):
        try:
            phase_weights(
                CloudOptics(
                    forward_gain=forward,
                    backward_gain=1.52,
                    forward_anisotropy=anisotropy,
                )
            )
        except ValueError:
            return False
        return True

    ceilings = []
    for g in (0.3, 0.4, 0.64):
        usable = [f for f in np.arange(2.0, 80.0, 0.5) if feasible(f, g)]
        ceilings.append(max(usable))
    # A narrower lobe allows a bigger gain.
    assert ceilings[0] < ceilings[1] < ceilings[2]
    # And the shipped default has usable headroom above the tuned value.
    assert ceilings[1] > 2.0 * CloudOptics().forward_gain


def test_infeasible_gains_are_refused_not_silently_broken():
    """Better a build-time error naming the fix than a black hole inside a cloud."""
    with pytest.raises(ValueError, match="negative"):
        phase_weights(CloudOptics(forward_gain=1.0, backward_gain=40.0))
    with pytest.raises(ValueError, match="negative"):
        phase_weights(CloudOptics(forward_gain=40.0, backward_gain=1.0))


def test_anisotropy_is_clamped_below_one():
    """A g of 1 is a delta spike; the basis matrix degenerates as it approaches."""
    capped = phase_weights(CloudOptics(forward_anisotropy=2.0))
    at_max = phase_weights(CloudOptics(forward_anisotropy=FORWARD_ANISOTROPY_MAX))
    np.testing.assert_allclose(capped, at_max)


def test_both_shaders_size_layerparams_for_every_layer():
    """A contract that has now been broken twice, in both directions, and neither
    failure is visible in a normal test run:

      * too small, and the higher layers read out of bounds — undefined crossfade
        and extinction, so those layers silently stop drawing;
      * different between the two stages, and the shared uniform fails to LINK
        ("has different type across different shaders") and nothing draws at all.

    Both stages must declare exactly MAX_LAYERS * LAYER_VEC4S.
    """
    expected = MAX_LAYERS * LAYER_VEC4S
    for name in ("cloud.frag", "cloud.vert"):
        source = Path(DATAFILES_PATH / "shaders" / name).read_text()
        match = re.search(r"uniform\s+vec4\s+layerParams\[(\d+)\]", source)
        assert match, f"layerParams declaration not found in {name}"
        assert int(match.group(1)) == expected, (
            f"{name} declares layerParams[{match.group(1)}], "
            f"expected {expected} = MAX_LAYERS({MAX_LAYERS}) * "
            f"LAYER_VEC4S({LAYER_VEC4S})"
        )
        # And the stride constant the accessors index with must agree too.
        stride = re.search(r"LAYER_VEC4S\s*=\s*(\d+)", source)
        assert stride, f"LAYER_VEC4S constant not found in {name}"
        assert int(stride.group(1)) == LAYER_VEC4S, name


def test_shader_phase_constant_matches_the_python_one():
    """cloud.frag hard-codes the backward lobe's g, since it is fixed. If that
    drifted from the Python value the pre-solved weights would be solved against a
    different basis than the shader evaluates, and the gains would be wrong."""
    source = Path(DATAFILES_PATH / "shaders/cloud.frag").read_text()
    match = re.search(r"BACKWARD_G\s*=\s*(-?[0-9.]+)", source)
    assert match, "BACKWARD_G not found in cloud.frag"
    assert float(match.group(1)) == pytest.approx(BACKWARD_ANISOTROPY)
    # And the shader must no longer normalise: the weights already do that.
    assert "atRightAngles" not in source


# ── The texture ─────────────────────────────────────────────────────────────────


def test_texture_is_repeat_wrapped_single_channel_and_unmipmapped():
    texture = build_noise_texture()
    assert texture.get_texture_type() == Texture.TT_3d_texture
    assert (texture.get_x_size(), texture.get_y_size(), texture.get_z_size()) == (
        NOISE_SIZE,
        NOISE_SIZE,
        NOISE_SIZE,
    )
    # Single channel, so there is no BGRA channel-order ambiguity to get wrong.
    assert texture.get_num_components() == 1
    for get_wrap in (texture.get_wrap_u, texture.get_wrap_v, texture.get_wrap_w):
        assert get_wrap() == Texture.WM_repeat
    # A 3D mip chain would average the fbm's highest octave away to a constant.
    assert texture.get_minfilter() == SamplerState.FT_linear
    assert texture.get_magfilter() == SamplerState.FT_linear


def test_texture_carries_the_volume_contents():
    texture = build_noise_texture(seed=11)
    expected = value_noise_volume(seed=11)
    got = np.frombuffer(texture.get_ram_image().get_data(), dtype=np.uint8)
    assert got.shape == (NOISE_SIZE**3,)
    # The RAM image is page-major, matching numpy's [z, y, x] ordering.
    np.testing.assert_allclose(
        got.reshape(expected.shape) / 255.0, expected, atol=1.0 / 255.0
    )


def test_feature_size_matches_the_lattice():
    assert NOISE_FEATURE == NOISE_SIZE / NOISE_LATTICE
    assert NOISE_SIZE % NOISE_LATTICE == 0
