"""
Unit tests for the space scenes (space_flight.scenes.scenes: SceneSpace,
SceneAsteroids, SceneLavaPlanet, SceneDebug) and Missions 1 and 2 in their
asteroid field.

The scenes' wiring runs on stand-ins (WorldBuilder's load_world mocked); the
missions' room in the field is checked against the field's own rocks
(WorldBuilder's scatter: no window, no workers). One end-to-end test builds the
real field and traverses it.
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
from world_builder import parse_world
from world_builder.asteroids.scatter import Scatter

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

# The asteroid field of Missions 1 and 2, as its world file defines it
FIELD = parse_world(SceneAsteroids.WORLD_PATH).fields[0].spec

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
    field = Scatter(FIELD, keep_outs=tuple(mission.KEEP_OUTS))
    for point in points():
        assert field.is_clear(point, CLEARANCE_M), point
    near = sum(len(field.rocks_near(p, 1000.0)) for p in points())
    assert near > 0  # "Big rock, two o'clock"


def test_without_keep_outs_the_routes_would_meet_rocks():
    """The keep-outs matter: the bare field has rocks on the routes."""
    field = Scatter(FIELD)
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


def _game(mirror_visible: bool | None = True):
    """A stand-in game; *mirror_visible* None: the player has no mirror."""
    position = np.array([10.0, 20.0, 30.0])
    player = SimpleNamespace(pawn=SimpleNamespace(position=position))
    player.rear_view_mirror = (
        None
        if mirror_visible is None
        else SimpleNamespace(mirror_np="mirror", is_mirror_visible=mirror_visible)
    )
    return SimpleNamespace(
        app=SimpleNamespace(
            graphics_settings=SimpleNamespace(world_settings=lambda: "settings"),
            cam="main camera",
        ),
        game_time=SimpleNamespace(get_current_time=lambda: 4.0),
        player=player,
        translucent_volumes={"bubble"},
        follow_render_origin=MagicMock(),
    )


def _mock_world(monkeypatch):
    """:return: (load_world mock, the loaded world's stand-in)"""
    field = MagicMock()
    world = MagicMock()
    world.field.return_value = field
    world.camera_render.return_value = np.array([0.0, 1.0, 0.0])
    game_world = SimpleNamespace(world=world, depth=MagicMock(), update=MagicMock())
    load = MagicMock(return_value=game_world)
    monkeypatch.setattr(scenes, "load_world", load)
    return load, game_world


@pytest.mark.parametrize(
    "kind, name",
    [
        (SceneDebug, "empty.yaml"),
        (SceneAsteroids, "asteroids.yaml"),
        (SceneLavaPlanet, "lava.yaml"),
    ],
)
def test_every_space_scene_loads_its_world_file(monkeypatch, kind, name):
    """The sky, the sun, the lights and the field are the file's; the scene
    runs them on the game's clock, at the quality the game settings give."""
    load, _ = _mock_world(monkeypatch)
    scene = kind(game=_game())
    scene.build_upfront()

    args, kwargs = load.call_args
    assert args[0] is scene.game.app
    assert args[1].name == name and args[1].parent.name == "space"
    assert kwargs["settings"] == "settings"
    assert kwargs["light_scale"] == kind.LIGHT_SCALE
    assert kwargs["clock"]() == 4.0  # the game's clock
    # The light at the ships is reckoned every few frames
    assert kwargs["light_period"] == scenes.LIGHT_PERIOD_FRAMES
    assert scene.depth is scene.game_world.depth


def test_the_space_world_files_are_what_the_scenes_were():
    """Without a body; the debug scene has no field, Missions 1 and 2's is
    dense and clumped under a sky, the Dev level's sparse, under no sky."""
    debug, asteroids, lava = (
        parse_world(kind.WORLD_PATH)
        for kind in (SceneDebug, SceneAsteroids, SceneLavaPlanet)
    )
    assert debug.bodies == asteroids.bodies == lava.bodies == ()
    assert debug.fields == ()
    assert [field.name for field in asteroids.fields] == [SceneAsteroids.FIELD]
    assert [field.name for field in lava.fields] == [SceneLavaPlanet.FIELD]
    assert debug.sky is not None and asteroids.sky is not None and lava.sky is None
    dense, sparse = asteroids.fields[0].spec, lava.fields[0].spec
    assert dense.density.count_per_km3 > sparse.density.count_per_km3
    assert dense.density.clumping is not None and sparse.density.clumping is None


def test_the_levels_keep_outs_go_into_the_loaded_file(monkeypatch):
    """load_world has no argument for them: the scene loads a copy of the
    file with them in its field, and no copy without."""
    load, _ = _mock_world(monkeypatch)
    keep_outs = route_keep_outs([[0, 0, 0], [0, 1000, 0]], 10.0)
    seen = []
    load.side_effect = lambda app, path, **_: (
        (seen.append(parse_world(path)) or load.return_value) and load.return_value
    )
    scene = SceneAsteroids(game=_game(), keep_outs=keep_outs)

    scene.build_upfront()

    (world,) = seen
    assert world.fields[0].keep_outs == tuple(keep_outs)
    assert load.call_args.args[1] != SceneAsteroids.WORLD_PATH  # a copy...
    assert not load.call_args.args[1].exists()  # ...gone once loaded

    load.reset_mock(side_effect=True)
    SceneAsteroids(game=_game()).build_upfront()
    assert load.call_args.args[1] == SceneAsteroids.WORLD_PATH


def test_the_field_is_solid_as_terrain(monkeypatch):
    load, game_world = _mock_world(monkeypatch)
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()

    assert scene.field is game_world.world.field.return_value
    game_world.world.field.assert_called_once_with(SceneAsteroids.FIELD)
    scene.field.enable_collision.assert_called_once_with(
        CollisionLayers.TERRAIN_INTO,
        name="terrain",  # the terrain's collision events and handlers
        max_distance=SceneAsteroids.COLLISION_DISTANCE_M,
    )


def test_the_world_follows_the_player(monkeypatch):
    """Render's origin is the player: the world, its field and its split
    cameras are updated around it."""
    _, game_world = _mock_world(monkeypatch)
    scene = SceneAsteroids(game=_game(mirror_visible=False))
    scene.build_upfront()

    scene.update_after_recenter()

    game_world.update.assert_called_once_with(scene.game.player.pawn.position)
    scene.field.update.assert_not_called()  # the world did it, for the camera


def test_the_split_keeps_off_the_translucent_volumes(monkeypatch):
    _, game_world = _mock_world(monkeypatch)
    update = game_world.depth.update  # the split cameras' own
    scene = SceneDebug(game=_game())
    scene.build_upfront()

    scene.depth.update(2000.0, 5e5)

    assert update.call_args.args == (2000.0, 5e5)
    assert update.call_args.kwargs == {"translucent": ("bubble",)}


def test_the_field_is_drawn_again_for_the_visible_mirror(monkeypatch):
    """The world draws the field for the main camera: the mirror, when it is
    shown, sees the rocks behind the player through a second update."""
    _, game_world = _mock_world(monkeypatch)
    scene = SceneAsteroids(game=_game(mirror_visible=True))
    scene.build_upfront()

    scene.update_after_recenter()

    position = scene.game.player.pawn.position
    (camera_world, camera_render), kwargs = scene.field.update.call_args
    np.testing.assert_allclose(camera_world, position + [0.0, 1.0, 0.0])
    np.testing.assert_allclose(camera_render, [0.0, 1.0, 0.0])
    assert kwargs["cameras"] == ["main camera", "mirror"]


@pytest.mark.parametrize("mirror_visible", [False, None])
def test_the_field_is_not_drawn_again_without_a_mirror(monkeypatch, mirror_visible):
    _mock_world(monkeypatch)
    scene = SceneAsteroids(game=_game(mirror_visible=mirror_visible))
    scene.build_upfront()

    scene.update_after_recenter()

    scene.field.update.assert_not_called()


def test_loading_waits_for_the_rock_shapes(monkeypatch):
    _, game_world = _mock_world(monkeypatch)
    monkeypatch.setattr(scenes, "SpeedDustCloud", MagicMock())
    monkeypatch.setattr(scenes, "WORLD_QUIET_S", 0.0)
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()
    loading = iter([True, True, False])
    type(game_world.world).loading = property(lambda _: next(loading, False))

    steps = list(scene.build_decomposed())

    assert steps[0] == "dust"
    assert steps.count("world") >= 2  # held while the world loads
    assert scene.game.follow_render_origin.call_count >= 3


def test_ships_spawned_at_run_time_find_room(monkeypatch):
    _mock_world(monkeypatch)
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


def test_cleaning_removes_the_split_cameras_then_the_world_with_its_field(
    monkeypatch,
):
    """The world owns the field and the worker pool its shapes are built on."""
    _, game_world = _mock_world(monkeypatch)
    order = []
    scene = SceneAsteroids(game=_game())
    scene.build_upfront()
    scene.speed_dust_cloud = MagicMock()
    scene.depth.destroy.side_effect = lambda: order.append("depth")
    scene.world.destroy.side_effect = lambda: order.append("world")

    scene.release_depth()  # FlightState.exit, before the render pipeline goes
    scene.clean()

    assert order == ["depth", "world"]
    assert scene.field is None and scene.world is None and scene.depth is None


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
        FIELD,
        clock=lambda: 3.0,
        settings=AsteroidSettings.preset("low"),
        executor=executor,
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
