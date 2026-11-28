"""
Unit tests for the planet scene of Mission 3 and Free Flight
(space_flight.scenes.scenes: SceneSolarSystem, wait_until_loaded).

The loading gate and the scene's wiring run on stand-ins; the ground heights
under Mission 3 are queried from WorldBuilder's terrain (no window, no
workers). One end-to-end test builds the real planet terrain through
WorldBuilder's World, loads its ground and traverses it.
"""

import logging
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import (
    BitMask32,
    CollisionHandlerQueue,
    CollisionNode,
    CollisionSegment,
    CollisionTraverser,
)
from world_builder import parse_world
from world_builder.settings import WorldSettings
from world_builder.terrain.biomes import BIOMES
from world_builder.terrain.planet import Planet
from world_builder.terrain.query import TerrainQuery
from world_builder.world import BodyLook, World

from space_flight.game.collisions import CollisionLayers
from space_flight.game.levels import mission3_level as mission3
from space_flight.scenes import scenes
from space_flight.scenes.scenes import (
    Scene,
    SceneSolarSystem,
    scene_factory,
    wait_until_loaded,
)


class FakeClock:
    """A clock advanced by hand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _gate(loading: list[bool], clock: FakeClock, dt: float = 0.125):
    """
    A loading gate over a world whose loading flag follows *loading*, one
    value per step (the last repeats), the clock advancing *dt* each.

    :return: (the steps it yields, the number of steps taken)
    """
    states = iter(loading)
    world = SimpleNamespace(loading=True, steps=0)

    def step():
        world.steps += 1
        world.loading = next(states, loading[-1])
        clock.now += dt

    pauses = []
    yielded = sum(
        1 for _ in wait_until_loaded(lambda: world.loading, step, clock, pauses.append)
    )
    world.pauses = pauses
    return yielded, world.steps


# ---------------------------------------------------------------------------
# Loading gate
# ---------------------------------------------------------------------------


class TestWaitUntilLoaded:
    def test_ends_once_quiet_for_the_quiet_time(self):
        clock = FakeClock()
        yielded, steps = _gate([True, True, False], clock)
        # Two loading steps, then quiet from the third (0.375 s) on
        assert clock.now == 0.375 + scenes.WORLD_QUIET_S
        assert yielded == steps - 1

    def test_one_quiet_frame_is_not_enough(self):
        clock = FakeClock()
        _gate([False, True, True, False], clock)
        # Quiet again from the fourth step (0.5 s) on
        assert clock.now == 0.5 + scenes.WORLD_QUIET_S

    def test_yields_to_the_workers_while_loading(self):
        """A step still loading sleeps a little (the workers' results come
        back through this process); once quiet, no more."""
        clock = FakeClock()
        states = iter([True, True, False])
        world = SimpleNamespace(loading=True)
        pauses = []

        def step():
            world.loading = next(states, False)
            clock.now += 0.125

        for _ in wait_until_loaded(lambda: world.loading, step, clock, pauses.append):
            pass
        assert pauses == [scenes.LOADING_YIELD_S] * 2

    def test_gives_up_after_the_timeout(self, caplog):
        clock = FakeClock()
        with caplog.at_level(logging.WARNING):
            _gate([True], clock, dt=1.0)
        assert clock.now == pytest.approx(scenes.WORLD_TIMEOUT_S)
        assert "still loading" in caplog.text


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def test_scene_factory_knows_the_solar_system():
    assert isinstance(
        scene_factory(game=None, scene_name="solar_system"), SceneSolarSystem
    )


# ---------------------------------------------------------------------------
# The world file
# ---------------------------------------------------------------------------


def test_the_world_file_is_the_solar_system():
    """The home planet with its air, clouds and sea, its airless moon, an ice
    planet and its ring: all defined by the file."""
    world = parse_world(SceneSolarSystem.WORLD_PATH)
    planet, moon = world.bodies
    assert [planet.name, moon.name] == ["planet", "moon"]
    assert planet.atmosphere is not None
    assert planet.clouds is not None and planet.clouds.cirrus is not None
    assert planet.ocean is not None and planet.spec.has_ocean
    assert moon.atmosphere is None
    assert world.sky is not None


def test_the_world_file_brings_every_file_it_needs():
    """The linked body files and the stamps and paints images are all in the
    world's folder (it moves as a whole)."""
    folder = SceneSolarSystem.WORLD_PATH.parent
    text = "".join(path.read_text() for path in folder.glob("*.yaml"))
    linked = set(re.findall(r"file:\s*([\w.]+\.yaml)", text))
    images = set(re.findall(r"(?:heightmap|mask):\s*(\S+\.png)", text))
    assert linked >= {"kerbin.yaml", "moon.yaml", "ice.yaml", "ring.yaml", "sky.yaml"}
    assert images
    for name in linked | images:
        assert (folder / name).is_file(), name


def test_the_level_frame_is_the_planets():
    """Chart positions are placed around the planet's centre, wherever the
    file puts it."""
    planet = parse_world(SceneSolarSystem.WORLD_PATH).bodies[0]
    frame = SceneSolarSystem.level_frame()
    assert frame.radius == planet.spec.radius
    assert frame.centre == pytest.approx(planet.position)
    reference = frame.position(0, 0, 0)
    assert np.linalg.norm(reference - frame.centre) == pytest.approx(frame.radius)
    assert SceneSolarSystem(game=None).default_up_direction == pytest.approx(frame.up)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def _scene(monkeypatch):
    """A SceneSolarSystem over a stand-in game, its loaded world a mock."""
    game_world = SimpleNamespace(
        world=MagicMock(), depth=MagicMock(), update=MagicMock()
    )
    load = MagicMock(return_value=game_world)
    monkeypatch.setattr(scenes, "load_world", load)
    position = np.array([10.0, 20.0, 30.0])
    game = SimpleNamespace(
        app=SimpleNamespace(
            graphics_settings=SimpleNamespace(world_settings=lambda: "settings")
        ),
        game_time=SimpleNamespace(get_current_time=lambda: 4.0),
        player=SimpleNamespace(pawn=SimpleNamespace(position=position)),
    )
    return SceneSolarSystem(game=game), load, position


def test_the_world_is_loaded_from_its_file_as_the_game_runs_it(monkeypatch):
    scene, load, _ = _scene(monkeypatch)
    scene.build_upfront()

    args, kwargs = load.call_args
    assert args == (scene.game.app, SceneSolarSystem.WORLD_PATH)
    assert kwargs["settings"] == "settings"
    assert kwargs["clock"]() == 4.0  # the game's clock
    assert kwargs["light_scale"] == SceneSolarSystem.LIGHT_SCALE
    # The light at the ships is reckoned every few frames
    assert kwargs["light_period"] == scenes.LIGHT_PERIOD_FRAMES
    assert scene.world is scene.game_world.world
    assert scene.depth is scene.game_world.depth
    # Every terrain is solid (the moon and the ring too), WorldBuilder's doing
    assert load.call_args.kwargs["collision_mask"] == CollisionLayers.TERRAIN_INTO
    scene.world.enable_collision.assert_not_called()


def test_the_world_follows_the_player(monkeypatch):
    """Render's origin is the player: the world (and its depth camera) is
    updated around it."""
    scene, _, position = _scene(monkeypatch)
    scene.build_upfront()

    scene.update_after_recenter()

    scene.game_world.update.assert_called_once_with(position)


def test_the_scene_uses_the_worlds_depth_camera_as_it_is(monkeypatch):
    """One reversed camera (WorldBuilder #57): nothing of the game's to add
    to its update (no split to keep clear of the shield bubbles any more)."""
    scene, load, _ = _scene(monkeypatch)
    update = load.return_value.depth.update
    scene.build_upfront()

    assert scene.depth.update is update


def test_the_mirror_takes_the_depth_cameras_convention(monkeypatch):
    """The rear-view mirror draws the scene with its own camera: it takes
    the world's camera's depth mode, and the standard one back when the
    camera goes."""
    from world_builder.depth import DEPTH_STANDARD

    scene, load, _ = _scene(monkeypatch)
    mirror = MagicMock()
    scene.game.player.rear_view_mirror = mirror
    scene.build_upfront()

    mirror.set_depth_mode.assert_called_once_with(load.return_value.depth.mode)
    scene.release_depth()
    mirror.set_depth_mode.assert_called_with(DEPTH_STANDARD)


def test_without_a_window_the_scene_has_no_depth_camera(monkeypatch):
    """Headless (no window), load_world builds no depth camera: the scene
    keeps none, leaves the mirror alone, and releases nothing."""
    scene, load, _ = _scene(monkeypatch)
    load.return_value.depth = None
    mirror = MagicMock()
    scene.game.player.rear_view_mirror = mirror
    scene.build_upfront()

    assert scene.depth is None
    mirror.set_depth_mode.assert_not_called()
    scene.release_depth()
    mirror.set_depth_mode.assert_not_called()


def test_cleaning_removes_the_depth_camera_once_before_the_world(monkeypatch):
    scene, _, _ = _scene(monkeypatch)
    scene.build_upfront()
    scene.speed_dust_cloud = MagicMock()
    order = []
    depth, world = scene.depth, scene.world
    depth.destroy.side_effect = lambda: order.append("depth")
    world.destroy.side_effect = lambda: order.append("world")

    scene.release_depth()  # FlightState.exit, before the render pipeline goes
    scene.clean()

    assert order == ["depth", "world"]
    assert scene.world is None and scene.game_world is None


def test_the_graphics_settings_light_the_world_with_every_shadow():
    """The saved quality (high by default) draws the mountains', the clouds'
    and the objects' shadows: a model tracked as the scene does receives
    the terrain's, the clouds' and the bodies' shadows and casts its own."""
    import yaml

    from space_flight.global_architecture.graphics_settings import (
        DEFAULT_GRAPHICS_FILE,
    )

    config = yaml.safe_load(DEFAULT_GRAPHICS_FILE.read_text())
    settings = WorldSettings.from_dict(config["world"])
    shadows = settings.shadows
    assert shadows.terrain_map_size > 0
    assert shadows.cloud_map_size > 0
    assert shadows.cloud_shadow_steps > 0
    assert shadows.object_shadows
    assert SceneSolarSystem.MODELS_CAST_SHADOWS
    assert SceneSolarSystem.MODELS_USE_WORLD_SHADER


# ---------------------------------------------------------------------------
# Mission 3 over the planet
# ---------------------------------------------------------------------------

# Clearance kept between Mission 3's ships and the ground or sea
MISSION3_CLEARANCE_M = 150.0


def _mission3_points() -> np.ndarray:
    """:return: Every spawn point and waypoint of Mission 3, the player's
    included, with points every 250 m along each route"""
    points = [np.array(mission3.PLAYER_POSITION, dtype=float)]
    for wave in (
        mission3.TRANSPORTS,
        mission3.ESCORT,
        mission3.FIRST_WAVE,
        mission3.SECOND_WAVE,
        mission3.THIRD_WAVE,
        mission3.FOURTH_WAVE,
    ):
        route = [np.array(p, dtype=float) for p in [wave.spawn_point, *wave.waypoints]]
        for a, b in zip(route, route[1:]):
            n = max(1, int(np.linalg.norm(b - a) // 250))
            points += [a + (b - a) * t for t in np.linspace(0, 1, n + 1)]
    return np.array(points)


def test_mission3_starts_clear_of_the_ground():
    """Every Mission 3 ship and route is above the ground and the sea, on the
    finest terrain level."""
    body = parse_world(SceneSolarSystem.WORLD_PATH).bodies[0]
    spec = body.spec
    scenes_frame = SceneSolarSystem.level_frame()
    planet = Planet(spec)
    query = TerrainQuery(planet, include_ocean=True, level=planet.grid.max_level)
    points = _mission3_points()
    # World frame -> planet frame
    planet_points = points - scenes_frame.centre
    altitude = np.linalg.norm(planet_points, axis=1) - spec.radius
    ground = query.height_at(planet_points)
    assert (altitude - ground).min() > MISSION3_CLEARANCE_M


# ---------------------------------------------------------------------------
# Collision, end to end
# ---------------------------------------------------------------------------

# Where the smoke test's player hovers (the sea under it is at z = 0)
# 1000 m above the sea north-east of the coast (chart metres)
_HOVER = SceneSolarSystem.level_frame().position(4000.0, 8000.0, 1000.0)


def test_planet_terrain_is_solid_to_a_laser(spaceflight_app):
    """
    The planet's terrain, built by World as the world file defines it, loaded around
    the player, stops a laser-masked segment fired straight down: one
    "terrain" entry, on the low ground or sea under the origin, facing up,
    whose owner knows its material.

    The drawn mesh, not the finest one, is solid: at this altitude its coarser
    triangles put the ground a few metres off the finest level's.
    """
    native = pytest.importorskip("world_builder.terrain.native")
    planet = parse_world(SceneSolarSystem.WORLD_PATH).bodies[0]
    bare = BodyLook(
        planet.name, planet.spec, position=planet.position, mass=planet.mass
    )
    world = World(spaceflight_app, [bare], lights=False)
    try:
        try:
            world.enable_collision(CollisionLayers.TERRAIN_INTO)
        except native.NativeCollisionError as error:
            pytest.skip(f"No native terrain collision: {error}")
        for _ in wait_until_loaded(lambda: world.loading, lambda: world.update(_HOVER)):
            pass

        # The player is at the render origin: the sea is 1000 m below it
        root = spaceflight_app.render.attach_new_node("smoke_root")
        segment = CollisionNode("laser")
        up = SceneSolarSystem.level_frame().up_at(_HOVER)
        segment.add_solid(CollisionSegment(*(-900 * up), *(-1100 * up)))
        segment.set_from_collide_mask(CollisionLayers.MUNITION_FROM)
        segment.set_into_collide_mask(BitMask32.all_off())
        segment_path = root.attach_new_node(segment)
        queue = CollisionHandlerQueue()
        traverser = CollisionTraverser()
        traverser.add_collider(segment_path, queue)
        traverser.traverse(spaceflight_app.render)

        entries = [queue.get_entry(i) for i in range(queue.get_num_entries())]
        assert [e.get_into_node().name for e in entries] == ["terrain"]
        entry = entries[0]
        point = entry.get_surface_point(spaceflight_app.render)
        assert np.dot(point, up) == pytest.approx(-1000.0, abs=30.0)
        assert np.dot(entry.get_surface_normal(spaceflight_app.render), up) > 0.9
        owner = entry.get_into_node_path().get_python_tag("owner")
        assert owner.material_at(point, spaceflight_app.render) in {"water", *BIOMES}
        root.remove_node()
    finally:
        world.destroy()


def test_scene_up_follows_minus_gravity_or_defaults_to_world_z():
    from types import SimpleNamespace

    from space_flight.scenes.scenes import Scene

    scene = Scene(game=None)
    default = np.array([0, 0, 1])
    # No world, or no bodies: world +Z
    assert np.array_equal(scene.up_at([5.0, 5.0, 5.0]), default)
    scene.world = SimpleNamespace(
        bodies=[1],
        gravity_field=lambda: SimpleNamespace(
            acceleration=lambda p: -np.asarray(p) * 20
        ),
    )
    up = scene.up_at([3.0, 0.0, 4.0])
    assert np.allclose(up, [0.6, 0.0, 0.8])
    # Negligible gravity: world +Z
    scene._gravity = SimpleNamespace(acceleration=lambda p: np.zeros(3))
    scene._up = None  # reckoned again
    assert np.array_equal(scene.up_at([3.0, 0.0, 4.0]), default)


def test_scene_up_is_reckoned_at_the_player_and_kept_a_while(monkeypatch):
    """Up is the player's for every position, reckoned again once
    UP_REFRESH_S has passed."""
    from types import SimpleNamespace

    from space_flight.scenes.scenes import UP_REFRESH_S, Scene

    now = [100.0]
    monkeypatch.setattr(scenes.time, "monotonic", lambda: now[0])
    pawn = SimpleNamespace(position=np.array([0.0, 0.0, 10.0]))
    scene = Scene(game=SimpleNamespace(player=SimpleNamespace(pawn=pawn)))
    calls = []

    def acceleration(p):
        calls.append(np.array(p))
        return -np.asarray(p, dtype=float)

    scene.world = SimpleNamespace(
        bodies=[1], gravity_field=lambda: SimpleNamespace(acceleration=acceleration)
    )
    # Anywhere: the player's up
    assert np.allclose(scene.up_at([10.0, 0.0, 0.0]), [0.0, 0.0, 1.0])
    assert np.allclose(scene.up_at([0.0, 10.0, 0.0]), [0.0, 0.0, 1.0])
    assert len(calls) == 1
    # A second later, where the player is now
    pawn.position = np.array([10.0, 0.0, 0.0])
    now[0] += UP_REFRESH_S
    assert np.allclose(scene.up_at([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0])
    assert len(calls) == 2


def _node_scene(tracked_nodes=()):
    """A Scene over a stand-in world that records track_light calls."""
    from panda3d.core import NodePath

    scene = Scene(game=None)
    calls = []
    tracked = list(tracked_nodes)

    def track_light(node, cast, shader):
        calls.append((node, cast, shader))
        tracked.append(node)

    scene.world = SimpleNamespace(
        tracked=SimpleNamespace(nodes=tracked),
        track_light=track_light,
    )
    return scene, calls, NodePath


def test_scene_tracks_anchored_models_to_cast_shadows():
    scene, calls, NodePath = _node_scene()
    ship = NodePath("ship_node")
    scene.track_model(ship)
    assert calls == [(ship, True, True)]


def test_scene_tracks_a_hierarchy_once():
    """Turrets and props anchored below a tracked ship follow it."""
    scene, calls, NodePath = _node_scene()
    ship = NodePath("ship_node")
    mount = ship.attach_new_node("mount")
    scene.track_model(ship)
    scene.track_model(ship)
    scene.track_model(mount)
    assert [call[0] for call in calls] == [ship]


def test_scene_without_a_world_tracks_nothing():
    from panda3d.core import NodePath

    Scene(game=None).track_model(NodePath("ship_node"))  # no error
