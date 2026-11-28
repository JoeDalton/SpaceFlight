from __future__ import annotations

import functools
import logging
import math
import time
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from world_builder import load_world, parse_world
from world_builder.asteroids.spec import KeepOut

from space_flight import (
    DATAFILES_PATH,
    WARP_MAX_SPEED_MPS,
    WARP_MIN_SPEED_MPS,
    WARP_SPACE_SPEED_MPS,
    WARP_SPEED_PER_ALTITUDE,
)
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.game.collisions import CollisionLayers
from space_flight.scenes.level_frame import LevelFrame
from space_flight.scenes.planet_2d import Planet2D

if TYPE_CHECKING:
    from panda3d.core import NodePath
    from world_builder.asteroids.field import AsteroidField
    from world_builder.depth import ReversedDepthCamera
    from world_builder.world import World
    from world_builder.world_file import GameWorld

    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger(__name__)

# Give up waiting for the world after this long (and say so): a slow machine
# takes a while to build the ground around the player
WORLD_TIMEOUT_S = 360.0


def scene_factory(
    game: FlightState, scene_name: str, keep_outs: Sequence[KeepOut] = ()
) -> SceneAsteroids | SceneLavaPlanet | SceneSolarSystem | SceneDebug:
    """
    :param game: The game/flight state
    :param scene_name: Which scene
    :param keep_outs: Room the scene's asteroid field leaves clear (a level's
        spawn points and routes); ignored by scenes without one
    """
    if scene_name == "asteroids":
        return SceneAsteroids(game=game, keep_outs=keep_outs)
    if scene_name == "lava_planet":
        return SceneLavaPlanet(game=game, keep_outs=keep_outs)
    if scene_name == "solar_system":
        return SceneSolarSystem(game=game)
    if scene_name == "debug":
        return SceneDebug(game=game)
    raise NotImplementedError(f"Unknown scene {scene_name}")


#: A gravity weaker than this (norm of the raw vector) gives no "up"
MIN_GRAVITY_NORM = 1e-1
#: "Up" is reckoned again this often, seconds: at the player, for every ship
#: (the ships stay a few kilometres from it: on a planet of hundreds of
#: kilometres, its "up" turns by a fraction of a degree over that, or in a
#: second of flight)
UP_REFRESH_S = 1.0
#: Frames between two reckonings of the light at the ships and the camera
#: (WorldBuilder's World.light_period): the light where a ship is changes
#: slowly next to the frame rate
LIGHT_PERIOD_FRAMES = 3


def warp_speed_at_altitude(altitude_m: float) -> float:
    """
    How fast a warping ship goes at an altitude (see Scene.warp_speed_mps).

    :param altitude_m: Height above the nearest body's ground, metres; infinite
        in a scene without bodies
    :return: The warp speed, m/s
    """
    if math.isinf(altitude_m):
        return WARP_SPACE_SPEED_MPS
    return min(
        max(WARP_MIN_SPEED_MPS, WARP_SPEED_PER_ALTITUDE * altitude_m),
        WARP_MAX_SPEED_MPS,
    )


class Scene:
    #: The view's camera: one reversed-Z camera over the whole range, with a
    #: float depth buffer's precision from the cockpit to orbit (see
    #: world_builder.depth). The world's own, from the scene's build_upfront
    #: (None until then).
    depth: ReversedDepthCamera | None = None

    def __init__(
        self,
        game: FlightState,
    ):
        self.game = game
        self.default_up_direction = np.array([0, 0, 1])
        self._gravity = None
        # The last "up" reckoned, and when (see up_at)
        self._up: np.ndarray | None = None
        self._up_time_s = -math.inf

    def up_at(self, position: Sequence[float]) -> np.ndarray:
        """
        Returns the "up" direction at a given location in the world.
        If there is significant gravity, up is its opposite.
        Else, the (0.0.1) is used

        It is reckoned at the player (at *position* without one) at most
        every UP_REFRESH_S and used for every position meanwhile: a gravity
        evaluation per bot and per call was a sizable share of the frame.

        :param position: A world position
        :return: "Up" there: against the gravity of the scene's WorldBuilder
            bodies when it is not negligible, else the scene's up_direction
            (world +Z)
        """
        world = getattr(self, "world", None)
        if world is None or not world.bodies:
            return self.default_up_direction
        now = time.monotonic()
        if self._up is None or now - self._up_time_s >= UP_REFRESH_S:
            player = getattr(self.game, "player", None)
            pawn = getattr(player, "pawn", None)
            reference = position if pawn is None else pawn.position
            self._up = self._gravity_up(world, reference)
            self._up_time_s = now
        return self._up

    def forget_up(self):
        """Reckon "up" again on the next up_at, e.g. after a warp moved the
        player far from where it was last reckoned."""
        self._up = None

    def _gravity_up(self, world: World, position: Sequence[float]) -> np.ndarray:
        """:return: Against the bodies' gravity at *position*, or
        default_up_direction where it is negligible"""
        if self._gravity is None:
            self._gravity = world.gravity_field()
        gravity = self._gravity.acceleration(np.asarray(position, dtype=np.float64))
        norm = float(np.linalg.norm(gravity))
        if not np.isfinite(norm) or norm < MIN_GRAVITY_NORM:
            return self.default_up_direction
        return -gravity / norm

    def altitude_m(self, position: Sequence[float]) -> float:
        """
        Height above the ground of the nearest of the scene's WorldBuilder
        bodies (the one whose sea level is nearest).

        :param position: A world position
        :return: The height, metres (0 under the ground), infinite in a scene
            without bodies
        """
        world = getattr(self, "world", None)
        if world is None or not world.bodies:
            return math.inf
        point = np.asarray(position, dtype=np.float64)
        body = world.nearest(point)
        relative = point - body.position
        # Only what is already generated: a query must not stall the frame
        ground_m = float(body.terrain.query.height_at(relative, generate=False))
        return max(float(np.linalg.norm(relative)) - body.radius - ground_m, 0.0)

    def warp_speed_mps(self, position: Sequence[float]) -> float:
        """
        How fast a warping ship goes at a position: in proportion to its
        altitude above the nearest body (WorldBuilder's free-flight demo rule),
        so the trip away from a body, or towards one, is exponential, a second
        per factor of e. A fixed speed in a scene without bodies.

        :param position: A world position
        :return: The warp speed, m/s
        """
        return warp_speed_at_altitude(self.altitude_m(position))

    #: Whether the models tracked by the scene cast shadows
    MODELS_CAST_SHADOWS = True
    #: Whether they are drawn by WorldBuilder's model shader (they then also
    #: receive the world's shadows, per pixel) instead of Panda3D's lights
    MODELS_USE_WORLD_SHADER = True

    def track_model(self, node: NodePath) -> None:
        """
        Light a model by the light at its own position and have it cast
        shadows (WorldBuilder's World.track_light), for the scenes that have a
        World. Called for every model anchored to a node (see
        AnchoredModel): the node is tracked once, whatever is anchored below
        it, so ships, turrets and props need nothing more.

        :param node: The node the model is anchored to (its children follow)
        """
        world = getattr(self, "world", None)
        if world is None or node.is_empty():
            return
        # One tracking per hierarchy: a node below a tracked one is lit and
        # casts with it
        tracked = {tracked_node.get_key() for tracked_node in world.tracked.nodes}
        ancestor = node
        while True:
            if ancestor.get_key() in tracked:
                return
            if not ancestor.has_parent():
                break
            ancestor = ancestor.get_parent()
        world.track_light(
            node,
            cast=self.MODELS_CAST_SHADOWS,
            shader=self.MODELS_USE_WORLD_SHADER,
        )

    def release_depth(self) -> None:
        """
        Remove the scene's depth camera, if it has one, with its scene buffer
        and post chain (render scale, anti-aliasing, FSR 1): FlightState.exit
        calls it first. The mirror goes back to the standard depth.
        """
        if self.depth is not None:
            self.depth.destroy()
            self.depth = None
            from world_builder.depth import DEPTH_STANDARD

            self._mirror_depth_mode(DEPTH_STANDARD)

    def _mirror_depth_mode(self, mode: int) -> None:
        """The rear-view mirror draws the scene with a camera of its own: the
        view's depth convention for it too (world_builder.depth)."""
        player = getattr(self.game, "player", None)
        mirror = getattr(player, "rear_view_mirror", None)
        if mirror is not None:
            mirror.set_depth_mode(mode)

    def update_after_recenter(self):
        """
        Per-frame update of what must follow the render origin once it has
        been moved onto the player (see FlightState.recenter_render_origin).
        Nothing by default.
        """

    def clear_position(self, position: Sequence[float], radius: float) -> np.ndarray:
        """
        A place near *position* with room for a ball of *radius*, for ships
        placed at run time (relative to the player): the position itself
        unless the scene has obstacles there.

        :param position: World position wanted
        :param radius: Room needed around it, metres
        :return: The position to use
        """
        return np.asarray(position, dtype=float)


class SceneWorld(Scene):
    """
    A scene whose world is a WorldBuilder world file, loaded whole by
    ``load_world``: its bodies, asteroid fields, sky, sun and lights, and its
    depth camera.

    The file defines the objects and nothing about running them. The scene
    decides how they are run: the quality, the game's clock, the light the
    ships are given (LIGHT_SCALE) and what is solid.

    With a window ``load_world`` builds the depth camera; headless (no
    window) none, nor the seas (:attr:`depth` is None).

    :ivar game_world: WorldBuilder's loaded world, once built (see
        build_upfront)
    :ivar world: its ``World``, which the scene's queries read
    """

    #: The world file
    WORLD_PATH: Path
    #: Scales the Panda3D lights the world puts on render for the ships, which
    #: use fixed-function lighting with no tone map
    LIGHT_SCALE: float

    def __init__(self, game: FlightState):
        super().__init__(game=game)
        self.game_world: GameWorld | None = None

    def level_keep_outs(self) -> dict[str, Sequence[KeepOut]]:
        """:return: The room the level keeps clear, by field name, added to
        the world file's (none by default)"""
        return {}

    def build_upfront(self):
        """
        Load the world (shaders, textures, worker processes, the ocean's
        reflection buffer, the depth camera) on the black screen, before the
        hyperspace animation starts. What loads over time (the ground, the
        rocks) loads during the animation (see build_decomposed).
        """
        game = self.game
        app = game.app
        self.game_world = load_world(
            app,
            self.WORLD_PATH,
            keep_outs=self.level_keep_outs(),
            # Every terrain is solid (WorldBuilder): the same collision
            # events and handlers
            collision_mask=CollisionLayers.TERRAIN_INTO,
            settings=app.graphics_settings.world_settings(),
            clock=game.game_time.get_current_time,
            light_scale=self.LIGHT_SCALE,
            light_period=LIGHT_PERIOD_FRAMES,
        )
        self.world = self.game_world.world
        self.depth = self.game_world.depth  # None headless: no window
        if self.depth is not None:
            self._mirror_depth_mode(self.depth.mode)

    def hold_loading(self) -> Generator[str, None, None]:
        """Hold the loading animation until the world has loaded around the
        player: ground not drawn yet is not solid. The game loop is paused
        while loading: each step is a frame, as the game loop would run it."""
        steps = self.game_world.load_steps(
            self.game.follow_render_origin, timeout_s=WORLD_TIMEOUT_S
        )
        for _ in steps:
            yield "world"

    def update_after_recenter(self):
        """Everything around the player, now at the render origin."""
        self.game_world.update(self.game.player.pawn.position)

    def clean(self):
        """
        Cleans the scene
        """
        # The depth camera first (GameWorld.destroy would remove it again)
        self.release_depth()
        self.world.destroy()  # its fields and worker pool too
        self.world = None
        self.game_world = None
        self.game = None


class SceneSolarSystem(SceneWorld):
    """
    The three-planets world (``datafiles/worlds/solar_system/``): the home
    planet (terrain, air, clouds, sea), its moon, an ice planet and its ring,
    the sky and the sun.

    The planet is not rotated: levels write their positions on the chart of
    its reference point and convert them with :meth:`level_frame` (see
    LevelFrame).
    """

    WORLD_PATH = DATAFILES_PATH / "worlds/solar_system/solar_system.yaml"
    LIGHT_SCALE = 0.4
    #: The body levels fly over (its name in the world file)
    PLANET = "planet"

    @classmethod
    @functools.cache
    def level_frame(cls) -> LevelFrame:
        """:return: The chart frame of the body called PLANET in the world
        file (chart to world)"""
        bodies = parse_world(cls.WORLD_PATH).bodies
        return LevelFrame.of(next(body for body in bodies if body.name == cls.PLANET))

    def __init__(self, game: FlightState):
        super().__init__(game=game)
        self.default_up_direction = self.level_frame().up

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """
        Build the rest of the scene incrementally, then hold the loading
        animation until the ground and the clouds around the player are
        loaded: ground not drawn yet is not solid.
        """
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "yellow", "white"], defer_build=True
        )
        yield from self.speed_dust_cloud.build()

        yield from self.hold_loading()

    def clean(self):
        """
        Cleans the SceneSolarSystem
        """
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        super().clean()


class SceneSpace(SceneWorld):
    """
    Open space (``datafiles/worlds/space/empty.yaml``): no body, the sky (stars,
    the sun's disc, a nebula), the sun, and Panda3D's lights for the ships.
    """

    WORLD_PATH = DATAFILES_PATH / "worlds/space/empty.yaml"
    LIGHT_SCALE = 0.2

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """Nothing more by default."""
        yield from ()


class SceneAsteroids(SceneSpace):
    """
    Missions 1 and 2's asteroid field (``datafiles/worlds/space/asteroids.yaml``):
    a 15 km cube of rock around the origin, patchy, its rocks from 50 m to 2 km
    across in radius, turning with the game's clock. Its rocks are solid to
    ships, munitions and sensors as terrain is, and leave room around the
    level's spawn points and routes (``keep_outs``).

    :ivar field: WorldBuilder's asteroid field, once built
    """

    WORLD_PATH = DATAFILES_PATH / "worlds/space/asteroids.yaml"
    #: The name of the asteroid field in the world file
    FIELD = "field"
    #: How far clear_position looks for room
    CLEAR_SEARCH_M = 3000.0
    #: Speed dust colours
    DUST = ["blue", "green", "pink", "white"]

    def __init__(self, game: FlightState, keep_outs: Sequence[KeepOut] = ()):
        super().__init__(game=game)
        self.keep_outs = tuple(keep_outs)
        self.field: AsteroidField | None = None

    def level_keep_outs(self) -> dict[str, Sequence[KeepOut]]:
        """:return: The level's keep-outs, for the field"""
        return {self.FIELD: self.keep_outs} if self.keep_outs else {}

    def build_upfront(self):
        """
        Load the world; its field's rock shapes are built by the world's
        workers during the hyperspace animation (see build_decomposed).
        """
        super().build_upfront()
        self.field = self.world.field(self.FIELD)

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """
        Build the speed dust, then hold the loading animation until the
        field's rock shapes are built: nothing is drawn or solid before.
        """
        self.speed_dust_cloud = SpeedDustCloud(game=self.game, colors=self.DUST)
        yield "dust"
        yield from self._build_backdrop()
        yield from self.hold_loading()

    def _build_backdrop(self) -> Generator[str, None, None]:
        """Scene-specific set dressing (none here)."""
        yield from ()

    def update_after_recenter(self):
        """
        The world around the player; the field is drawn for the rear-view
        mirror too while it is shown (a view of the game world).
        """
        mirror = getattr(self.game.player, "rear_view_mirror", None)
        views = self.game_world.views
        views.clear()
        if mirror is not None and mirror.is_mirror_visible:
            views.append(mirror.mirror_np)
        super().update_after_recenter()

    def clear_position(self, position: Sequence[float], radius: float) -> np.ndarray:
        """
        The nearest place to *position* where a ball of *radius* touches no
        rock (the field's frame is the world's), or *position* if there is
        none within CLEAR_SEARCH_M.
        """
        position = np.asarray(position, dtype=float)
        clear = self.field.scatter.find_clear(position, radius, self.CLEAR_SEARCH_M)
        if clear is None:
            LOGGER.warning(f"No room for {radius:.0f} m near {position}")
            return position
        return clear

    def clean(self):
        """
        Cleans the SceneAsteroids
        """
        self.field = None  # destroyed with the world
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        super().clean()


class SceneLavaPlanet(SceneAsteroids):
    """
    The Dev level's scene (``datafiles/worlds/space/lava.yaml``): a sparser
    field in a lava planet's orange light, the planet a 2D backdrop, no sky.
    """

    WORLD_PATH = DATAFILES_PATH / "worlds/space/lava.yaml"
    DUST = ["orange", "pink", "yellow", "white"]

    def _build_backdrop(self) -> Generator[str, None, None]:
        self.planet = Planet2D(game=self.game, type="lava")
        yield "planet"

    def clean(self):
        """
        Cleans the SceneLavaPlanet
        """
        self.planet.clean()
        self.planet = None
        super().clean()


class SceneDebug(SceneSpace):
    """An empty sky, lit."""
