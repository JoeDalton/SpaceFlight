"""
Unit tests for the in-scene cloud system (space_flight.scenes.cloud).

These run fully headless (the shared window-type none app): they build geometry
and step the per-frame CPU logic but never render, so they need no window or GPU
context and are safe for the GitHub CI runners.

Note the hard limit of a headless suite: it cannot see a pixel, and it cannot
even tell you whether the GLSL compiles — Panda's Shader.load succeeds with no
graphics context.  So the shape and the lighting are checked by rendering
offscreen or running the demo (scripts/demo_clouds.py); what is checked HERE is
the contracts a later change could silently break, above all that the CPU
placement and the GPU drawing agree about where the cloud is.

If tests break on ubuntu : loadPrcFileData("", "load-display p3tinydisplay")
"""

import re
import types
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from panda3d.core import CullBinManager, NodePath, Vec3, loadPrcFileData

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.graphics_settings import _VALID_CLOUD_QUALITY
from space_flight.scenes.cloud import (
    PRESETS,
    QUALITY_SCALES,
    CloudField,
    CloudLayer,
    CloudOptics,
    CloudQuality,
    Clouds,
    CloudType,
    DensityField,
    at_quality,
)
from space_flight.scenes.cloud.cloud import atlas_rects as read_atlas_rects
from space_flight.scenes.cloud.cloud import (
    load_cloud_atlas,
    sample_field_particles,
    snap_to_noise_period,
    volume_fraction,
)
from space_flight.scenes.cloud.field import (
    _CELL_PARAMS_STRIDE,
    _CELLS_PER_ROW,
    MAX_LAYERS,
    _default_layers,
    _ensure_cloud_bins,
    lod_shells,
)
from space_flight.scenes.cloud.noise import (
    LAYER_VEC4S,
    NOISE_SIZE,
    OCTAVE_OFFSETS,
    density,
    measure_coverage,
    phase_weights,
    quantise,
    resolve_field,
    streak_direction,
    value_noise_volume,
)

# Must be set before ShowBase is constructed.
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")

# A domain small enough to keep every field in this file cheap to build. It is
# also SMALLER than the cumulus field's 32 km noise period, which deliberately
# exercises the non-seamless recycle path (see snap_to_noise_period).
TEST_DOMAIN = 6000.0


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app(spaceflight_app):
    """
    The shared headless app (ShowBase is a singleton — see
    conftest.py::spaceflight_app). Its asset_manager is all the cloud atlas
    loader needs.
    """
    return spaceflight_app


@pytest.fixture(scope="session")
def game(app):
    """Minimal game stub exposing app for the atlas loader / field."""
    return types.SimpleNamespace(app=app)


@pytest.fixture(scope="session")
def atlas_rects(game):
    """The packaged sprite-atlas rects. The sprites are a per-quad THICKNESS
    profile, not a silhouette, which is what lets one billboard stand in for a
    lumpy puff instead of a smooth ball."""
    return load_cloud_atlas(game)[1]


@pytest.fixture(scope="module")
def volume():
    """The noise octave, quantised the way the GPU copy is."""
    return quantise(value_noise_volume(seed=7))


@pytest.fixture(scope="module")
def resolved(volume):
    """PRESETS with every field's derived threshold filled in, as the build does.

    A preset carries ``coverage``, not a threshold: which raw fbm value corresponds
    to a given coverage depends on the noise volume, so a preset is genuinely not
    placeable until it has been resolved against the volume it will be drawn from.
    Resolved once for the whole module, because measuring a field is the expensive
    part (see noise.column_peaks).
    """
    return {
        cloud_type: replace(spec, field=resolve_field(volume, spec.field))
        for cloud_type, spec in PRESETS.items()
    }


def _make_field(game, layers, **kwargs):
    """Build a CloudField under a throwaway parent (no rendering).

    Quality is pinned to HIGH — the authored presets — because the `game` fixture
    wraps the REAL app, whose graphics_settings reads the developer's own
    configuration/graphics.yaml. Without this, setting cloud quality in the menu
    silently changes what the suite asserts, and CI disagrees with local.
    Tests that mean to exercise the settings-reading path pass quality=None.
    """
    kwargs.setdefault("domain", TEST_DOMAIN)
    kwargs.setdefault("quality", CloudQuality.HIGH)
    return CloudField(
        parent=NodePath("test_parent"), game=game, layers=layers, **kwargs
    )


CUMULUS = [CloudLayer(CloudType.CUMULUS)]


# ── The contract between placement and drawing (the load-bearing one) ───────────


def test_shader_octave_offsets_match_the_placement_fbm():
    """noise.py's fbm decides WHERE billboards go and the shader's decides where
    cloud is DRAWN, so their octave offsets must be identical. If they drifted,
    billboards would sit in clear air while cloud went undrawn — a failure that no
    other test here could see, since one side lives in GLSL."""
    source = Path(DATAFILES_PATH / "shaders/cloud.frag").read_text()
    found = []
    for index in (2, 3, 4):
        match = re.search(rf"OCTAVE_{index}_OFFSET\s*=\s*vec3\(([^)]*)\)", source)
        assert match, f"OCTAVE_{index}_OFFSET not found in cloud.frag"
        found.append(tuple(float(v) for v in match.group(1).split(",")))
    assert found == list(OCTAVE_OFFSETS[1:])


def test_every_placed_billboard_sits_where_the_field_is_cloud(
    volume, atlas_rects, resolved
):
    """Placement is rejection-sampled against the very field the shader draws, so
    every billboard centre must be at non-zero density. The shader discards
    fragments below the threshold, so a billboard placed in clear air is pure
    wasted fill rate — and a systematic offset between the two would eat the
    silhouette."""
    spec = resolved[CloudType.CUMULUS]
    placed = sample_field_particles(
        spec, volume, domain=4000.0, cell_size=1000.0, atlas_rects=atlas_rects, seed=1
    )
    world = placed["local"] + np.repeat(
        placed["cell_centres"], np.diff(placed["cell_start"]), axis=0
    )
    assert len(world) > 100
    assert (density(volume, spec.field, world) > 0.0).all()


def test_placement_covers_the_slab_and_nothing_outside_it(
    volume, atlas_rects, resolved
):
    """The slab belongs to the cloud TYPE, so every billboard of a type lives
    between the same two altitudes — which is exactly what stops one cloud's
    profile cutting a plane through its neighbour."""
    spec = resolved[CloudType.CUMULUS]
    base, thickness = spec.field.slab
    placed = sample_field_particles(
        spec, volume, domain=4000.0, cell_size=1000.0, atlas_rects=atlas_rects, seed=2
    )
    z = placed["local"][:, 2] + np.repeat(
        placed["cell_centres"][:, 2], np.diff(placed["cell_start"])
    )
    assert z.min() >= base
    assert z.max() <= base + thickness


def test_higher_coverage_places_more_billboards(volume, atlas_rects, resolved):
    """Coverage must reach all the way through to placement.

    Placement is rejection-sampled against the resolved field, so asking for more
    sky to be cloud has to put more billboards in it — otherwise the knob would
    change what is DRAWN without changing what is PLACED, and the deck would grow
    holes rather than grow.
    """
    spec = resolved[CloudType.CUMULUS]
    common = dict(
        volume=volume, domain=4000.0, cell_size=1000.0, atlas_rects=atlas_rects, seed=3
    )
    counts = []
    for coverage in (0.15, 0.30, 0.60):
        field = resolve_field(volume, replace(spec.field, coverage=coverage))
        placed = sample_field_particles(replace(spec, field=field), **common)
        counts.append(len(placed["local"]))
    assert counts[0] < counts[1] < counts[2], counts
    # And it grows FASTER than the projected area does — measured about 3.2x for a
    # doubling of coverage. That is the right behaviour, not a miscalibration:
    # coverage is what fraction of sky has cloud somewhere in the column, while
    # billboards fill a VOLUME, and at higher coverage each cloudy column is also
    # cloudy over a taller stretch of its slab. It is also the reason coverage is
    # the knob that costs the most performance.
    assert counts[1] / counts[0] > 2.0, counts


# ── Optical calibration (cloud.py) ──────────────────────────────────────────────


def test_volume_fraction_is_independent_of_the_billboard_budget(
    volume, atlas_rects, resolved
):
    """The whole point of deriving extinction from the geometry: asking for a
    different volume fraction must change the count and the extinction in
    opposite directions, leaving what a ray accumulates unchanged. So changing
    the billboard budget is a performance decision, not a look change."""
    spec = resolved[CloudType.CUMULUS]
    common = dict(
        volume=volume, domain=4000.0, cell_size=1000.0, atlas_rects=atlas_rects, seed=4
    )
    coarse = sample_field_particles(replace(spec, volume_fraction=1.0), **common)
    fine = sample_field_particles(replace(spec, volume_fraction=4.0), **common)
    assert len(fine["local"]) > len(coarse["local"])
    assert fine["phi"] > coarse["phi"]
    # phi tracks the request, so density/phi cancels the count out.
    assert coarse["phi"] == pytest.approx(1.0, rel=0.15)
    assert fine["phi"] == pytest.approx(4.0, rel=0.15)


def test_volume_fraction_of_nothing_is_zero():
    assert volume_fraction(np.zeros(0), 1000.0) == 0.0
    assert volume_fraction(np.ones(5), 0.0) == 0.0


def test_field_extinction_offsets_the_volume_fraction(game):
    """extinction == field density / (phi * sprite coverage), so a denser packing
    is not a denser cloud."""
    field = _make_field(game, CUMULUS)
    report = field._layer_report[0]
    assert report["extinction"] > 0.0
    assert report["extinction"] == pytest.approx(
        field._layer_specs[0].field.density / (report["phi"] * 0.385), rel=0.05
    )


# ── Seamless recycling (cloud.py) ───────────────────────────────────────────────


def test_domain_snaps_down_to_a_whole_noise_period():
    """A cell recycles by teleporting one box width. When that width is a whole
    number of the field's noise periods it lands where the field is
    bit-identical, so the jump is invisible and needs no fade to hide it."""
    spec = PRESETS[CloudType.CUMULUS].field
    period = NOISE_SIZE / spec.noise_scale[0]
    width, seamless = snap_to_noise_period(spec, 2.5 * period)
    assert seamless
    assert width == pytest.approx(2.0 * period)


def test_a_domain_below_one_period_is_honoured_but_not_seamless():
    """Snapping up would silently quadruple the billboard count, so a small
    domain is honoured as asked and covered by the fade band instead."""
    spec = PRESETS[CloudType.CUMULUS].field
    width, seamless = snap_to_noise_period(spec, 5000.0)
    assert width == 5000.0
    assert not seamless


def test_an_anisotropic_field_cannot_recycle_seamlessly():
    """Cirrus stretches X against Y, so its two horizontal noise periods differ
    and no one square box is a whole multiple of both."""
    _, seamless = snap_to_noise_period(PRESETS[CloudType.CIRRUS].field, 1e6)
    assert not seamless


def test_a_seamless_layer_gets_no_fade_band(game):
    """The fade band exists only to hide a recycle. A seamless box has nothing to
    hide, so the band must be exactly zero — otherwise clouds dissolve at the
    domain edge for no reason."""
    period = NOISE_SIZE / PRESETS[CloudType.CUMULUS].field.noise_scale[0]
    seamless = _make_field(game, CUMULUS, domain=period)
    faded = _make_field(game, CUMULUS, domain=TEST_DOMAIN)
    # layerParams row 5 is (extinction, density, wrapRadius, wrapFadeBand).
    assert seamless._layer_report[0]["seamless"]
    assert seamless._layer_params[0][5][3] == 0.0
    assert faded._layer_params[0][5][3] > 0.0


# ── Per-type density fields (noise.py) ──────────────────────────────────────────


def test_each_type_has_its_own_field_and_they_are_decorrelated(volume, resolved):
    """Two types sharing one noise volume must not carve identically. They are
    separated by a constant offset in noise space, which is an independent field
    with the same statistics for the cost of an add."""
    offsets = {t: PRESETS[t].field.offset for t in CloudType}
    assert len(set(offsets.values())) == len(CloudType)
    # And the fields themselves differ where their slabs allow comparison.
    points = np.random.default_rng(0).uniform(
        [-5000, -5000, 1100], [5000, 5000, 1400], (4000, 3)
    )
    cumulus_field = resolved[CloudType.CUMULUS].field
    shifted_field = resolve_field(
        volume, replace(cumulus_field, offset=(11.3, 5.7, 2.9))
    )
    assert not np.allclose(
        density(volume, cumulus_field, points),
        density(volume, shifted_field, points),
    )
    # The offset gives an independent field with the SAME statistics, which is why
    # a type keeps its authored coverage wherever it is put in noise space.
    assert measure_coverage(volume, shifted_field) == pytest.approx(
        cumulus_field.coverage, abs=0.02
    )


def test_layer_params_are_packed_one_row_per_layer(game):
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)],
    )
    assert field._layer_params.shape == (MAX_LAYERS, LAYER_VEC4S, 4)
    cumulus, cirrus = PRESETS[CloudType.CUMULUS], PRESETS[CloudType.CIRRUS]
    # Row 0 is (noiseScale.xyz, threshLo); row 4 is the slab and the profile.
    np.testing.assert_allclose(
        field._layer_params[0][0][:3], cumulus.field.noise_scale, rtol=1e-6
    )
    np.testing.assert_allclose(
        field._layer_params[1][0][:3], cirrus.field.noise_scale, rtol=1e-6
    )
    np.testing.assert_allclose(
        field._layer_params[0][4][:2], cumulus.field.slab, rtol=1e-6
    )


def test_optics_are_per_type_and_packed_after_the_field(game):
    """Optics ride in the same layerParams row block as the field, so a type's
    march and cap are looked up with the field it belongs to."""
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)],
    )
    cumulus = PRESETS[CloudType.CUMULUS].optics
    cirrus = PRESETS[CloudType.CIRRUS].optics
    # Row 7 is (sunSteps, sunStepLength, shadowStrength, multipleScattering).
    np.testing.assert_allclose(
        field._layer_params[0][7],
        (
            cumulus.sun_steps,
            cumulus.sun_step_length,
            cumulus.shadow_strength,
            cumulus.multiple_scattering,
        ),
    )
    np.testing.assert_allclose(
        field._layer_params[1][7],
        (
            cirrus.sun_steps,
            cirrus.sun_step_length,
            cirrus.shadow_strength,
            cirrus.multiple_scattering,
        ),
    )
    # And they genuinely differ — a cirrus sheet marches differently to a deck.
    assert cirrus.sun_step_length != cumulus.sun_step_length
    assert cirrus.max_optical_depth != cumulus.max_optical_depth


def test_set_optics_changes_shading_live_without_a_rebuild(game):
    """Optics affect nothing but shading, so they need no rebuild. That is the
    whole reason they are split from the density field."""
    field = _make_field(game, CUMULUS)
    billboards, cells = field._n, field._n_cells
    local = field._local.copy()

    field.set_optics(shadow_strength=0.35, sun_steps=2)
    assert field._n == billboards  # nothing re-placed
    assert field._n_cells == cells
    np.testing.assert_array_equal(field._local, local)
    np.testing.assert_allclose(field._layer_params[0][7][2], 0.35)
    np.testing.assert_allclose(field._layer_params[0][7][0], 2.0)
    # _layer_specs is the single source of truth; the report holds only what the
    # build measured, so there is no second copy of the optics to go stale.
    assert field._layer_specs[0].optics.shadow_strength == 0.35
    assert "optics" not in field._layer_report[0]


def test_set_optics_can_target_one_layer(game):
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)]
    )
    before = float(field._layer_params[0][7][2])
    field.set_optics(layer=1, shadow_strength=0.2)
    np.testing.assert_allclose(field._layer_params[0][7][2], before)
    np.testing.assert_allclose(field._layer_params[1][7][2], 0.2)


def test_set_optics_rejects_shape_parameters(game):
    """Shape drives placement, so letting it through here would silently put the
    billboards and the drawn cloud out of step — better to refuse than to look
    like it worked."""
    field = _make_field(game, CUMULUS)
    with pytest.raises(AttributeError, match="rebuild"):
        field.set_optics(threshold=(0.1, 0.2))
    with pytest.raises(AttributeError):
        field.set_optics(shadow_strngth=0.5)  # a typo must not pass silently


def test_a_layer_can_override_the_preset_optics(game):
    optics = CloudOptics(sun_steps=1, forward_gain=3.0, backward_gain=2.0)
    field = _make_field(game, [CloudLayer(CloudType.CUMULUS, optics=optics)])
    np.testing.assert_allclose(field._layer_params[0][7][0], 1.0)
    # Rows 8-9 carry the solved phase weights, not the gains.
    forward, backward, isotropic = phase_weights(optics)
    np.testing.assert_allclose(field._layer_params[0][8][2], forward, rtol=1e-6)
    np.testing.assert_allclose(field._layer_params[0][8][3], backward, rtol=1e-6)
    np.testing.assert_allclose(field._layer_params[0][9][0], isotropic, rtol=1e-6)


def test_billboard_stretch_is_optically_free(volume, atlas_rects, resolved):
    """The stretch is area-preserving, so it must change neither the billboard
    count nor the volume fraction the extinction is derived from. Only the shape
    of each quad changes — which is why it is safe to tune by eye."""
    spec = resolved[CloudType.CIRRUS]
    common = dict(
        volume=volume, domain=4000.0, cell_size=2000.0, atlas_rects=atlas_rects, seed=9
    )
    square = sample_field_particles(replace(spec, aspect=1.0), **common)
    stretched = sample_field_particles(replace(spec, aspect=6.0), **common)
    assert len(square["local"]) == len(stretched["local"])
    assert square["phi"] == pytest.approx(stretched["phi"])
    np.testing.assert_array_equal(square["radii"], stretched["radii"])


def test_the_streak_axis_follows_the_field(game):
    """Derived from the field, not authored: a stretched billboard combing one way
    while the field streaks another would read as combed rather than fibrous."""
    # Cirrus stretches along X (its smallest horizontal noise scale).
    cirrus = PRESETS[CloudType.CIRRUS].field
    assert cirrus.noise_scale[0] < cirrus.noise_scale[1]
    assert streak_direction(cirrus) == (1.0, 0.0)
    # Swap the scales and the axis follows.
    swapped = replace(cirrus, noise_scale=(0.0025, 0.0004, 0.03))
    assert streak_direction(swapped) == (0.0, 1.0)


def test_aspect_and_streak_reach_the_shader(game):
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)]
    )
    # Row 10 is (aspect, streak.x, streak.y, spare).
    np.testing.assert_allclose(field._layer_params[0][10], (1.0, 1.0, 0.0, 0.0))
    np.testing.assert_allclose(
        field._layer_params[1][10],
        (PRESETS[CloudType.CIRRUS].aspect, 1.0, 0.0, 0.0),
    )
    # Only the fibrous type is stretched; a round cumulus puff should stay round.
    assert PRESETS[CloudType.CUMULUS].aspect == 1.0
    assert PRESETS[CloudType.CIRRUS].aspect > 1.0


def test_the_billboard_aspect_is_gentler_than_the_field(game):
    """Matching the field's own anisotropy would double-count it and read as
    combed; the billboard only has to stop fighting the field."""
    cirrus = PRESETS[CloudType.CIRRUS]
    field_ratio = cirrus.field.noise_scale[1] / cirrus.field.noise_scale[0]
    assert 1.0 < cirrus.aspect < field_ratio


def test_too_many_layers_is_rejected(game):
    """The layerParams uniform array is a fixed size, and Panda would silently
    truncate rather than complain."""
    with pytest.raises(ValueError, match="at most"):
        _make_field(game, [CloudLayer(CloudType.CUMULUS)] * (MAX_LAYERS + 1))


def test_a_layer_can_override_the_preset_field(game):
    """The field IS the shape, so overriding it is the whole tuning surface."""
    custom = replace(PRESETS[CloudType.CUMULUS].field, slab=(2000.0, 300.0))
    field = _make_field(game, [CloudLayer(CloudType.CUMULUS, field=custom)])
    np.testing.assert_allclose(field._layer_params[0][4][:2], (2000.0, 300.0))
    z = field._local[:, 2] + np.repeat(field._cell_centres[:, 2], field._cell_pop)
    assert z.min() >= 2000.0
    assert z.max() <= 2300.0


def test_density_field_reports_its_feature_size():
    """The number to reason about when asking how big a cloud will be."""
    spec = DensityField(noise_scale=(0.002, 0.002, 0.004))
    assert spec.feature_size == (2000.0, 2000.0, 1000.0)


# ── The ragged cell layout (field.py) ──────────────────────────────────────────


def test_cells_partition_the_particles_exactly(game):
    """Populations vary, so the offsets table is the only thing that says which
    particles belong to which cell. It must tile the array with no gap and no
    overlap, or the per-frame re-sort writes one cell's triangles into another's
    slot."""
    field = _make_field(game, CUMULUS)
    assert field._cell_start[0] == 0
    assert field._cell_start[-1] == field._n
    assert (np.diff(field._cell_start) > 0).all()  # no empty cells are kept
    assert len(field._cell_start) == field._n_cells + 1


def test_particles_lie_within_their_own_cell(game):
    """A particle's position is stored relative to ITS cell's centre, and the cell
    is the unit of recycling — so a particle outside its cell would be teleported
    to the wrong place."""
    field = _make_field(game, [CloudLayer(CloudType.CUMULUS, cell_size=1000.0)])
    half = 0.5 * 1000.0
    assert (np.abs(field._local[:, :2]) <= half + 1e-3).all()


def test_the_layout_is_ragged_not_padded(game):
    """Padding every cell to the largest costs about 3x the vertex memory at
    cumulus coverage. If a change ever reintroduced it, populations would all be
    equal and this would catch it. Every slot is a real billboard: there is no
    zero-radius padding to skip in the vertex shader."""
    field = _make_field(game, CUMULUS)
    assert field._cell_pop.max() > field._cell_pop.min()
    assert field._n == field._cell_start[-1]


def test_cell_ids_index_the_cell_that_owns_each_particle(game):
    """The vertex shader looks a cell's centre up by this id, so an off-by-one
    would draw every billboard at a neighbouring cell's position."""
    field = _make_field(game, CUMULUS)
    expected = np.repeat(np.arange(field._n_cells), field._cell_pop)
    assert len(expected) == field._n
    assert expected.max() == field._n_cells - 1


# ── LOD shells (field.py) ───────────────────────────────────────────────────────


def _smoothstep(lo, hi, x):
    t = np.clip((np.asarray(x) - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _shell_weight(layer, distance):
    """The weight cloud.frag computes for this layer at a camera distance."""
    fade_in = layer.fade_in if layer.fade_in is not None else (-1.0, 0.0)
    fade_out = layer.fade_out if layer.fade_out is not None else (1e9, 2e9)
    return _smoothstep(*fade_in, distance) * (1.0 - _smoothstep(*fade_out, distance))


def test_shell_weights_sum_to_one_at_every_distance():
    """The load-bearing shell invariant. Adjacent shells share a crossfade band —
    one's fade-out is the next one's fade-in — so their weights must sum to
    exactly 1 there. Anything else is a ring of wrong density at a fixed radius
    from the camera, which sweeps across the field as you fly and which the eye
    picks up immediately."""
    shells = lod_shells(CloudType.CUMULUS, count=4, domain=32000.0)
    distances = np.linspace(0.0, 200000.0, 4001)
    total = sum(_shell_weight(shell, distances) for shell in shells)
    # Inside the outermost shell's reach the weights tile exactly.
    inside = distances <= shells[-1].domain * 0.5
    np.testing.assert_allclose(total[inside], 1.0, atol=1e-9)


def test_each_shell_hands_over_to_the_next(game):
    """One shell's fade-out band IS the next one's fade-in band. If they merely
    overlapped approximately the weights could not sum to 1."""
    shells = lod_shells(CloudType.CUMULUS, count=4)
    assert shells[0].fade_in is None  # present from the camera outward
    assert shells[-1].fade_out is None  # horizon haze takes it to sky
    for inner, outer in zip(shells, shells[1:]):
        assert inner.fade_out == outer.fade_in


def test_shell_crossfades_complete_inside_their_box():
    """A shell can only draw within its recycle box, so its handover must finish
    well inside it — otherwise the box edge shows."""
    for shell in lod_shells(CloudType.CUMULUS, count=4):
        if shell.fade_out is not None:
            assert shell.fade_out[1] < 0.5 * shell.domain


def test_shells_halve_in_count_as_they_double_in_reach(game):
    """The whole economic argument: quadruple the area, eighth the density, so
    each shell costs half its predecessor. A uniform field would quadruple.

    Uses a full 32 km innermost domain, which is one noise period, so every
    shell's box is a whole number of periods and they all see exactly the same
    coverage — the halving is then exact rather than statistical. At a fraction of
    a period the shells sample different parts of the field and the ratio drifts
    by 15-20%.
    """
    field = _make_field(game, lod_shells(CloudType.CUMULUS, count=3, domain=32000.0))
    counts = [report["particles"] for report in field._layer_report]
    assert len(counts) == 3
    for inner, outer in zip(counts, counts[1:]):
        assert outer == pytest.approx(inner * 0.5, rel=0.05)


def test_shells_scale_radius_and_cap_together(game):
    """A shell's billboards have twice the chord, hence twice the per-fragment
    optical depth — so the cap has to double with them or the outer shells get
    truncated and distant cloud renders too thin."""
    field = _make_field(game, lod_shells(CloudType.CUMULUS, count=3, domain=8000.0))
    for inner, outer in zip(field._layer_specs, field._layer_specs[1:]):
        assert outer.radius[0] == pytest.approx(2.0 * inner.radius[0])
        assert outer.radius[1] == pytest.approx(2.0 * inner.radius[1])
        assert outer.optics.max_optical_depth == pytest.approx(
            2.0 * inner.optics.max_optical_depth
        )
        # volume_fraction held CONSTANT is what makes the count fall as 1/r^3 on
        # its own, and what keeps a ray's total optical depth unchanged. If a shell
        # varied it, the deck would change density with distance.
        assert outer.volume_fraction == inner.volume_fraction


def test_shells_share_one_density_field(game):
    """They must, or their crossfades would disagree about where the cloud is."""
    shells = lod_shells(CloudType.CUMULUS, count=4)
    fields = {id(shell.field or PRESETS[shell.cloud_type].field) for shell in shells}
    assert len(fields) == 1


def test_every_shell_recycles_seamlessly(game):
    """Each shell's box is a power-of-two multiple of the innermost, which is one
    noise period — so every shell stays a whole number of periods."""
    field = _make_field(game, lod_shells(CloudType.CUMULUS, count=3, domain=32000.0))
    assert all(report["seamless"] for report in field._layer_report)


def test_cell_texture_stays_well_inside_the_gl_size_limit(game):
    """The cellParams texture is wrapped into ROWS, not laid out in one line.

    Laid out linearly it needs STRIDE * n_cells texels, which six shells push past
    a common GL_MAX_TEXTURE_DIMENSION of 16 384. Past the limit the texture cannot
    be created, every fetch returns zero, and the whole field silently collapses
    to one blob at the origin with every billboard claiming layer 0.
    """
    field = _make_field(game, lod_shells(CloudType.CUMULUS, count=6, domain=32000.0))
    texture = field._cell_tex
    assert texture.get_x_size() == _CELL_PARAMS_STRIDE * _CELLS_PER_ROW
    # The width is fixed, so it cannot creep toward the limit however many cells
    # the field grows to; only the (cheap) row count moves.
    assert texture.get_x_size() <= 8192
    assert field._n_cells > _CELLS_PER_ROW, "want more than one row exercised"
    assert texture.get_y_size() == -(-field._n_cells // _CELLS_PER_ROW)


def test_every_cell_is_readable_where_the_shader_looks_for_it(game):
    """The row-wrapping contract: cloud.vert computes (row, column) from the cell
    id, and this checks a cell's centre and layer really land there. Get the
    wrapping wrong and billboards are drawn at another cell's position."""
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)],
    )
    image = np.frombuffer(
        field._cell_tex.get_ram_image().get_data(), dtype=np.float32
    ).reshape(field._cell_rows, _CELLS_PER_ROW, _CELL_PARAMS_STRIDE)
    for cell in (0, 1, _CELLS_PER_ROW - 1, _CELLS_PER_ROW, field._n_cells - 1):
        if cell >= field._n_cells:
            continue
        row, column = divmod(cell, _CELLS_PER_ROW)  # exactly what the shader does
        np.testing.assert_allclose(
            image[row, column, 0:3], field._cell_centres[cell], rtol=1e-6
        )
        assert image[row, column, 3] == pytest.approx(field._cell_layer[cell])


def test_planet_curvature_is_stored_as_the_shader_expects(game):
    flat = _make_field(game, CUMULUS, planet_radius=0.0)
    curved = _make_field(game, CUMULUS, planet_radius=6371000.0)
    assert flat._curvature == 0.0
    assert curved._curvature == pytest.approx(1.0 / (2.0 * 6371000.0))
    # The drop that matters: negligible near, comparable to the slab far out.
    assert 32000.0**2 * curved._curvature == pytest.approx(80.4, rel=0.02)
    assert 128000.0**2 * curved._curvature == pytest.approx(1286.0, rel=0.02)


# ── Draw order (field.py) ───────────────────────────────────────────────────────


def test_draw_order_is_a_permutation_of_the_cells(game):
    field = _make_field(game, CUMULUS)
    field.update(Vec3(0, 0, 1200), 1 / 60.0)
    assert sorted(field._draw_order.tolist()) == list(range(field._n_cells))


def test_buffer_offsets_tile_the_index_buffer(game):
    """With variable populations, a cell's slot depends on which cells outrank it.
    The cumulative table must still cover the buffer exactly once."""
    field = _make_field(game, CUMULUS)
    field.update(Vec3(0, 0, 1200), 1 / 60.0)
    assert field._buf_offset[0] == 0
    assert field._buf_offset[-1] == field._n
    np.testing.assert_array_equal(
        np.diff(field._buf_offset), field._cell_pop[field._draw_order]
    )


def test_index_buffer_is_a_permutation_after_a_full_cycle(game):
    """Every particle must be drawn exactly once — the ragged gather is the part
    most likely to drop or duplicate one."""
    field = _make_field(game, CUMULUS, resort_frames=4)
    for _ in range(8):  # > resort_frames → at least one full cycle
        field.update(Vec3(120, -80, 1200), 1 / 60.0)
    assert field._stage.min() >= 0
    assert field._stage.max() < 4 * field._n
    # Six indices per particle; every vertex of every quad must appear.
    assert np.array_equal(np.sort(np.unique(field._stage)), np.arange(4 * field._n))


def test_particles_are_sorted_back_to_front_within_a_cell(game):
    """Premultiplied "over" is order-dependent, so this ordering is what makes the
    accumulation correct rather than merely plausible."""
    field = _make_field(game, CUMULUS, resort_frames=1)
    cam = Vec3(300, -200, 1250)
    field.update(cam, 1 / 60.0)
    cam_xyz = np.array([cam.x, cam.y, cam.z], np.float32)
    # The first cell in draw order occupies the first slots of the buffer.
    cell = field._draw_order[0]
    count = field._cell_pop[cell]
    drawn = field._stage[: count * 6 : 6] // 4  # particle id per triangle pair
    world = field._cell_centres[cell] + field._local[drawn]
    dist = np.linalg.norm(world - cam_xyz, axis=1)
    assert (np.diff(dist) <= 1e-3).all(), "not far → near within the cell"


def test_cells_are_ordered_far_to_near(game):
    field = _make_field(game, CUMULUS)
    cam = Vec3(500, -300, 1400)
    field.update(cam, 1 / 60.0)
    cam_xyz = np.array([cam.x, cam.y, cam.z], np.float32)
    dist_sq = np.sum((field._cell_centres - cam_xyz) ** 2, axis=1)
    np.testing.assert_array_equal(field._draw_order, np.argsort(-dist_sq))


# ── Wind and recycling (field.py) ──────────────────────────────────────────────


def test_field_advects_the_noise_with_the_wind(game):
    """If the field did not drift with the clouds, puffs would slide through it
    and continuously dissolve. The advection is derived from the same wind, and
    carried in metres so every layer scales it by its own noise_scale."""
    field = _make_field(game, CUMULUS, wind=(20.0, 0.0, 0.0))
    assert np.array_equal(field._noise_offset, np.zeros(3))
    field.update(Vec3(0, 0, 1200), 1.0)
    # Opposite in sign to the drift, so world-position-plus-offset is invariant.
    np.testing.assert_allclose(field._noise_offset, [-20.0, 0.0, 0.0])


def test_wind_drifts_cell_centres(game):
    """Three seconds at 50 m/s is well inside the box, so nothing recycles and
    the drift is exactly the wind."""
    field = _make_field(game, CUMULUS, wind=(50.0, 0.0, 0.0))
    before = field._cell_centres.copy()
    for _ in range(3):
        field.update(Vec3(0, 0, 1200), 1.0)
    moved = field._cell_centres - before
    np.testing.assert_allclose(moved[:, 0], 150.0, atol=1e-3)
    np.testing.assert_allclose(moved[:, 1:], 0.0, atol=1e-3)


def test_recycling_keeps_cells_within_their_box(game):
    field = _make_field(game, CUMULUS, wind=(0, 0, 0))
    cam = Vec3(0, 0, 1200)
    for i in range(40):  # fly far beyond the box
        cam = Vec3(i * 500.0, i * 400.0, 1200)
        field.update(cam, 1 / 60.0)
    rel = np.abs(field._cell_centres[:, :2] - np.array([cam.x, cam.y], np.float32))
    assert (rel.max(axis=1) <= field._cell_wrap + 1e-3).all()


def test_layers_recycle_within_their_own_box(game):
    """Each layer has its own box, which is what LOD shells rely on: a distant
    shell can be huge without needing the near shell's cloud density everywhere."""
    field = _make_field(
        game,
        [
            CloudLayer(CloudType.CUMULUS, domain=4000.0),
            CloudLayer(CloudType.CIRRUS, domain=12000.0),
        ],
        wind=(500.0, 0.0, 0.0),
    )
    np.testing.assert_allclose(sorted(np.unique(field._cell_wrap)), [2000.0, 6000.0])
    for _ in range(40):
        field.update(Vec3(0, 0, 1200), 1.0)
    rel = np.abs(field._cell_centres[:, :2])
    assert (rel.max(axis=1) <= field._cell_wrap + 1e-3).all()


def test_a_windless_field_with_a_parked_camera_does_not_move(game):
    field = _make_field(game, CUMULUS, wind=(0, 0, 0))
    before = field._cell_centres.copy()
    for _ in range(3):
        field.update(Vec3(0, 0, 1200), 1.0)
    np.testing.assert_array_equal(field._cell_centres, before)


def test_update_with_zero_dt_does_not_drift(game):
    """A paused frame must not advance the wind."""
    field = _make_field(game, CUMULUS, wind=(50.0, 0.0, 0.0))
    before = field._cell_centres.copy()
    field.update(Vec3(0, 0, 1200), 0.0)
    np.testing.assert_array_equal(field._cell_centres, before)
    np.testing.assert_array_equal(field._noise_offset, np.zeros(3))


# ── Live sun (field.py) ─────────────────────────────────────────────────────────


def test_set_sun_normalises_and_records(game):
    """The sun is a handful of uniforms, so it can move with no rebuild. Anything
    baked per particle would need the placement regenerated instead."""
    field = _make_field(game, CUMULUS)
    before = field._n  # billboard count must not change
    field.set_sun(
        (0.0, 0.0, 5.0), sun_color=(1.0, 0.5, 0.25), sky_color=(0.1, 0.2, 0.3)
    )
    assert field._n == before
    assert field._sun_color_arg == (1.0, 0.5, 0.25)
    assert field._sky_color_arg == (0.1, 0.2, 0.3)
    # Colours are optional: direction alone must leave them alone.
    field.set_sun((1.0, 0.0, 1.0))
    assert field._sun_color_arg == (1.0, 0.5, 0.25)


def test_set_sun_rejects_a_zero_direction(game):
    field = _make_field(game, CUMULUS)
    with pytest.raises(ValueError):
        field.set_sun((0.0, 0.0, 0.0))


# ── Draw order vs. the rest of the scene ────────────────────────────────────────


def test_cloud_bins_sort_between_opaque_and_transparent(game):
    """The load-bearing draw-order contract.

    Clouds don't write depth, so anything drawn after them composites over them
    regardless of depth. The clouds must therefore sit AFTER "opaque" (so opaque
    geometry occludes them via the depth test) and BEFORE "transparent" and
    "fixed" (so every translucent effect in the game composites over them).
    """
    _make_field(game, CUMULUS)
    manager = CullBinManager.get_global_ptr()

    def sort_of(name):
        index = manager.find_bin(name)
        assert index != -1, f"cull bin {name!r} is not registered"
        return manager.get_bin_sort(index)

    assert (
        sort_of("opaque") < sort_of("cloud") < sort_of("transparent") < sort_of("fixed")
    )


def test_ensure_cloud_bins_is_idempotent(game):
    """Building several fields must not keep adding duplicate bins."""
    _ensure_cloud_bins()
    manager = CullBinManager.get_global_ptr()
    before = manager.get_num_bins()
    _ensure_cloud_bins()
    _make_field(game, CUMULUS)
    assert manager.get_num_bins() == before


def test_the_build_resolves_every_layers_coverage(game):
    """A layer reaches placement and packing only through the resolver, so no layer
    may still be carrying an unresolved field afterwards."""
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)]
    )
    for spec in field._layer_specs:
        assert spec.field.threshold is not None
        lo, hi = spec.field.threshold
        assert lo < hi
    # And the packed rows carry it, which is what the shader actually reads.
    assert field._layer_params[0][0][3] == pytest.approx(
        field._layer_specs[0].field.threshold[0], rel=1e-6
    )


def test_lod_shells_of_one_type_share_a_threshold(game):
    """Load-bearing. Shells of a type share a field and crossfade into each other,
    so if they resolved to different windows they would disagree about where cloud
    is exactly where both are drawing it."""
    field = _make_field(game, lod_shells(CloudType.CUMULUS, count=3, domain=6000.0))
    windows = {spec.field.threshold for spec in field._layer_specs}
    assert len(windows) == 1, windows


def test_set_coverage_changes_the_packed_window_without_rebuilding(game):
    """The live knob: re-derives the threshold from the cached peaks and re-packs,
    touching neither the geometry nor the placement."""
    field = _make_field(game, CUMULUS)
    before = field._layer_specs[0].field.threshold[0]
    rows_before = field._layer_params[0].copy()
    vertices = field.node.node().get_geom(0).get_vertex_data().get_num_rows()

    field.set_coverage(layer=0, coverage=0.10)
    after = field._layer_specs[0].field.threshold[0]
    assert field._layer_specs[0].field.coverage == pytest.approx(0.10)
    # Less cloud means a HIGHER bar for the field to clear.
    assert after > before
    assert field._layer_params[0][0][3] == pytest.approx(after, rel=1e-6)
    # Nothing but the window moved: same geometry, same everything else packed.
    assert field.node.node().get_geom(0).get_vertex_data().get_num_rows() == vertices
    np.testing.assert_allclose(field._layer_params[0][4:], rows_before[4:])


def test_set_coverage_can_change_only_the_edge(game):
    """Softness and amount are independent axes, so setting one must not move the
    other — the window's low edge is what coverage is defined against.

    The width is asserted as a RATIO against the field's own starting softness,
    so this stays true whatever the preset ships.
    """
    field = _make_field(game, CUMULUS)
    spec = field._layer_specs[0].field
    softness_before = spec.edge_softness
    lo_before, hi_before = spec.threshold

    field.set_coverage(layer=0, edge_softness=2.5 * softness_before)
    lo_after, hi_after = field._layer_specs[0].field.threshold
    # The low edge is where coverage lives, so it must not budge at all.
    assert lo_after == pytest.approx(lo_before)
    # Width is edge_softness * sigma, and sigma did not change.
    assert (hi_after - lo_after) == pytest.approx(2.5 * (hi_before - lo_before))
    assert field._layer_specs[0].field.coverage == pytest.approx(spec.coverage)


def test_set_coverage_leaves_other_layers_alone(game):
    """Coverage is per type: each has its own slab and its own field, so setting
    one type's must not touch another's."""
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS), CloudLayer(CloudType.CIRRUS)]
    )
    cirrus_before = field._layer_specs[1].field.threshold
    field.set_coverage(layer=0, coverage=0.5)
    assert field._layer_specs[1].field.threshold == cirrus_before
    assert (
        field._layer_specs[1].field.coverage == PRESETS[CloudType.CIRRUS].field.coverage
    )


# ── Quality (cloud.py) ─────────────────────────────────────────────────────────


def test_high_is_exactly_what_the_presets_ship():
    """HIGH must be the identity, or the authored look would depend on a setting."""
    for spec in PRESETS.values():
        assert at_quality(spec, CloudQuality.HIGH) is spec


def test_quality_preserves_the_sun_marchs_reach():
    """The load-bearing invariant. sun_steps * sun_step_length is how far sunward
    the march looks, and for cumulus that is tuned to one cloud's depth — what it
    takes to reach full shadow at the base of a tower. Dropping steps without
    lengthening them would shorten the reach and wash the self-shadowing out, which
    is a change of look, not of quality."""
    for cloud_type, spec in PRESETS.items():
        reach = spec.optics.sun_steps * spec.optics.sun_step_length
        for quality in CloudQuality:
            optics = at_quality(spec, quality).optics
            assert optics.sun_steps * optics.sun_step_length == pytest.approx(reach), (
                f"{cloud_type.value} at {quality.value} changed its march reach"
            )


def test_quality_never_marches_zero_steps():
    """A type that already marches few steps (cirrus marches 2) must not be scaled
    into marching none, which would remove self-shadowing outright."""
    for spec in PRESETS.values():
        for quality in CloudQuality:
            assert at_quality(spec, quality).optics.sun_steps >= 1


def test_quality_leaves_volume_fraction_alone():
    """Count is changed through the RADIUS, holding volume_fraction — and therefore
    ray overlap — fixed. Cutting volume_fraction instead was measured to cost 18%
    of a cloud's screen area at LOW (against 8.8% this way), because at a cloud's
    fringe removing billboards removes the silhouette rather than thinning it."""
    for spec in PRESETS.values():
        for quality in CloudQuality:
            scaled = at_quality(spec, quality)
            assert scaled.volume_fraction == spec.volume_fraction


def test_quality_scales_the_radius_as_the_cube_root_of_the_count():
    """volume_fraction is (4/3)*pi*n*<r^3>, so holding it fixed makes the count
    fall as the cube of the radius — the same conservation law lod_shells uses for
    distance. This is what makes the count land on the requested ratio."""
    spec = PRESETS[CloudType.CUMULUS]
    for quality, (count, _march) in QUALITY_SCALES.items():
        scaled = at_quality(spec, quality)
        for shipped, got in zip(spec.radius, scaled.radius):
            assert got == pytest.approx(shipped * count ** (-1.0 / 3.0))


def test_quality_is_relative_so_types_keep_their_character():
    """Scales are multipliers, not absolutes: a thin veil must still march fewer
    steps than a 2.4 km tower at every level, because that difference is about the
    types' geometry rather than about quality."""
    for quality in CloudQuality:
        cirrus = at_quality(PRESETS[CloudType.CIRRUS], quality).optics.sun_steps
        tower = at_quality(PRESETS[CloudType.CUMULONIMBUS], quality).optics.sun_steps
        assert cirrus < tower, quality


def test_the_march_is_stepped_more_gently_than_the_billboards():
    """Deliberate asymmetry: billboards are a pure cost, but the sun march is what
    makes clouds shadow themselves, which is most of what gives them form. Halving
    it per level would put cumulus at a single sample by LOW."""
    for quality, (count, march) in QUALITY_SCALES.items():
        if count < 1.0:
            assert march > count, quality
        elif count > 1.0:
            assert march < count, quality


def test_quality_scales_reach_the_built_billboard_count(game):
    """End to end: the ratio asked for is the ratio placed."""
    counts = {}
    for quality in CloudQuality:
        field = _make_field(game, CUMULUS, quality=quality)
        counts[quality] = field._n
    reference = counts[CloudQuality.HIGH]
    for quality, (count, _march) in QUALITY_SCALES.items():
        # Placement is a rejection sample, so allow a few percent of noise.
        assert counts[quality] / reference == pytest.approx(count, rel=0.05), counts


def test_quality_does_not_disturb_the_coverage_calibration(game):
    """Quality touches the billboards and the march, never the FIELD — so how much
    of the sky is cloud must not depend on the graphics setting."""
    windows = set()
    for quality in CloudQuality:
        field = _make_field(game, CUMULUS, quality=quality)
        windows.add(field._layer_specs[0].field.threshold)
    assert len(windows) == 1, windows


def test_a_field_defaults_to_the_players_setting(game):
    """Read from the graphics settings the way the ocean reads its reflection
    scale, rather than threaded in by every caller."""
    settings = types.SimpleNamespace(config={"clouds": {"quality": "low"}})
    app = types.SimpleNamespace(
        asset_manager=game.app.asset_manager,
        loader=game.app.loader,
        graphics_settings=settings,
    )
    field = _make_field(types.SimpleNamespace(app=app), CUMULUS, quality=None)
    assert field._quality is CloudQuality.LOW
    # An explicit argument still wins.
    field = _make_field(
        types.SimpleNamespace(app=app), CUMULUS, quality=CloudQuality.ULTRA
    )
    assert field._quality is CloudQuality.ULTRA


@pytest.mark.parametrize(
    "config",
    [None, {}, {"clouds": {}}, {"clouds": {"quality": "nonsense"}}],
)
def test_a_missing_or_unknown_quality_means_the_authored_look(game, config):
    """The demo builds its field from a stub game with no settings at all. Absent
    or unreadable must mean HIGH — the presets' own values — never a crash and
    never a silent downgrade."""
    app = types.SimpleNamespace(
        asset_manager=game.app.asset_manager,
        loader=game.app.loader,
        graphics_settings=(
            None if config is None else types.SimpleNamespace(config=config)
        ),
    )
    field = _make_field(types.SimpleNamespace(app=app), CUMULUS, quality=None)
    assert field._quality is CloudQuality.HIGH


def test_the_suite_does_not_read_the_developers_quality_setting(game):
    """The `game` fixture wraps the real app, so CloudField's default
    quality=None would read this machine's configuration/graphics.yaml and make
    CI disagree with local. _make_field pins HIGH; this asserts it keeps doing so.
    """
    field = _make_field(game, CUMULUS)
    assert field._quality is CloudQuality.HIGH
    optics = field._layer_specs[0].optics
    shipped = PRESETS[CloudType.CUMULUS].optics
    assert optics.sun_steps == shipped.sun_steps
    assert optics.sun_step_length == pytest.approx(shipped.sun_step_length)


def test_cloud_quality_names_match_the_graphics_settings():
    """A cross-module contract with no import between the two sides: a name the
    settings sanitiser accepts but CloudQuality does not know would pass validation
    and then silently fall back to HIGH, so the player's choice would do nothing."""
    assert set(_VALID_CLOUD_QUALITY) == {q.value for q in CloudQuality}
    # And the settings list is ordered cheapest-first, which the menu slider's
    # stops depend on for "drag right costs more".
    assert list(_VALID_CLOUD_QUALITY) == ["low", "mid", "high", "ultra"]
    assert [q.value for q in CloudQuality] == list(_VALID_CLOUD_QUALITY)


def test_cloudfield_uses_the_cloud_bin(game):
    field = _make_field(game, CUMULUS)
    assert field.node.get_bin_name() == "cloud"


# ── Defaults, determinism & structure ───────────────────────────────────────────


def test_default_layers_is_a_shelled_cumulus_deck():
    """Cumulus alone while the look is being settled — a second type overhead
    makes the deck harder to judge — but in LOD shells, so it reaches the
    horizon."""
    layers = _default_layers()
    assert {layer.cloud_type for layer in layers} == {CloudType.CUMULUS}
    assert len(layers) > 1
    # Innermost first, each doubling the last.
    domains = [layer.domain for layer in layers]
    assert domains == sorted(domains)
    assert all(b == pytest.approx(2.0 * a) for a, b in zip(domains, domains[1:]))


def test_default_field_builds_and_recycles_seamlessly(game):
    """The default domain is exactly one noise period, so the recycle is
    invisible and no fade band is needed."""
    field = _make_field(game, None, domain=32000.0)
    assert field._layer_report[0]["seamless"]
    assert field._n > 1000
    assert not field.node.is_empty()


def test_cloudfield_deterministic(game):
    """Same seed => identical placement and draw order."""
    a = _make_field(game, CUMULUS, seed=11)
    b = _make_field(game, CUMULUS, seed=11)
    c = _make_field(game, CUMULUS, seed=12)
    np.testing.assert_array_equal(a._cell_centres, b._cell_centres)
    np.testing.assert_array_equal(a._local, b._local)
    assert a._n == b._n
    assert not (a._n == c._n and np.array_equal(a._local, c._local))


def test_cloudfield_vertex_buffer_row_count(game):
    """The block-wise vertex buffer fills all 4 verts per particle."""
    field = _make_field(game, CUMULUS)
    vdata = field.node.node().get_geom(0).get_vertex_data()
    assert vdata.get_num_rows() == 4 * field._n


def test_vertex_format_carries_no_colour_and_no_layer_column(game):
    """Colour is a function of world position, and the cloud type is a property of
    a whole cell — so neither may ride per vertex. Anything carried per particle
    that affects appearance shows up as quad-shaped patches."""
    field = _make_field(game, CUMULUS)
    array = field.node.node().get_geom(0).get_vertex_data().get_format().get_array(0)
    names = {
        str(array.get_column(i).get_name()) for i in range(array.get_num_columns())
    }
    assert names == {"vertex", "texcoord", "i_radius", "i_uv_st", "i_cellId"}
    assert array.get_stride() == 11 * 4


# ── Sprite atlas (cloud.py) ─────────────────────────────────────────────────────


def test_atlas_rects_read_without_a_context(atlas_rects):
    """The mean-alpha calibration and the tests both need the rects headlessly."""
    from_json = read_atlas_rects()
    assert len(from_json) == len(atlas_rects) > 0
    assert all(len(rect) == 4 for rect in from_json)


# ── Game wrapper (field.py) ──────────────────────────────────────────────────────


def test_clouds_wrapper_lifecycle(app):
    # window-type none makes no default camera, so stub one under the real render.
    camera = app.render.attach_new_node("clouds_test_cam")
    camera.set_pos(0, 0, 1200)
    game = types.SimpleNamespace(
        app=types.SimpleNamespace(
            loader=app.loader,
            render=app.render,
            camera=camera,
            asset_manager=app.asset_manager,
        ),
        root_node=app.render.attach_new_node("clouds_test_root"),
        method_lists={},
        game_time=types.SimpleNamespace(get_time_step=lambda: 1 / 60.0),
    )
    clouds = Clouds(game, layers=CUMULUS, domain=TEST_DOMAIN)

    assert clouds.id in game.method_lists
    game.method_lists[clouds.id][0]()  # the registered per-frame update
    assert not clouds.field.node.is_empty()

    clouds.clean()
    assert clouds.id not in game.method_lists
    assert clouds.field.node.is_empty()  # geometry detached
    game.root_node.remove_node()
    camera.remove_node()
