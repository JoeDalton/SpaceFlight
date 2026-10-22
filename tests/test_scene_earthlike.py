"""
Unit tests for Mission 3's planet scene (space_flight.scenes.scenes:
SceneEarthlike, wait_until_loaded).

The loading gate and the scene's wiring run on stand-ins; the ground heights
under Mission 3 are queried from WorldBuilder's terrain (no window, no
workers). One end-to-end test builds the real planet terrain through
WorldBuilder's World, loads its ground and traverses it.
"""

import logging
import math
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
from world_builder.terrain.biomes import BIOMES
from world_builder.terrain.level import load_level
from world_builder.terrain.planet import Planet
from world_builder.terrain.query import TerrainQuery
from world_builder.world import BodyLook, World

from space_flight.game.collisions import CollisionLayers
from space_flight.game.levels import mission3_level as mission3
from space_flight.scenes import scenes
from space_flight.scenes.scenes import (
    Scene,
    SceneEarthlike,
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

    yielded = sum(1 for _ in wait_until_loaded(lambda: world.loading, step, clock))
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

    def test_gives_up_after_the_timeout(self, caplog):
        clock = FakeClock()
        with caplog.at_level(logging.WARNING):
            _gate([True], clock, dt=1.0)
        assert clock.now == pytest.approx(scenes.WORLD_TIMEOUT_S)
        assert "still loading" in caplog.text


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def test_scene_factory_knows_the_earthlike_planet():
    assert isinstance(scene_factory(game=None, scene_name="earthlike_planet"), Scene)


def test_earthlike_level_file_is_a_world_builder_level():
    spec, _pose = load_level(SceneEarthlike.LEVEL_PATH)
    assert spec.name == "earthlike"
    assert spec.has_ocean


def test_the_planet_and_its_moon():
    """The planet's centre is one radius below the origin, with air, clouds
    and the swell ocean; the airless moon hangs in the northern sky."""
    planet, moon = SceneEarthlike(game=None).bodies()
    radius = planet.spec.radius
    assert planet.name == "planet"
    assert planet.position == pytest.approx((0.0, 0.0, -radius))
    assert planet.atmosphere is not None
    assert planet.clouds is SceneEarthlike.CLOUDS
    assert planet.ocean is SceneEarthlike.OCEAN

    assert moon.name == "moon" and moon.atmosphere is None
    offset = np.array(moon.position) - planet.position
    assert np.linalg.norm(offset) == pytest.approx(SceneEarthlike.MOON_DISTANCE_M)
    assert math.degrees(math.acos(offset[2] / np.linalg.norm(offset))) == (
        pytest.approx(SceneEarthlike.MOON_ZENITH_ANGLE_DEG)
    )
    assert offset[1] > 0.0 and offset[0] == 0.0  # north, ahead of the convoy


def _scene(monkeypatch):
    """A SceneEarthlike over a stand-in game, its World a mock."""
    world_class = MagicMock()
    monkeypatch.setattr(scenes, "World", world_class)
    position = np.array([10.0, 20.0, 30.0])
    game = SimpleNamespace(
        app=SimpleNamespace(
            graphics_settings=SimpleNamespace(world_settings=lambda: "settings")
        ),
        game_time=SimpleNamespace(get_current_time=lambda: 4.0),
        player=SimpleNamespace(pawn=SimpleNamespace(position=position)),
        depth_far=123456.0,
    )
    return SceneEarthlike(game=game), world_class, position


def test_the_world_is_built_with_the_scenes_look(monkeypatch):
    scene, world_class, _ = _scene(monkeypatch)
    scene.build_upfront()

    args, kwargs = world_class.call_args
    assert args[0] is scene.game.app
    assert [body.name for body in args[1]] == ["planet", "moon"]
    assert kwargs["sun"] is SceneEarthlike.SUN
    assert kwargs["sky"] is SceneEarthlike.SKY
    assert kwargs["settings"] == "settings"
    assert kwargs["light_scale"] == SceneEarthlike.LIGHT_SCALE
    assert kwargs["clock"]() == 4.0  # the game's clock
    scene.world.enable_collision.assert_called_once_with(
        CollisionLayers.TERRAIN_INTO, bodies=["planet"]
    )


def test_the_world_follows_the_player(monkeypatch):
    """Render's origin is the player: the world is updated around it, its sky
    inside the far camera's range."""
    scene, _, position = _scene(monkeypatch)
    scene.build_upfront()

    scene.update_after_recenter()
    scene.depth_ranges()

    scene.world.update.assert_called_once_with(position, far=123456.0)
    scene.world.depth_ranges.assert_called_once_with(position)


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
    spec, _pose = load_level(SceneEarthlike.LEVEL_PATH)
    planet = Planet(spec)
    query = TerrainQuery(planet, include_ocean=True, level=planet.grid.max_level)
    points = _mission3_points()
    # World frame -> planet frame: the planet's centre is one radius below
    planet_points = points + np.array([0.0, 0.0, spec.radius])
    altitude = np.linalg.norm(planet_points, axis=1) - spec.radius
    ground = query.height_at(planet_points)
    assert (altitude - ground).min() > MISSION3_CLEARANCE_M


# ---------------------------------------------------------------------------
# Collision, end to end
# ---------------------------------------------------------------------------

# Where the smoke test's player hovers (the sea under it is at z = 0)
_HOVER = np.array([0.0, 0.0, 1000.0])


def test_planet_terrain_is_solid_to_a_laser(spaceflight_app):
    """
    The planet's terrain, built by World as the scene does and loaded around
    the player, stops a laser-masked segment fired straight down: one
    "terrain" entry, on the low ground or sea under the origin, facing up,
    whose owner knows its material.

    The drawn mesh, not the finest one, is solid: at this altitude its coarser
    triangles put the ground a few metres off the finest level's.
    """
    native = pytest.importorskip("world_builder.terrain.native")
    planet = SceneEarthlike(game=None).bodies()[0]
    bare = BodyLook(planet.name, planet.spec, position=planet.position)
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
        segment.add_solid(CollisionSegment(0, 0, -900, 0, 0, -1100))
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
        assert point.z == pytest.approx(-1000.0, abs=30.0)
        assert entry.get_surface_normal(spaceflight_app.render).z > 0.9
        owner = entry.get_into_node_path().get_python_tag("owner")
        assert owner.material_at(point, spaceflight_app.render) in {"water", *BIOMES}
        root.remove_node()
    finally:
        world.destroy()
