from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Generator, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from world_builder.asteroids.distributions import Distribution
from world_builder.asteroids.field import AsteroidField
from world_builder.asteroids.spec import (
    Box,
    Clumping,
    Density,
    FieldSpec,
    KeepOut,
    MaterialSpec,
)
from world_builder.atmosphere import AtmosphereParams
from world_builder.terrain.level import load_level
from world_builder.terrain.planet import PRESETS
from world_builder.world import BodyLook, CloudLook, OceanLook, SkyLook, SunLook, World

from space_flight import CAMERA_FAR_M, DATAFILES_PATH
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.game.collisions import CollisionLayers
from space_flight.scenes.planet_2d import Planet2D

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger(__name__)

# The default depth split, metres: depth steps stay about 0.25 m just short of
# it and about 10 m at the far plane (see Scene.depth_ranges)
DEFAULT_DEPTH_SPLIT_M = 2000.0

# The world counts as loaded once its loading flag has stayed False this long:
# it turns on briefly whenever detail refines, so one quiet frame is not enough.
WORLD_QUIET_S = 0.5
# Give up waiting for the world after this long (and say so)
WORLD_TIMEOUT_S = 60.0
# Sleep this long after each step while the world loads: its worker
# processes' results come back through a thread of this process, which a loop
# that never sleeps starves (a headless build runs the loading loop flat out;
# an animated one's frames leave it the time already).
LOADING_YIELD_S = 0.005


def wait_until_loaded(
    loading: Callable[[], bool],
    step: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> Generator[str, None, None]:
    """
    Hold the level's loading until a world has loaded around the player:
    step it once per frame until *loading* has stayed False for
    :data:`WORLD_QUIET_S` (ground not drawn yet is not solid), or for at most
    :data:`WORLD_TIMEOUT_S`.

    :param loading: Whether the world still loads
    :param step: Advance the world by a frame (the game loop is paused while
        loading)
    :param clock: Real time, in seconds
    :param pause: Sleeps for a duration, seconds (LOADING_YIELD_S each step
        while loading)
    :return: A generator to advance once per frame
    """
    start = clock()
    quiet_since = None
    while True:
        step()
        now = clock()
        if loading():
            quiet_since = None
            pause(LOADING_YIELD_S)
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= WORLD_QUIET_S:
            return
        if now - start >= WORLD_TIMEOUT_S:
            LOGGER.warning(
                f"World still loading after {WORLD_TIMEOUT_S:.0f} s: starting anyway"
            )
            return
        yield "world"


def scene_factory(
    game: FlightState, scene_name: str, keep_outs: Sequence[KeepOut] = ()
) -> SceneAsteroids | SceneLavaPlanet | SceneEarthlike | SceneDebug:
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
    if scene_name == "earthlike_planet":
        return SceneEarthlike(game=game)
    if scene_name == "debug":
        return SceneDebug(game=game)
    raise NotImplementedError(f"Unknown scene {scene_name}")


class Scene:
    def __init__(
        self,
        game: FlightState,
    ):
        self.game = game
        self.up_direction = np.array([0, 0, 1])

    def depth_ranges(self) -> tuple[float, float]:
        """
        The split cameras' ranges this frame (see FlightState.split_depth):
        the main camera draws up to the split, a far camera beyond it, each
        with the whole depth buffer.

        By default a fixed split, past which a space level has only distant
        things (the sky, 2D planets), and the camera's whole far range.

        :return: (split, far), metres
        """
        return DEFAULT_DEPTH_SPLIT_M, CAMERA_FAR_M

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


class SceneEarthlike(Scene):
    """
    A copy of WorldBuilder's earth-like demo world around the player: the
    planet (terrain, air, clouds, swell ocean), its moon, the sky and the sun.

    WorldBuilder's World builds and updates them. What they look like is
    decided here. The planet is not rotated: its centre is one radius below
    the world origin, so the ground under Mission 3 is its +z pole, with sea
    level at z = 0 there.
    """

    LEVEL_PATH = DATAFILES_PATH / "worlds/earthlike_demo/demo.yaml"
    # Toward the sun: high in the south-east sky
    SUN = SunLook(direction=(0.4, -0.5, 0.75))
    SKY = SkyLook()
    # Cumulus above the convoy, which flies at 200-800 m
    CLOUDS = CloudLook(altitude=2200.0)
    # The 20 m swell, calmed over the shallows; the air's own haze colour
    OCEAN = OceanLook(haze_color=(0.62, 0.71, 0.84), haze_distance=150000.0)
    # The moon: the demo's airless sand moon, this far from the planet's
    # centre, this far from the vertical over the origin toward north (ahead
    # of the convoy). Next to no sky light: a black sky.
    MOON_DISTANCE_M = 10_000e3
    MOON_ZENITH_ANGLE_DEG = 75.0
    MOON_AMBIENT = (0.025, 0.025, 0.03)
    # The ships are lit by Panda3D's fixed-function lights, with no tone map:
    # the world's physical noon sun (about 2.4) is scaled to about white
    LIGHT_SCALE = 0.4

    def bodies(self) -> list[BodyLook]:
        """:return: The planet (from LEVEL_PATH) and its moon"""
        spec, _camera_pose = load_level(self.LEVEL_PATH)
        centre = np.array([0.0, 0.0, -spec.radius])
        angle = math.radians(self.MOON_ZENITH_ANGLE_DEG)
        moon = centre + self.MOON_DISTANCE_M * np.array(
            [0.0, math.sin(angle), math.cos(angle)]
        )
        return [
            BodyLook(
                "planet",
                spec,
                position=tuple(centre),
                atmosphere=AtmosphereParams(),
                clouds=self.CLOUDS,
                ocean=self.OCEAN,
            ),
            BodyLook(
                "moon",
                replace(PRESETS["moon"], seed=7),
                position=tuple(moon),
                ambient=self.MOON_AMBIENT,
            ),
        ]

    def build_upfront(self):
        """
        Build the world (shaders, textures, worker processes, the ocean's
        reflection buffer) on the black screen, before the hyperspace
        animation starts and before FlightState's split cameras: the ocean's
        reflection copies the main lens. The ground loads during the
        animation (see build_decomposed).
        """
        app = self.game.app
        self.world = World(
            app,
            self.bodies(),
            sun=self.SUN,
            sky=self.SKY,
            settings=app.graphics_settings.world_settings(),
            light_scale=self.LIGHT_SCALE,
            clock=self.game.game_time.get_current_time,
        )
        # Solid to ships, munitions and sensors, the sea surface included
        self.world.enable_collision(CollisionLayers.TERRAIN_INTO, bodies=["planet"])

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

        # The game loop is paused while loading: step the world as a frame does
        yield from wait_until_loaded(
            lambda: self.world.loading, self.game.follow_render_origin
        )

    def depth_ranges(self) -> tuple[float, float]:
        """:return: The split following the nearest ground, the far plane
        reaching the farthest visible part of the planet and the moon"""
        return self.world.depth_ranges(self.game.player.pawn.position)

    def update_after_recenter(self):
        """Everything around the player, now at the render origin."""
        self.world.update(self.game.player.pawn.position, far=self.game.depth_far)

    def clean(self):
        """
        Cleans the SceneEarthlike
        """
        self.world.destroy()
        self.world = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.game = None


class SceneSpace(Scene):
    """
    Open space: WorldBuilder's World with no planet, for its sky (stars, the
    sun's disc, a nebula), its sun and Panda3D's lights for the ships.

    The ships are lit by Panda3D's fixed-function lights, with no tone map:
    the world's light is scaled down by LIGHT_SCALE, its sky light in open
    space (AMBIENT) given before that scale.
    """

    #: Toward the sun
    SUN = SunLook(direction=(-0.42, -0.84, 0.35))
    #: None: no sky (a scene with its own backdrop)
    SKY: SkyLook | None = SkyLook()
    #: The sky light in open space, before LIGHT_SCALE
    AMBIENT = (0.5, 1.0, 2.0)
    LIGHT_SCALE = 0.2

    def build_upfront(self):
        """Build the world (sky, lights, worker processes) on the black
        screen, before the hyperspace animation starts."""
        app = self.game.app
        self.world = World(
            app,
            [],
            sun=self.SUN,
            sky=self.SKY,
            settings=app.graphics_settings.world_settings(),
            light_scale=self.LIGHT_SCALE,
            clock=self.game.game_time.get_current_time,
            space_ambient=self.AMBIENT,
        )

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """Nothing more by default."""
        yield from ()

    def update_after_recenter(self):
        """The sky and the lights around the player, now at the render origin."""
        self.world.update(self.game.player.pawn.position, far=self.game.depth_far)

    def clean(self):
        """
        Cleans the scene
        """
        self.world.destroy()
        self.world = None
        self.game = None


class SceneAsteroids(SceneSpace):
    """
    Missions 1 and 2's asteroid field (WorldBuilder's asteroids): a 15 km
    cube of rock around the origin, patchy, its rocks from 50 m to 2 km
    across in radius, turning with the game's clock. Its rocks are solid to
    ships, munitions and sensors as terrain is, and leave room around the
    level's spawn points and routes (``keep_outs``).
    """

    FIELD = FieldSpec(
        shape=Box((7500.0, 7500.0, 7500.0), edge=500.0),
        density=Density(3.0, Clumping(scale=4000.0, coverage=0.6, softness=0.12)),
        sizes=Distribution.power_law(3.5, 50.0, 2000.0),
        material=MaterialSpec(Distribution.uniform(0.0, 0.15)),
    )
    #: Rocks farther than this from the player are not solid
    COLLISION_DISTANCE_M = 20_000.0
    #: How far clear_position looks for room
    CLEAR_SEARCH_M = 3000.0
    #: Speed dust colours
    DUST = ["blue", "green", "pink", "white"]

    def __init__(self, game: FlightState, keep_outs: Sequence[KeepOut] = ()):
        super().__init__(game=game)
        self.keep_outs = tuple(keep_outs)

    def build_upfront(self):
        """
        Build the world, then the field on its worker pool: its rock shapes
        are built by the workers during the hyperspace animation (see
        build_decomposed).
        """
        super().build_upfront()
        app = self.game.app
        scale = self.LIGHT_SCALE
        self.field = AsteroidField(
            app,
            self.FIELD,
            clock=self.game.game_time.get_current_time,
            settings=app.graphics_settings.world_settings().asteroids,
            keep_outs=self.keep_outs,
            executor=self.world.executor,
            sun_direction=self.SUN.direction,
            sun_color=tuple(np.asarray(self.SUN.color) * scale),
            ambient=tuple(np.asarray(self.AMBIENT) * scale),
            exposure=1.0,
            tonemap=False,  # as the ships' fixed-function lighting
            far=CAMERA_FAR_M,
        )
        # Solid as terrain: the same collision events and handlers
        self.field.enable_collision(
            CollisionLayers.TERRAIN_INTO,
            name="terrain",
            max_distance=self.COLLISION_DISTANCE_M,
        )

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """
        Build the speed dust, then hold the loading animation until the
        field's rock shapes are built: nothing is drawn or solid before.
        """
        self.speed_dust_cloud = SpeedDustCloud(game=self.game, colors=self.DUST)
        yield "dust"
        yield from self._build_backdrop()
        # The game loop is paused while loading: step the field as a frame does
        yield from wait_until_loaded(
            lambda: self.field.loading, self.game.follow_render_origin
        )

    def _build_backdrop(self) -> Generator[str, None, None]:
        """Scene-specific set dressing (none here)."""
        yield from ()

    def update_after_recenter(self):
        """The sky, the lights and the field around the player: the main
        camera and the rear-view mirror see it."""
        super().update_after_recenter()
        camera_render = self.world.camera_render()
        camera_world = np.asarray(self.game.player.pawn.position) + camera_render
        self.field.update(camera_world, camera_render, cameras=self._cameras())

    def _cameras(self) -> list:
        """:return: The views the rocks are drawn for"""
        cameras = [getattr(self.game.app, "cam", None)]
        mirror = getattr(self.game.player, "rear_view_mirror", None)
        if mirror is not None:
            cameras.append(mirror.mirror_np)
        return [camera for camera in cameras if camera is not None]

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
        self.field.destroy()  # before the world, which owns the worker pool
        self.field = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        super().clean()


class SceneLavaPlanet(SceneAsteroids):
    """
    The Dev level's scene: a sparser field in a lava planet's orange light,
    the planet a 2D backdrop, no sky.
    """

    FIELD = FieldSpec(
        shape=Box((7500.0, 7500.0, 7500.0), edge=500.0),
        density=Density(0.4),
        sizes=Distribution.power_law(3.5, 50.0, 2000.0),
        seed=1,
    )
    SUN = SunLook(direction=(0.0, 0.98, 0.2))  # from the planet
    SKY = None
    AMBIENT = (2.0, 1.0, 0.5)
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
