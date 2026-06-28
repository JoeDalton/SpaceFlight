"""
Unit tests for the in-scene cloud system (``space_flight.scenes.cloud``).

These run fully headless: a single ``window-type none`` ShowBase gives a loader
and a scene graph without opening a window or needing a GPU context, since the
tests build geometry and step the per-frame CPU logic but never render.  That
makes them safe for the GitHub CI runners.

If tests break on ubuntu : loadPrcFileData("", "load-display p3tinydisplay")
"""

import types

import numpy as np
import pytest
from panda3d.core import NodePath, Vec3, loadPrcFileData

from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.scenes.cloud import (
    CloudField,
    CloudLayer,
    Clouds,
    CloudType,
    build_templates,
)
from space_flight.scenes.cloud import cloud as cloud_module
from space_flight.scenes.cloud import load_cloud_atlas
from space_flight.scenes.cloud.cloud import (
    DEFAULTS,
    _load_cached_templates,
    _save_cached_templates,
    _shade_particles,
    _template_cache_key,
    build_cloud_particles,
    build_templates_iter,
)
from space_flight.scenes.cloud.field import _assemble

# Must be set before ShowBase is constructed.
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")

from direct.showbase.ShowBase import ShowBase  # noqa E402

SUN_DIR = np.array([0.2, 1.0, 0.1])
SUN_COLOR = np.array([1.0, 0.8, 0.2])
AMBIENT_COLOR = np.array([0.4, 0.1, 0.4])


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def app():
    """One headless ShowBase for the whole module (ShowBase is a singleton).

    The cloud atlas now loads through ``asset_manager`` (like every other
    particle atlas), so the headless app needs one attached.
    """
    base = ShowBase()
    base.asset_manager = AssetManager(base)
    return base


@pytest.fixture(scope="session")
def game(app):
    """Minimal game stub exposing ``app`` for the atlas loader / field."""
    return types.SimpleNamespace(app=app)


@pytest.fixture(scope="session")
def atlas_rects(game):
    """The packaged sprite-atlas rects (texture itself unused by these tests)."""
    return load_cloud_atlas(game)[1]


def _make_field(game, layers, **kwargs):
    """Build a CloudField under a throwaway parent (no rendering)."""
    return CloudField(
        parent=NodePath("test_parent"), game=game, layers=layers, **kwargs
    )


# ── Particle generation (cloud.py) ──────────────────────────────────────────────


@pytest.mark.parametrize("cloud_type", list(CloudType))
def test_build_cloud_particles_fields_and_ranges(cloud_type):
    particles = build_cloud_particles(cloud_type, seed=1)
    preset = DEFAULTS[cloud_type]

    assert 0 < len(particles) <= preset["n_particles"]
    assert all({"pos", "radius", "density", "albedo"} <= p.keys() for p in particles)

    density = np.array([p["density"] for p in particles])
    albedo = np.array([p["albedo"] for p in particles])
    pos = np.array([p["pos"] for p in particles])
    assert (
        preset["density_min"] - 1e-6 <= density.min()
        and density.max() <= preset["density_max"] + 1e-6
    )
    assert (
        preset["albedo_min"] - 1e-6 <= albedo.min()
        and albedo.max() <= preset["albedo_max"] + 1e-6
    )
    assert np.isfinite(pos).all()
    # Particles sit at/above the type's base altitude.
    assert pos[:, 2].min() >= preset["cloud_base_z"] - 1e-6


def test_build_cloud_particles_deterministic():
    same_a = build_cloud_particles(CloudType.CUMULUS, seed=7)
    same_b = build_cloud_particles(CloudType.CUMULUS, seed=7)
    diff = build_cloud_particles(CloudType.CUMULUS, seed=8)
    assert [p["pos"] for p in same_a] == [p["pos"] for p in same_b]
    assert [p["pos"] for p in same_a] != [p["pos"] for p in diff]


def test_overrides_change_particle_count():
    default = build_cloud_particles(CloudType.CUMULUS, seed=1)
    fewer = build_cloud_particles(CloudType.CUMULUS, seed=1, n_particles=50)
    assert len(fewer) <= 50 < len(default)


# ── Self-shadow shading (cloud.py) ───────────────────────────────────────────────


def test_shade_particles_shape_and_range():
    particles = build_cloud_particles(CloudType.CUMULUS, seed=1)
    rgb = _shade_particles(particles, SUN_COLOR, AMBIENT_COLOR, SUN_DIR)
    assert rgb.shape == (len(particles), 3)
    assert np.isfinite(rgb).all()
    assert (rgb >= 0).all() and (rgb <= 1).all()


def test_shade_particles_deterministic():
    particles = build_cloud_particles(CloudType.CUMULUS, seed=1)
    a = _shade_particles(particles, SUN_COLOR, AMBIENT_COLOR, SUN_DIR)
    b = _shade_particles(particles, SUN_COLOR, AMBIENT_COLOR, SUN_DIR)
    np.testing.assert_array_equal(a, b)


# ── Templates (cloud.py) ─────────────────────────────────────────────────────────


def test_build_templates(atlas_rects):
    templates = build_templates(
        3,
        atlas_rects,
        SUN_COLOR,
        AMBIENT_COLOR,
        SUN_DIR,
        cloud_type=CloudType.CUMULUS,
        density_scale=0.7,
    )
    assert len(templates) == 3
    for tpl in templates:
        n = len(tpl["pos"])
        assert tpl["pos"].shape == (n, 3)
        assert tpl["colors"].shape == (n, 4)
        assert tpl["uv"].shape == (n, 4)
        # Centred at the origin (so a placement's centroid is just its offset).
        assert np.allclose(tpl["pos"].mean(axis=0), 0.0, atol=1.0)
        # RGBA all in [0, 1]; alpha follows density × scale.
        assert (tpl["colors"] >= 0).all() and (tpl["colors"] <= 1).all()


def test_template_alpha_follows_density_scale(atlas_rects):
    faint = build_templates(
        1,
        atlas_rects,
        SUN_COLOR,
        AMBIENT_COLOR,
        SUN_DIR,
        cloud_type=CloudType.CUMULUS,
        density_scale=0.1,
        base_seed=3,
    )
    solid = build_templates(
        1,
        atlas_rects,
        SUN_COLOR,
        AMBIENT_COLOR,
        SUN_DIR,
        cloud_type=CloudType.CUMULUS,
        density_scale=0.9,
        base_seed=3,
    )
    # Same shape (same seed), so alpha scales with density_scale.
    assert faint[0]["colors"][:, 3].mean() < solid[0]["colors"][:, 3].mean()


# ── Field assembly (field.py) ────────────────────────────────────────────────────


def test_assemble_pads_to_max_and_keeps_offsets(atlas_rects):
    cumulus = build_templates(
        1, atlas_rects, SUN_COLOR, AMBIENT_COLOR, SUN_DIR, cloud_type=CloudType.CUMULUS
    )
    cirrus = build_templates(
        1, atlas_rects, SUN_COLOR, AMBIENT_COLOR, SUN_DIR, cloud_type=CloudType.CIRRUS
    )
    templates = cumulus + cirrus
    placements = [(0, (100.0, 0.0, 1200.0)), (1, (0.0, 200.0, 8000.0))]
    local, radii, colors, uv, centres, n_per = _assemble(templates, placements)

    assert n_per == max(len(cumulus[0]["pos"]), len(cirrus[0]["pos"]))
    assert local.shape == (2, n_per, 3)
    assert centres.shape == (2, 3)
    np.testing.assert_allclose(centres[0], [100, 0, 1200])
    np.testing.assert_allclose(centres[1], [0, 200, 8000])
    # The smaller (cirrus) cloud's padding is zero-radius → renders nothing.
    cirrus_count = len(cirrus[0]["pos"])
    assert (radii[1, cirrus_count:] == 0).all()


# ── CloudLayer dataclass ─────────────────────────────────────────────────────────


def test_cloud_layer_defaults():
    layer = CloudLayer(CloudType.CUMULUS, count=5)
    assert layer.altitude == (1000.0, 1500.0)
    assert layer.n_templates == 8
    assert layer.density_scale == 0.7
    assert layer.overrides is None


# ── CloudField (field.py) ────────────────────────────────────────────────────────


def test_cloudfield_counts_and_node(game):
    field = _make_field(
        game,
        [
            CloudLayer(CloudType.CUMULUS, 30, (1000, 1500), n_templates=3),
            CloudLayer(CloudType.CIRRUS, 10, (8000, 8500), n_templates=2),
        ],
    )
    assert field._n_clouds == 40
    assert field._n_per == max(
        DEFAULTS[CloudType.CUMULUS]["n_particles"],
        DEFAULTS[CloudType.CIRRUS]["n_particles"],
    )
    assert not field.node.is_empty()


def test_cloudfield_draw_order_is_permutation(game):
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS, 25, (1000, 1500), 3)], domain=8000.0
    )
    field.update(Vec3(0, 0, 1200), 1 / 60.0)
    assert sorted(field._draw_order.tolist()) == list(range(field._n_clouds))


def test_cloudfield_index_buffer_stays_valid(game):
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS, 20, (1000, 1500), 3)],
        domain=8000.0,
        resort_frames=4,
    )
    for _ in range(12):  # > resort_frames → at least one full cycle
        field.update(Vec3(0, 0, 1200), 1 / 60.0)
    assert field._stage.min() >= 0
    assert field._stage.max() < 4 * field._n  # every index points at a real vertex


def test_recycling_keeps_clouds_within_box(game):
    domain = 10000.0
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS, 50, (1000, 1500), 4)],
        domain=domain,
        wind=(0, 0, 0),
    )
    cam = Vec3(0, 0, 1200)
    for i in range(60):  # fly far beyond the box
        cam = Vec3(i * 500.0, i * 400.0, 1200)
        field.update(cam, 1 / 60.0)
    rel = np.abs(field._cloud_centres[:, :2] - np.array([cam.x, cam.y], np.float32))
    assert rel.max() <= domain * 0.5 + 1e-3


def test_wind_drifts_centroids(game):
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS, 20, (1000, 1500), 3)],
        domain=0.0,
        wind=(50.0, 0.0, 0.0),
    )  # domain 0 → no recycling
    before = field._cloud_centres.copy()
    for _ in range(3):
        field.update(Vec3(0, 0, 1200), 1.0)
    moved = field._cloud_centres - before
    np.testing.assert_allclose(moved[:, 0], 150.0, atol=1e-3)
    np.testing.assert_allclose(moved[:, 1:], 0.0, atol=1e-3)


def test_static_field_does_not_move(game):
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS, 20, (1000, 1500), 3)],
        domain=0.0,
        wind=(0, 0, 0),
    )
    assert field._dynamic is False
    before = field._cloud_centres.copy()
    for _ in range(3):
        field.update(Vec3(0, 0, 1200), 1.0)
    np.testing.assert_array_equal(field._cloud_centres, before)


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
    clouds = Clouds(
        game, layers=[CloudLayer(CloudType.CUMULUS, 10, (1000, 1500), 2)], domain=8000.0
    )

    assert clouds.id in game.method_lists
    game.method_lists[clouds.id][0]()  # the registered per-frame update
    assert not clouds.field.node.is_empty()

    clouds.clean()
    assert clouds.id not in game.method_lists
    assert clouds.field.node.is_empty()  # geometry detached
    game.root_node.remove_node()
    camera.remove_node()


# ── Defaults, determinism & tuning knobs ─────────────────────────────────────────


def test_default_layers_used_when_none(game):
    """layers=None falls back to the built-in cumulus + cirrus field."""
    field = _make_field(game, None)  # exercises _default_layers()
    assert field._n_clouds == 300 + 120  # default cumulus + cirrus counts


def test_cloudfield_deterministic(game):
    """Same seed => identical placement and draw order."""
    layers = [CloudLayer(CloudType.CUMULUS, 20, (1000, 1500), 3)]
    a = _make_field(game, layers, domain=8000.0, seed=11)
    b = _make_field(game, layers, domain=8000.0, seed=11)
    c = _make_field(game, layers, domain=8000.0, seed=12)
    np.testing.assert_array_equal(a._cloud_centres, b._cloud_centres)
    assert not np.array_equal(a._cloud_centres, c._cloud_centres)


def test_wrap_fade_band_default_and_override(game):
    layers = [CloudLayer(CloudType.CUMULUS, 5, (1000, 1500), 2)]
    default = _make_field(game, layers, domain=20000.0)
    custom = _make_field(game, layers, domain=20000.0, wrap_fade_band=1234.0)
    assert default._wrap_band == pytest.approx(0.12 * 20000.0)
    assert custom._wrap_band == pytest.approx(1234.0)


def test_update_with_zero_dt_does_not_drift(game):
    """A wind-only field (no recycling) must not move when dt == 0."""
    field = _make_field(
        game,
        [CloudLayer(CloudType.CUMULUS, 15, (1000, 1500), 2)],
        domain=0.0,
        wind=(50.0, 0.0, 0.0),
    )
    before = field._cloud_centres.copy()
    field.update(Vec3(0, 0, 1200), 0.0)
    np.testing.assert_array_equal(field._cloud_centres, before)


# ── Mixed-type ordering (the reason a single field exists) ───────────────────────


def test_mixed_layers_sorted_together_back_to_front(game):
    """Cumulus + cirrus share one Geom, so the global draw order is every cloud
    of every type sorted back-to-front by centroid distance from the camera."""
    field = _make_field(
        game,
        [
            CloudLayer(CloudType.CUMULUS, 30, (1000, 1500), 3),
            CloudLayer(CloudType.CIRRUS, 15, (8000, 8500), 2),
        ],
        domain=12000.0,
    )
    cam = Vec3(500, -300, 1400)
    field.update(cam, 1 / 60.0)

    cam_xyz = np.array([cam.x, cam.y, cam.z], np.float32)
    dist_sq = np.sum((field._cloud_centres - cam_xyz) ** 2, axis=1)
    # _draw_order must be farthest → nearest across BOTH layers together.
    expected = np.argsort(-dist_sq)
    np.testing.assert_array_equal(field._draw_order, expected)


# ── Low-yield generation (sub-sampling skipped) ──────────────────────────────────


def test_build_cloud_particles_below_target_is_not_trimmed():
    """When the carve keeps fewer than n_particles, all survivors are returned."""
    particles = build_cloud_particles(CloudType.CIRRUS, seed=1, n_particles=100000)
    assert 0 < len(particles) < 100000


# ── Per-template generator (cloud.py) ────────────────────────────────────────────


def test_build_templates_iter_matches_build_templates(atlas_rects):
    """The generator yields exactly what the list-returning wrapper produces."""
    kwargs = dict(cloud_type=CloudType.CUMULUS, density_scale=0.7, base_seed=2)
    via_list = build_templates(
        3, atlas_rects, SUN_COLOR, AMBIENT_COLOR, SUN_DIR, **kwargs
    )
    via_iter = list(
        build_templates_iter(
            3, atlas_rects, SUN_COLOR, AMBIENT_COLOR, SUN_DIR, **kwargs
        )
    )
    assert len(via_iter) == len(via_list) == 3
    for from_list, from_iter in zip(via_list, via_iter):
        for field in ("pos", "radii", "colors", "uv"):
            np.testing.assert_array_equal(from_list[field], from_iter[field])


# ── Template disk cache (cloud.py) ────────────────────────────────────────────────


def _cache_args(atlas_rects):
    """Shared keyword args for the cache-key / generator calls below."""
    return dict(
        n_templates=2,
        atlas_rects=atlas_rects,
        sun_color=SUN_COLOR,
        ambient_color=AMBIENT_COLOR,
        sun_dir=SUN_DIR,
        cloud_type=CloudType.CUMULUS,
        density_scale=0.7,
        base_seed=5,
        uv_seed=0,
        overrides=None,
    )


def test_template_cache_key_deterministic_and_sensitive(atlas_rects):
    """Same inputs give the same key; any relevant change gives a different one."""
    base = _template_cache_key(**_cache_args(atlas_rects))
    assert base == _template_cache_key(**_cache_args(atlas_rects))

    changed_seed = _cache_args(atlas_rects)
    changed_seed["base_seed"] = 6
    assert _template_cache_key(**changed_seed) != base

    changed_sun = _cache_args(atlas_rects)
    changed_sun["sun_dir"] = SUN_DIR + 1.0
    assert _template_cache_key(**changed_sun) != base


def test_template_cache_roundtrip(atlas_rects, tmp_path, monkeypatch):
    """Saved templates load back with byte-identical arrays."""
    monkeypatch.setattr(cloud_module, "_TEMPLATE_CACHE_DIR", tmp_path)
    templates = build_templates(
        2, atlas_rects, SUN_COLOR, AMBIENT_COLOR, SUN_DIR, base_seed=5
    )
    _save_cached_templates("somekey", templates)
    loaded = _load_cached_templates("somekey")

    assert loaded is not None and len(loaded) == len(templates)
    for original, restored in zip(templates, loaded):
        for field in ("pos", "radii", "colors", "uv"):
            np.testing.assert_array_equal(original[field], restored[field])


def test_template_cache_miss_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_module, "_TEMPLATE_CACHE_DIR", tmp_path)
    assert _load_cached_templates("never_written") is None


def test_build_templates_iter_writes_then_reads_cache(
    atlas_rects, tmp_path, monkeypatch
):
    """With use_cache, the first call writes one .npz and the second reads it."""
    monkeypatch.setattr(cloud_module, "_TEMPLATE_CACHE_DIR", tmp_path)
    args = _cache_args(atlas_rects)

    first = list(build_templates_iter(**args, use_cache=True))
    assert len(list(tmp_path.glob("*.npz"))) == 1  # cache file written

    second = list(build_templates_iter(**args, use_cache=True))  # cache hit
    assert len(first) == len(second) == args["n_templates"]
    for from_gen, from_cache in zip(first, second):
        for field in ("pos", "radii", "colors", "uv"):
            np.testing.assert_array_equal(from_gen[field], from_cache[field])


def test_build_templates_iter_without_cache_writes_nothing(
    atlas_rects, tmp_path, monkeypatch
):
    """use_cache defaults off, so tests and tools never touch the cache."""
    monkeypatch.setattr(cloud_module, "_TEMPLATE_CACHE_DIR", tmp_path)
    list(build_templates_iter(**_cache_args(atlas_rects)))
    assert list(tmp_path.glob("*.npz")) == []


# ── Deferred / chunked field build (field.py) ────────────────────────────────────


def test_cloudfield_defer_build_matches_immediate(game):
    """A deferred build, driven step by step, equals the immediate build."""
    layers = [CloudLayer(CloudType.CUMULUS, 15, (1000, 1500), 2)]
    immediate = _make_field(game, layers, domain=8000.0, seed=3)

    deferred = CloudField(
        parent=NodePath("deferred_parent"),
        game=game,
        layers=layers,
        domain=8000.0,
        seed=3,
        defer_build=True,
    )
    assert not hasattr(deferred, "node")  # nothing built in the constructor

    for _ in deferred.build():  # drive the generator to completion
        pass

    assert not deferred.node.is_empty()
    assert deferred._n_clouds == immediate._n_clouds
    np.testing.assert_array_equal(deferred._cloud_centres, immediate._cloud_centres)


def test_cloudfield_vertex_buffer_row_count(game):
    """The block-wise vertex buffer fills all 4 verts per particle."""
    field = _make_field(
        game, [CloudLayer(CloudType.CUMULUS, 12, (1000, 1500), 2)], domain=8000.0
    )
    vdata = field.node.node().get_geom(0).get_vertex_data()
    assert vdata.get_num_rows() == 4 * field._n
