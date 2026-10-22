from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Generator
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import LVecBase3f, Vec3
from world_builder.atmosphere import AtmosphereParams
from world_builder.clouds import Clouds
from world_builder.terrain.level import load_level
from world_builder.terrain.planet import PRESETS
from world_builder.world import BodyLook, CloudLook, OceanLook, SkyLook, SunLook, World

from space_flight import CAMERA_FAR_M, DATAFILES_PATH
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.game.collisions import CollisionLayers
from space_flight.scenes.asteroid_field import AsteroidField
from space_flight.scenes.lighting import Lighting
from space_flight.scenes.ocean import Ocean
from space_flight.scenes.planet_2d import Planet2D
from space_flight.scenes.skybox import Skybox

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


def wait_until_loaded(
    loading: Callable[[], bool],
    step: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
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
    :return: A generator to advance once per frame
    """
    start = clock()
    quiet_since = None
    while True:
        step()
        now = clock()
        if loading():
            quiet_since = None
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
    game: FlightState, scene_name: str
) -> SceneAsteroids | SceneLavaPlanet | SceneOcean | SceneEarthlike | SceneDebug:
    if scene_name == "asteroids":
        return SceneAsteroids(game=game)
    if scene_name == "lava_planet":
        return SceneLavaPlanet(game=game)
    if scene_name == "ocean_planet":
        return SceneOcean(game=game)
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
        things (skyboxes, 2D planets), and the camera's whole far range.

        :return: (split, far), metres
        """
        return DEFAULT_DEPTH_SPLIT_M, CAMERA_FAR_M

    def update_after_recenter(self):
        """
        Per-frame update of what must follow the render origin once it has
        been moved onto the player (see FlightState.recenter_render_origin).
        Nothing by default.
        """


class SceneOcean(Scene):
    # Sun lighting, shared by the cloud field (build_upfront) and the directional
    # light (build_decomposed).
    SUN_DIRECTION = [-0.35, -1, 0.05]
    SUN_COLOR = np.array([1.0, 0.8, 0.2, 1])
    AMBIENT_COLOR = np.array([0.2, 0.2, 0.4, 0.2])
    # What distant things fade to. ONE value, shared by the ocean and the cloud
    # field: both curve over the planet and meet at the horizon, so if they faded
    # to different colours they would not join.
    HAZE_COLOR = AMBIENT_COLOR[:3]

    def build_upfront(self):
        """
        Build the objects whose one-time GPU preparation (shader compile, vertex
        munge, buffer upload) is heavy enough to spike a frame, and force that
        prep now — on a black screen, BEFORE the hyperspace animation starts —
        so the animation that follows stays smooth.

        Requires the player to already exist: the ocean's reflection camera
        copies the player camera's lens.
        """
        # The quality the player chose in the graphics settings
        world = self.game.app.graphics_settings.world_settings()

        # Ocean (geometry, reflection buffer, shader). Curved over the planet, so
        # it has a real horizon that dips and bows with altitude.
        self.ocean = Ocean(
            game=self.game,
            geometric_swell=True,
            haze_color=LVecBase3f(*self.HAZE_COLOR),
            settings=world.settings_for(Ocean),
        )

        # Volumetric clouds, lit to match the dusk sun. The lighting is live, so
        # moving the sun here (or later, via clouds.field.set_sun) relights them
        # with no rebuild.
        self.clouds = Clouds(
            game=self.game,
            sun_direction=Vec3(*self.SUN_DIRECTION),
            sun_color=self.SUN_COLOR[:3],
            sky_color=self.AMBIENT_COLOR[:3],
            haze_color=self.HAZE_COLOR,
            settings=world.settings_for(Clouds),
        )

        # Force the one-time GPU preparation now (textures, vertex buffers and
        # shader compile) so the first time these draw during the animation
        # there is no upload/compile spike. We're on a black screen here, so the
        # cost is invisible.
        gsg = self.game.app.win.get_gsg()
        if gsg is not None:
            self.ocean.base_node.prepare_scene(gsg)
            self.clouds.field.node.prepare_scene(gsg)

    def build_decomposed(self) -> Generator[str | None, None, None]:
        """
        Build the rest of the scene incrementally, yielding between components
        so the loading animation keeps rendering. These are all light and their
        first-render GPU prep is cheap, so they need no special handling.
        """
        # Skybox
        self.skybox = Skybox(game=self.game, name="dusk")
        yield "skybox"

        # Planet
        self.planet = Planet2D(
            game=self.game,
            type="terran",
            scale=1000,
            position=np.array([10000.0, 0.0, 2000.0]),
            orientation=np.quaternion(np.sqrt(2) / 2, 0, 0, -np.sqrt(2) / 2),
        )
        yield "planet"

        # Lights
        self.lighting = Lighting(
            game=self.game,
            directional_color=self.SUN_COLOR,
            directional_direction=self.SUN_DIRECTION,
            ambient_color=[0.2, 0.3, 0.4, 0.2],
        )
        yield "lighting"

        # Speed dust effect (100 nodes — build in chunks across frames)
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "yellow", "white"], defer_build=True
        )
        yield from self.speed_dust_cloud.build()

        # # Star destroyer
        # self.isd = self.game.root_node.attachNewNode("isd_instance")
        # isd_path = (
        #     DATAFILES_PATH
        #     / "models/star_wars_imperial-class_star_destroyer/scene.gltf"
        # )
        # self.game.app.asset_manager.instantiate_3d_model_to_node(
        #     path=isd_path,
        #     parent_node=self.isd,
        # )
        # self.isd.reparent_to(self.game.root_node)
        # self.isd.set_pos(2000, 3000, 1000)
        # self.isd.setP(90)
        # self.isd.set_scale(1)
        # yield "isd"

    def clean(self):
        """
        Cleans the SceneOcean
        """
        # self.isd.removeNode()
        self.ocean.clean()
        self.ocean = None
        self.clouds.clean()
        self.clouds = None
        self.skybox.clean()
        self.skybox = None
        self.planet.clean()
        self.planet = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.lighting.clean()
        self.lighting = None
        self.game = None

        # self.big_rotating_asteroid_field.clean()
        # self.big_rotating_asteroid_field = None


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


class SceneAsteroids(Scene):
    def build_upfront(self):
        """
        Build the asteroid fields (one dense static field plus two rotating
        ones) synchronously on the black screen, BEFORE the hyperspace
        animation starts. Their GPU preparation is not forced here.
        """
        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=2000,
            field_size=15000,
            is_moving=False,
            seed=0,
        )
        self.big_rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=20,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
            seed=1,
        )
        self.rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=500,
            field_size=15000,
            is_moving=True,
            seed=2,
        )

    def build_decomposed(self) -> Generator[str, None, None]:
        """Build the asteroids scene incrementally"""
        # Skybox
        self.skybox = Skybox(game=self.game, name="purple")
        yield "skybox"

        # Lights
        self.lighting = Lighting(game=self.game, ambient_color=[0.2, 0.4, 0.6, 1])
        yield "lighting"

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "green", "pink", "white"]
        )
        yield "dust"

        # Drydock
        # self.drydock = self.game.root_node.attachNewNode("drydock_instance")
        # drydock_path = DATAFILES_PATH / "models/star_trek_space_drydock/scene.gltf"
        # self.game.app.asset_manager.instantiate_3d_model_to_node(
        # path=drydock_path,
        # parent_node=self.drydock,
        # )
        # self.drydock.reparent_to(self.game.root_node)
        # self.drydock.set_pos(0, 8000, 50)
        # self.drydock.set_scale(100, 100, 100)
        # yield "drydock"

    def clean(self):
        """
        Cleans the SceneAsteroids
        """
        # self.drydock.removeNode()
        self.rotating_asteroid_field.clean()
        self.rotating_asteroid_field = None
        self.big_rotating_asteroid_field.clean()
        self.big_rotating_asteroid_field = None
        self.static_asteroid_field.clean()
        self.static_asteroid_field = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.lighting.clean()
        self.lighting = None
        self.skybox.clean()
        self.skybox = None
        self.game = None


class SceneLavaPlanet(Scene):
    def build_upfront(self):
        """
        Build the asteroid fields (one static field plus two rotating ones)
        synchronously on the black screen, BEFORE the hyperspace animation
        starts. Their GPU preparation is not forced here.
        """
        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=500,
            field_size=15000,
            is_moving=False,
            seed=0,
        )
        self.big_rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=3,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
            seed=1,
        )
        self.rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=100,
            field_size=15000,
            is_moving=True,
            seed=2,
        )

    def build_decomposed(self) -> Generator[str, None, None]:
        """
        Build the lava-planet scene incrementally (see
        SceneOcean.build_decomposed): lighting, dust, planet and Star Destroyer.
        """
        # Lights
        self.lighting = Lighting(
            game=self.game,
            directional_direction=[0, 0, 0],
            ambient_color=[0.4, 0.2, 0.1, 1],
        )
        yield "lighting"

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["orange", "pink", "yellow", "white"]
        )
        yield "dust"

        # Planet
        self.planet = Planet2D(game=self.game, type="lava")
        yield "planet"

    def clean(self):
        """
        Cleans the SceneLavaPlanet
        """
        self.rotating_asteroid_field.clean()
        self.rotating_asteroid_field = None
        self.big_rotating_asteroid_field.clean()
        self.big_rotating_asteroid_field = None
        self.static_asteroid_field.clean()
        self.static_asteroid_field = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.lighting.clean()
        self.lighting = None
        self.planet.clean()
        self.planet = None
        # No skybox: build_decomposed doesn't build one for this scene.
        self.game = None


class SceneDebug(Scene):
    def build_upfront(self):
        """
        Nothing to build upfront: the debug scene has no heavy objects.
        """
        pass

    def build_decomposed(self) -> Generator[str, None, None]:
        """
        Build the debug scene incrementally (see SceneOcean.build_decomposed):
        a skybox and lighting.
        """
        # Skybox
        self.skybox = Skybox(game=self.game, name="test")
        yield "skybox"

        # Lights
        self.lighting = Lighting(game=self.game)
        yield "lighting"

    def clean(self):
        """
        Cleans the SceneDebug
        """
        self.lighting.clean()
        self.lighting = None
        self.skybox.clean()
        self.skybox = None
        self.game = None
