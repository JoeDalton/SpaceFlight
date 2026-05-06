import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.scenes.asteroid_field import AsteroidField
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
        game: ShowBase,
    ):
        self.game = game
        self.up_direction = np.array([0, 0, 1])

    def inititalize_move(self):
        pass


class SceneOcean(Scene):
    def __init__(
        self,
        game,
    ):
        super().__init__(game=game)

        # ── Sky / sun ─────────────────────────────────────────────────────────
        # TODO use asset manager. In any case, I will change the skybox
        # Skybox
        self.skybox = Skybox(game=self.game)  # , name="basic_sky/scene.gltf")
        # self.skybox = self.game.app.loader.loadModel(
        #   DATAFILES_PATH/"models/skyboxes/basic_sky/scene.gltf"
        # )
        # self.skybox.reparentTo(self.game.root_node)
        # self.skybox.setBin('background', 1)
        # self.skybox.setDepthWrite(0)
        # self.skybox.setLightOff()
        # self.skybox.setScale(1000)
        # self.sun = self.game.app.loader.loadModel(
        #   DATAFILES_PATH/"models/skyboxes/blue_sky/sun.egg"
        # )
        # self.sun.reparentTo(self.skybox)
        # self.sun.setBin('background', 1)
        # self.sun.setDepthWrite(0)
        # self.sun.setLightOff()
        # self.sun.setScale(50)
        # self.sun.setP(20)

        # Planet
        self.planet = Planet2D(
            game=self.game,
            type="terran",
            scale=1000,
            position=np.array([0.0, 10000.0, 2000.0]),
        )

        # Ocean
        self.ocean = Ocean(game=game, refl_scale=0.5)

        # Lights
        self.lighting = Lighting(
            game=self.game,
            directional_color=[1.0, 0.8, 0.6, 1],
            directional_direction=[0, -70, 0],
            ambient_color=[0.3, 0.4, 0.5, 1],
        )

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "yellow", "white"]
        )

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
        self.isd.set_pos(2000, 3000, 400)
        self.isd.setP(90)
        self.isd.set_scale(1)

    def clean(self):
        """
        Cleans the SceneAsteroids
        """
        self.isd.removeNode()
        self.speed_dust_cloud.clean()
        self.speed_dust_cloud = None
        self.lighting.clean()
        self.lighting = None
        self.game = None


class SceneAsteroids(Scene):
    def __init__(
        self,
        game,
    ):
        super().__init__(game=game)

        # Skybox
        self.skybox = Skybox(game=self.game)

        # Lights
        self.lighting = Lighting(game=self.game)

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["blue", "green", "pink", "white"]
        )

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
    def __init__(
        self,
        game,
    ):
        super().__init__(game=game)

        # Lights
        self.lighting = Lighting(
            game=self.game,
            directional_direction=[0, 0, 0],
            ambient_color=[0.4, 0.2, 0.1, 1],
        )

        # Speed dust effect
        self.speed_dust_cloud = SpeedDustCloud(
            game=self.game, colors=["orange", "pink", "yellow", "white"]
        )

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

        # Planet
        self.planet = Planet2D(game=self.game, type="lava")

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
    def __init__(
        self,
        game,
    ):
        super().__init__(game=game)

        # Skybox
        self.skybox = Skybox(game=self.game, name="sky_test.bam")

        # Lights
        self.lighting = Lighting(game=self.game)

    def clean(self):
        """
        Cleans the SceneDebug
        """
        self.lighting.clean()
        self.lighting = None
        self.skybox.clean()
        self.skybox = None
        self.game = None
