"""
Unit tests for the space scenes (space_flight.scenes.scenes: SceneSpace,
SceneAsteroids, SceneLavaPlanet, SceneDebug) and Missions 1 and 2 in their
asteroid field.

The scenes' wiring runs on stand-ins (WorldBuilder's World and AsteroidField
mocked); the missions' room in the field is checked against the field's own
rocks (WorldBuilder's scatter: no window, no workers). One end-to-end test
builds the real field and traverses it.
"""

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
from world_builder.asteroids.scatter import Scatter

from space_flight import CAMERA_FAR_M
from space_flight.game.collisions import CollisionLayers
from space_flight.game.levels import mission1_level as mission1
from space_flight.game.levels import mission2_level as mission2
from space_flight.game.levels.common import route_keep_outs
from space_flight.scenes import scenes
from space_flight.scenes.scenes import (
    Scene,
    SceneAsteroids,
    SceneDebug,
    SceneLavaPlanet,
    SceneSpace,
    scene_factory,
)

# ---------------------------------------------------------------------------
# Missions 1 and 2 in the field
# ---------------------------------------------------------------------------

# Room kept between the missions' ships and the rocks (under the keep-outs')
CLEARANCE_M = 150.0


def _route_points(route, step: float = 250.0) -> list[np.ndarray]:
    """:return: The route's points, and points every *step* along its legs"""
    route = [np.array(p, dtype=float) for p in route]
    points = [route[0]]
    for a, b in zip(route, route[1:]):
        n = max(1, int(np.linalg.norm(b - a) // step))
        points += [a + (b - a) * t for t in np.linspace(0, 1, n + 1)[1:]]
    return points


def _mission1_points() -> list[np.ndarray]:
    m = mission1
    return [
        *_route_points([m.PLAYER_SPAWN_POINT, m.WAYPOINT_1, m.CIRCUIT_WAYPOINTS[0]]),
        *_route_points([*m.CIRCUIT_WAYPOINTS, m.CIRCUIT_WAYPOINTS[0]]),
        *_route_points(m.RACE_WAYPOINTS),
    ]


def _mission2_points() -> list[np.ndarray]:
    m = mission2
    return [
        *_route_points(
            [m.PLAYER_SPAWN_POINT, m.BLUE_SPAWN_POINT, m.PATROL_WAYPOINTS[0]]
        ),
        *_route_points([*m.PATROL_WAYPOINTS, m.PATROL_WAYPOINTS[0]]),
        *_route_points([m.CONVOY_SPAWN_POINT, *m.CONVOY_ROUTE]),
    ]


@pytest.mark.parametrize(
    "mission,points",
    [(mission1, _mission1_points), (mission2, _mission2_points)],
    ids=["mission1", "mission2"],
)
def test_the_missions_routes_are_clear_of_rocks(mission, points):
    """Every spawn point and route of the mission is clear of the field's
    rocks, its keep-outs in place; rocks still stand near the routes."""
    field = Scatter(SceneAsteroids.FIELD, keep_outs=tuple(mission.KEEP_OUTS))
    for point in points():
        assert field.is_clear(point, CLEARANCE_M), point
    near = sum(len(field.rocks_near(p, 1000.0)) for p in points())
    assert near > 0  # "Big rock, two o'clock"


def test_without_keep_outs_the_routes_would_meet_rocks():
    """The keep-outs matter: the bare field has rocks on the routes."""
    field = Scatter(SceneAsteroids.FIELD)
    blocked = [p for p in _mission2_points() if not field.is_clear(p, CLEARANCE_M)]
    assert blocked


def test_route_keep_outs():
    legs = route_keep_outs([[0, 0, 0], [100, 0, 0], [100, 100, 0]], 50.0, loop=True)
    assert [(k.centre, k.end) for k in legs] == [
        ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0)),
        ((100.0, 0.0, 0.0), (100.0, 100.0, 0.0)),
        ((100.0, 100.0, 0.0), (0.0, 0.0, 0.0)),
    ]
    assert all(k.radius == 50.0 for k in legs)
    (ball,) = route_keep_outs([[1, 2, 3]], 10.0)
    assert ball.centre == (1.0, 2.0, 3.0) and ball.end is None


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


def test_scene_factory_knows_every_space_scene():
    keep_outs = route_keep_outs([[0, 0, 0]], 10.0)
    asteroids = scene_factory(game=None, scene_name="asteroids", keep_outs=keep_outs)
    assert isinstance(asteroids, SceneAsteroids)
    assert asteroids.keep_outs == tuple(keep_outs)
    assert isinstance(
        scene_factory(game=None, scene_name="lava_planet"), SceneLavaPlanet
    )
    assert isinstance(scene_factory(game=None, scene_name="debug"), SceneDebug)
    with pytest.raises(NotImplementedError):
        scene_factory(game=None, scene_name="nowhere")


def test_a_scene_without_obstacles_keeps_positions():
    position = Scene(game=None).clear_position([1.0, 2.0, 3.0], 100.0)
    np.testing.assert_array_equal(position, [1.0, 2.0, 3.0])


def _game(mirror: bool = True):
    position = np.array([10.0, 20.0, 30.0])
    player = SimpleNamespace(pawn=SimpleNamespace(position=position))
    player.rear_view_mirror = SimpleNamespace(mirror_np="mirror") if mirror else None
    world_settings = SimpleNamespace(asteroids="asteroid settings")
    return SimpleNamespace(
        app=SimpleNamespace(
            graphics_settings=SimpleNamespace(world_settings=lambda: world_settings),
            cam="main camera",
        ),
        game_time=SimpleNamespace(get_current_time=lambda: 4.0),
        player=player,
        depth_far=123456.0,
        follow_render_origin=MagicMock(),
    )


def _mock_parts(monkeypatch):
    world_class, field_class = MagicMock(), MagicMock()
    monkeypatch.setattr(scenes, "World", world_class)
    monkeypatch.setattr(scenes, "AsteroidField", field_class)
    world_class.return_value.camera_render.return_value = np.array([0.0, 1.0, 0.0])
    return world_class, field_class


@pytest.mark.parametrize("kind", [SceneDebug, SceneAsteroids, SceneLavaPlanet])
def test_space_is_a_world_without_bodies(monkeypatch, kind):
    """The sky, the sun and the lights of WorldBuilder's World, no planet,
    on the game's clock."""
    world_class, _ = _mock_parts(monkeypatch)
    scene = kind(game=_game())
    scene.build_upfront()

    args, kwargs = world_class.call_args
    assert args[0] is scene.game.app
    assert list(args[1]) == []
    assert kwargs["sun"] is kind.SUN
    assert kwargs["sky"] is kind.SKY
    assert kwargs["light_scale"] == kind.LIGHT_SCALE
    assert kwargs["space_ambient"] == kind.AMBIENT
    assert kwargs["clock"]() == 4.0  # the game's clock


def test_the_lava_planet_has_its_own_backdrop_not_a_sky():
    assert SceneLavaPlanet.SKY is None and SceneAsteroids.SKY is not None
    assert SceneLavaPlanet.FIELD != SceneAsteroids.FIELD


def test_the_field_is_built_as_the_ships_are_lit(monkeypatch):
    world_class, field_class = _mock_parts(monkeypatch)
    keep_outs = route_keep_outs([[0, 0, 0]], 10.0)
    scene = SceneAsteroids(game=_game(), keep_outs=keep_outs)
    scene.build_upfront()

    args, kwargs = field_class.call_args
    assert args == (scene.game.app, SceneAsteroids.FIELD)
    assert kwargs["clock"]() == 4.0  # the game's clock: a pause stops the rocks
    assert kwargs["settings"] == "asteroid settings"
    assert kwargs["keep_outs"] == tuple(keep_outs)
    assert kwargs["executor"] is world_class.return_value.executor  # one pool
    assert kwargs["tonemap"] is False  # as Panda3D's fixed-function lights
    scale = SceneAsteroids.LIGHT_SCALE
    np.testing.assert_allclose(
        kwargs["sun_color"], np.array(SceneAsteroids.SUN.color) * scale
    )
    np.testing.assert_allclose(
        kwargs["ambient"], np.array(SceneAsteroids.AMBIENT) * scale
    )
    assert kwargs["far"] == CAMERA_FAR_M
    scene.field.enable_collision.assert_called_once_with(
        CollisionLayers.TERRAIN_INTO,
        name="terrain",  # the terrain's collision events and handlers
        max_distance=SceneAsteroids.COLLISION_DISTANCE_M,
    )


@pytest.mark.parametrize("mirror", [True, False])
def test_the_field_follows_the_player_for_every_view(monkeypatch, mirror):
    """Render's origin is the player: the sky and the field are updated
    around the camera there, the field for the main view and the mirror's."""
    world_class, _ = _mock_parts(monkeypatch)
    scene = SceneAsteroids(game=_game(mirror=mirror))
    scene.build_upfront()

    scene.update_after_recenter()

    position = scene.game.player.pawn.position
    scene.world.update.assert_called_once_with(position, far=123456.0)
    (camera_world, camera_render), kwargs = scene.field.update.call_args
    np.testing.assert_allclose(camera_world, position + [0.0, 1.0, 0.0])
    np.testing.assert_allclose(camera_render, [0.0, 1.0, 0.0])
    expected = ["main camera", "mirror"] if mirror else ["main camera"]
    assert kwargs["cameras"] == expected


def test_loading_waits_for_the_rock_shapes(monkeypatch):
    _mock_parts(monkeypatch)
    monkeypatch.setattr(scenes, "SpeedDustCloud", MagicMock())
    monkeypatch.setattr(scenes, "WORLD_QUIET_S", 0.0)
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()
    loading = iter([True, True, False])
    type(scene.field).loading = property(lambda _: next(loading, False))

    steps = list(scene.build_decomposed())

    assert steps[0] == "dust"
    assert steps.count("world") >= 2  # held while the field loads
    assert scene.game.follow_render_origin.call_count >= 3


def test_ships_spawned_at_run_time_find_room(monkeypatch):
    _mock_parts(monkeypatch)
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()
    find_clear = scene.field.scatter.find_clear
    find_clear.return_value = np.array([5.0, 6.0, 7.0])

    got = scene.clear_position([1.0, 2.0, 3.0], 120.0)

    np.testing.assert_array_equal(got, [5.0, 6.0, 7.0])
    (point, radius, search), _ = find_clear.call_args
    np.testing.assert_array_equal(point, [1.0, 2.0, 3.0])
    assert radius == 120.0 and search == SceneAsteroids.CLEAR_SEARCH_M
    # no room within reach: the position wanted
    find_clear.return_value = None
    np.testing.assert_array_equal(
        scene.clear_position([1.0, 2.0, 3.0], 120.0), [1, 2, 3]
    )


def test_cleaning_destroys_the_field_before_the_world(monkeypatch):
    """The world owns the worker pool the field's shapes are built on."""
    _mock_parts(monkeypatch)
    order = []
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()
    scene.speed_dust_cloud = MagicMock()
    scene.field.destroy.side_effect = lambda: order.append("field")
    scene.world.destroy.side_effect = lambda: order.append("world")

    scene.clean()

    assert order == ["field", "world"]
    assert scene.field is None and scene.world is None


def test_space_scenes_share_the_space_base():
    for kind in (SceneAsteroids, SceneLavaPlanet, SceneDebug):
        assert issubclass(kind, SceneSpace)


# ---------------------------------------------------------------------------
# The field, end to end
# ---------------------------------------------------------------------------


def test_the_field_is_solid_to_a_laser(spaceflight_app):
    """
    The asteroid field, built as the scene builds it, stops a laser-masked
    segment fired into a rock: one "terrain" entry on the rock's surface,
    facing the laser, whose owner knows its material.
    """
    native = pytest.importorskip("world_builder.terrain.native")
    from world_builder.asteroids.field import AsteroidField
    from world_builder.asteroids.settings import AsteroidSettings
    from world_builder.terrain.workers import ChunkExecutor

    executor = ChunkExecutor(backend="inline", inline_budget=8)
    field = AsteroidField(
        spaceflight_app,
        SceneAsteroids.FIELD,
        clock=lambda: 3.0,
        settings=AsteroidSettings.preset("low"),
        executor=executor,
        tonemap=False,
    )
    root = None
    try:
        try:
            field.enable_collision(CollisionLayers.TERRAIN_INTO, name="terrain")
        except native.NativeCollisionError as error:
            pytest.skip(f"No native collision: {error}")
        # Headless: no camera, nothing drawn, the rocks still held and solid
        for _ in range(20):
            field.update(np.zeros(3), np.zeros(3), cameras=[])
            if not field.loading:
                break
        assert not field.loading
        rocks = field.population.rocks[field.collision._registered]
        rock = rocks[np.argmin(np.linalg.norm(rocks["centre"], axis=1))]
        # The camera, the player and render's origin at the world's origin
        start = rock["centre"] + np.array([0.0, 0.0, 2.0 * rock["radius"]])
        root = spaceflight_app.render.attach_new_node("smoke_root")
        segment = CollisionNode("laser")
        segment.add_solid(CollisionSegment(*start, *rock["centre"]))
        segment.set_from_collide_mask(CollisionLayers.MUNITION_FROM)
        segment.set_into_collide_mask(BitMask32.all_off())
        path = root.attach_new_node(segment)
        queue = CollisionHandlerQueue()
        traverser = CollisionTraverser()
        traverser.add_collider(path, queue)
        traverser.traverse(spaceflight_app.render)

        entries = [queue.get_entry(i) for i in range(queue.get_num_entries())]
        assert [e.get_into_node().name for e in entries] == ["terrain"]
        entry = entries[0]
        point = np.array(entry.get_surface_point(spaceflight_app.render))
        assert np.linalg.norm(point - rock["centre"]) <= rock["radius"] * 1.001
        assert entry.get_surface_normal(spaceflight_app.render).z > 0.0
        owner = entry.get_into_node_path().get_python_tag("owner")
        assert owner.material_at(point, spaceflight_app.render) in {"rock", "snow"}
        speed = owner.velocity_at(point, spaceflight_app.render)
        assert speed.shape == (3,)
    finally:
        if root is not None:
            root.remove_node()
        field.destroy()
        executor.shutdown()
