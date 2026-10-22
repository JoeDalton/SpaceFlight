"""
Unit tests for the planet terrain scene (space_flight.scenes.planet_surface,
space_flight.scenes.scenes.SceneEarthlike).

The ground-loading gate runs on a fake terrain; the ground heights under
Mission 3 are queried from WorldBuilder's terrain (no window, no workers). One
end-to-end test builds the real terrain, loads its ground and traverses it.
"""

import logging
from types import SimpleNamespace

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

from space_flight.game.collisions import CollisionLayers
from space_flight.game.levels import mission3_level as mission3
from space_flight.scenes import planet_surface
from space_flight.scenes.planet_surface import PlanetSurface
from space_flight.scenes.scenes import Scene, SceneEarthlike, scene_factory


class FakeClock:
    """A clock advanced by hand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _surface(loading: list[bool], clock: FakeClock, dt: float = 0.125):
    """
    A PlanetSurface over a fake terrain whose loading flag follows *loading*,
    one value per update (the last repeats), the clock advancing *dt* each.
    """
    surface = object.__new__(PlanetSurface)
    states = iter(loading)
    terrain = SimpleNamespace(loading=True, updates=[])

    def update(position):
        terrain.updates.append(position)
        terrain.loading = next(states, loading[-1])
        clock.now += dt

    terrain.update = update
    surface.terrain = terrain
    return surface


def _run(surface, clock) -> int:
    """:return: The steps the ground wait yields before it ends"""
    return sum(1 for _ in surface.wait_until_loaded(np.zeros(3), clock=clock))


# ---------------------------------------------------------------------------
# Ground loading gate
# ---------------------------------------------------------------------------


class TestWaitUntilLoaded:
    def test_ends_once_quiet_for_the_quiet_time(self):
        clock = FakeClock()
        surface = _surface([True, True, False], clock)
        steps = _run(surface, clock)
        # Two loading steps, then quiet from the third (0.375 s) on
        assert clock.now == 0.375 + planet_surface.GROUND_QUIET_S
        assert steps == len(surface.terrain.updates) - 1

    def test_one_quiet_frame_is_not_enough(self):
        clock = FakeClock()
        surface = _surface([False, True, True, False], clock)
        _run(surface, clock)
        # Quiet again from the fourth step (0.5 s) on
        assert clock.now == 0.5 + planet_surface.GROUND_QUIET_S

    def test_updates_around_the_player(self):
        clock = FakeClock()
        surface = _surface([False], clock)
        position = np.array([1.0, 2.0, 3.0])
        list(surface.wait_until_loaded(position, clock=clock))
        assert all(p is position for p in surface.terrain.updates)

    def test_gives_up_after_the_timeout(self, caplog):
        clock = FakeClock()
        surface = _surface([True], clock, dt=1.0)
        with caplog.at_level(logging.WARNING):
            _run(surface, clock)
        assert clock.now == pytest.approx(planet_surface.GROUND_TIMEOUT_S)
        assert "still loading" in caplog.text


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


def test_scene_factory_knows_the_earthlike_planet():
    assert isinstance(scene_factory(game=None, scene_name="earthlike_planet"), Scene)


def test_scenes_update_nothing_after_recenter_by_default():
    Scene(game=None).update_after_recenter()


def test_earthlike_scene_updates_the_terrain_around_the_player():
    position = np.array([10.0, 20.0, 30.0])
    scene = SceneEarthlike(game=SimpleNamespace(player=SimpleNamespace()))
    scene.game.player.pawn = SimpleNamespace(position=position)
    scene.planet = SimpleNamespace(updates=[])
    scene.planet.update = scene.planet.updates.append
    scene.update_after_recenter()
    assert scene.planet.updates == [position]


def test_earthlike_level_file_is_a_world_builder_level():
    spec, _pose = load_level(SceneEarthlike.LEVEL_PATH)
    assert spec.name == "earthlike"
    assert spec.has_ocean


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
    The real terrain, once its ground is loaded, stops a laser-masked segment
    fired straight down: one "terrain" entry, on the low ground or sea under
    the origin, facing up, whose owner knows its material.

    The drawn mesh, not the finest one, is solid: at this altitude its coarser
    triangles put the ground a few metres off the finest level's.
    """
    native = pytest.importorskip("world_builder.terrain.native")
    game = SimpleNamespace(app=spaceflight_app)
    try:
        surface = PlanetSurface(
            game, SceneEarthlike.LEVEL_PATH, sun_direction=np.array([0, 0, 1.0])
        )
    except native.NativeCollisionError as error:
        pytest.skip(f"No native terrain collision: {error}")
    try:
        for _ in surface.wait_until_loaded(_HOVER):
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
        surface.clean()
