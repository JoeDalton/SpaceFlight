from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.dust_clouds import SpeedDust
from space_flight.lighting import Lighting
from space_flight.scenes.asteroid_field import AsteroidField
from space_flight.scenes.planet_2d import Planet2D
from space_flight.scenes.skybox import Skybox


def scene_factory(app: ShowBase, scene_name: str):
    if scene_name == "asteroids":
        return SceneAsteroids(app=app)
    elif scene_name == "lava_planet":
        return SceneLavaPlanet(app=app)


class Scene:
    def __init__(
        self,
        app: ShowBase,
    ):
        self.app = app

    def inititalize_move(self):
        pass


class SceneAsteroids(Scene):
    def __init__(
        self,
        app: ShowBase,
    ):
        super().__init__(app=app)

        # Skybox
        self.skybox = Skybox(app=self.app)

        # Lights
        self.lighting = Lighting(app=self.app)

        # Speed dust effect
        SpeedDust(app=self.app, colors=["blue", "green", "pink", "white"])

        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            app=self.app, n_asteroids=2000, field_size=15000, is_moving=False
        )
        self.big_rotating_asteroid_field = AsteroidField(
            app=self.app,
            n_asteroids=20,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
        )
        self.rotating_asteroid_field = AsteroidField(
            app=self.app, n_asteroids=500, field_size=15000, is_moving=True
        )

        # Drydock
        self.drydock = self.app.loader.load_model(
            DATAFILES_PATH / "models/star_trek_space_drydock/scene.gltf"
        )
        self.drydock.reparent_to(self.app.render)
        self.drydock.set_pos(0, 8000, 50)
        self.drydock.set_scale(100, 100, 100)

        # Planet
        # self.planet = self.loader.load_model(
        #     DATAFILES_PATH / "models/jupiter/scene.gltf"
        # )
        # self.planet.reparent_to(self.render)
        # self.planet.set_pos(0, 8000, 50)
        # self.planet.set_scale(100, 100, 100)

        # Terrain
        # self.terrain = self.loader.load_model(
        #     DATAFILES_PATH / "models/barringer_meteorite_crater/scene.gltf"
        # )
        # self.terrain.reparent_to(self.render)
        # self.terrain.set_pos(0, 8000, 0)
        # self.terrain.set_scale(1000, 1000, 1000)

        # # test asset
        # self.test_asset = self.loader.load_model(
        # DATAFILES_PATH / "models/venator-class_star_destroyer/scene.gltf"
        # )
        # self.test_asset.reparent_to(self.render)
        # self.test_asset.set_pos(0, 1000, 50)
        # self.test_asset.set_scale(1000, 1000, 1000)

    def inititalize_move(self):
        self.rotating_asteroid_field.initialize_move()
        self.big_rotating_asteroid_field.initialize_move()


class SceneLavaPlanet(Scene):
    def __init__(
        self,
        app: ShowBase,
    ):
        super().__init__(app=app)

        # Lights
        self.lighting = Lighting(
            app=self.app,
            directional_direction=[0, 0, 0],
            ambient_color=[0.4, 0.2, 0.1, 1],
        )

        # Speed dust effect
        SpeedDust(app=self.app, colors=["orange", "pink", "yellow", "white"])

        # Asteroid field
        self.static_asteroid_field = AsteroidField(
            app=self.app, n_asteroids=500, field_size=15000, is_moving=False
        )
        self.big_rotating_asteroid_field = AsteroidField(
            app=self.app,
            n_asteroids=3,
            scale_factor=10,
            field_size=15000,
            is_moving=True,
        )
        self.rotating_asteroid_field = AsteroidField(
            app=self.app, n_asteroids=100, field_size=15000, is_moving=True
        )

        # Planet
        self.planet = Planet2D(app=self.app, type="lava")
