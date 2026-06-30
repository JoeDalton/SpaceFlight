import numpy as np
from panda3d.core import Vec3

from space_flight import DATAFILES_PATH
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.scenes.asteroid_field import AsteroidField
from space_flight.scenes.cloud import Clouds
from space_flight.scenes.lighting import Lighting
from space_flight.scenes.ocean import Ocean
from space_flight.scenes.planet_2d import Planet2D
from space_flight.scenes.skybox import Skybox


def scene_factory(game, scene_name: str):
    if scene_name == "asteroids":
        return SceneAsteroids(game=game)
    elif scene_name == "lava_planet":
        return SceneLavaPlanet(game=game)
    elif scene_name == "ocean_planet":
        return SceneOcean(game=game)
    elif scene_name == "debug":
        return SceneDebug(game=game)
    else:
        raise NotImplementedError(f"Unknown scene {scene_name}")


class Scene:
    def __init__(
        self,
        game,
    ):
        self.game = game
        self.up_direction = np.array([0, 0, 1])

    def inititalize_move(self):
        pass


class SceneOcean(Scene):
    # Sun lighting, shared by the cloud field (build_upfront) and the directional
    # light (build_decomposed).
    SUN_DIRECTION = [-0.35, -1, 0.05]
    SUN_COLOR = np.array([1.0, 0.8, 0.2, 1])
    AMBIENT_COLOR = np.array([0.2, 0.2, 0.4, 0.2])

    def build_upfront(self):
        """
        Build the objects whose one-time GPU preparation (shader compile, vertex
        munge, buffer upload) is heavy enough to spike a frame, and force that
        prep now — on a black screen, BEFORE the hyperspace animation starts —
        so the animation that follows stays smooth.

        Requires the player to already exist: the ocean's reflection camera
        copies the player camera's lens.
        """
        # Ocean (geometry, reflection buffer, shader).
        self.ocean = Ocean(game=self.game, geometric_swell=True)

        # Volumetric clouds (cumulus + cirrus), lit to match the dusk sun.
        self.clouds = Clouds(
            game=self.game,
            sun_direction=Vec3(*self.SUN_DIRECTION),
            sun_color=self.SUN_COLOR[:3],
            ambient_color=self.AMBIENT_COLOR[:3],
            use_cache=True,
        )

        # Force the one-time GPU preparation now (textures, vertex buffers and
        # shader compile) so the first time these draw during the animation
        # there is no upload/compile spike. We're on a black screen here, so the
        # cost is invisible.
        gsg = self.game.app.win.get_gsg()
        if gsg is not None:
            self.ocean.base_node.prepare_scene(gsg)
            self.clouds.field.node.prepare_scene(gsg)

    def build_decomposed(self):
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

        # Star destroyer
        self.isd = self.game.root_node.attachNewNode("isd_instance")
        isd_path = (
            DATAFILES_PATH / "models/star_wars_imperial-class_star_destroyer/scene.gltf"
        )
        self.game.app.asset_manager.instantiate_3d_model_to_node(
            path=isd_path,
            parent_node=self.isd,
        )
        self.isd.reparent_to(self.game.root_node)
        self.isd.set_pos(2000, 3000, 1000)
        self.isd.setP(90)
        self.isd.set_scale(1)
        yield "isd"

    def clean(self):
        """
        Cleans the SceneOcean
        """
        self.isd.removeNode()
        self.clouds.clean()
        self.clouds = None
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.lighting.clean()
        self.lighting = None
        self.game = None

        # self.big_rotating_asteroid_field.clean()
        # self.big_rotating_asteroid_field = None


class SceneAsteroids(Scene):
    def build_upfront(self):
        """
        Build the objects whose one-time GPU preparation (shader compile, vertex
        munge, buffer upload) is heavy enough to spike a frame, and force that
        prep now — on a black screen, BEFORE the hyperspace animation starts —
        so the animation that follows stays smooth.

        Requires the player to already exist: the ocean's reflection camera
        copies the player camera's lens.
        """
        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            game=self.game, n_asteroids=2000, field_size=15000, is_moving=False
        )
        self.big_rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=20,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
        )
        self.rotating_asteroid_field = AsteroidField(
            game=self.game, n_asteroids=500, field_size=15000, is_moving=True
        )

    def build_decomposed(self):
        """Build the asteroids scene incrementally"""
        # Skybox
        self.skybox = Skybox(game=self.game, name="purple")
        yield "skybox"

        # Lights
        self.lighting = Lighting(game=self.game)
        yield "lighting"

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "green", "pink", "white"]
        )
        yield "dust"

        # Drydock
        self.drydock = self.game.root_node.attachNewNode("drydock_instance")
        drydock_path = DATAFILES_PATH / "models/star_trek_space_drydock/scene.gltf"
        self.game.app.asset_manager.instantiate_3d_model_to_node(
            path=drydock_path,
            parent_node=self.drydock,
        )
        self.drydock.reparent_to(self.game.root_node)
        self.drydock.set_pos(0, 8000, 50)
        self.drydock.set_scale(100, 100, 100)
        yield "drydock"

    def clean(self):
        """
        Cleans the SceneAsteroids
        """
        self.drydock.removeNode()
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
        Build the objects whose one-time GPU preparation (shader compile, vertex
        munge, buffer upload) is heavy enough to spike a frame, and force that
        prep now — on a black screen, BEFORE the hyperspace animation starts —
        so the animation that follows stays smooth.

        Requires the player to already exist: the ocean's reflection camera
        copies the player camera's lens.
        """
        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            game=self.game, n_asteroids=500, field_size=15000, is_moving=False
        )
        self.big_rotating_asteroid_field = AsteroidField(
            game=self.game,
            n_asteroids=3,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
        )
        self.rotating_asteroid_field = AsteroidField(
            game=self.game, n_asteroids=100, field_size=15000, is_moving=True
        )

    def build_decomposed(self):
        """Build the lava-planet scene incrementally (see SceneOcean.build)."""
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

        # Star destroyer
        self.isd = self.game.root_node.attachNewNode("isd_instance")
        isd_path = (
            DATAFILES_PATH / "models/star_wars_imperial-class_star_destroyer/scene.gltf"
        )
        self.game.app.asset_manager.instantiate_3d_model_to_node(
            path=isd_path,
            parent_node=self.isd,
        )
        self.isd.reparent_to(self.game.root_node)
        self.isd.set_pos(0, 1000, 50)
        self.isd.setP(90)
        self.isd.set_scale(1)
        yield "ISD"

    def clean(self):
        """
        Cleans the SceneLavaPlanet
        """
        self.isd.removeNode()
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
        # self.skybox.clean()
        # self.skybox=None
        self.game = None


class SceneDebug(Scene):
    def build_upfront(self) -> None:
        """
        Build the objects whose one-time GPU preparation (shader compile, vertex
        munge, buffer upload) is heavy enough to spike a frame, and force that
        prep now — on a black screen, BEFORE the hyperspace animation starts —
        so the animation that follows stays smooth.

        Requires the player to already exist: the ocean's reflection camera
        copies the player camera's lens.
        """
        pass

    def build_decomposed(self):
        """Build the debug scene incrementally (see SceneOcean.build)."""
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
