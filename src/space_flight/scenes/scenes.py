from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.fx.speed_dust_cloud import SpeedDustCloud
from space_flight.scenes.asteroid_field import AsteroidField
from space_flight.scenes.lighting import Lighting
from space_flight.scenes.planet_2d import Planet2D
from space_flight.scenes.skybox import Skybox


def scene_factory(game, scene_name: str):
    if scene_name == "asteroids":
        return SceneAsteroids(game=game)
    elif scene_name == "lava_planet":
        return SceneLavaPlanet(game=game)
    elif scene_name == "debug_collisions":
        return SceneDebug(game=game)
    else:
        raise NotImplementedError(f"Unknown scene {scene_name}")


class Scene:
    def __init__(
        self,
        game: ShowBase,
    ):
        self.game = game

    def inititalize_move(self):
        pass


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
        SpeedDustCloud(game=self.game, colors=["blue", "green", "pink", "white"])

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
        self.drydock = self.game.app.loader.load_model(
            DATAFILES_PATH / "models/star_trek_space_drydock/scene.gltf"
        )
        self.drydock.reparent_to(self.game.root_node)
        self.drydock.set_pos(0, 8000, 50)
        self.drydock.set_scale(100, 100, 100)


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
        SpeedDustCloud(game=self.game, colors=["orange", "pink", "yellow", "white"])

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
        self.test_asset = self.game.app.loader.load_model(
            DATAFILES_PATH / "models/star_wars_imperial-class_star_destroyer/scene.gltf"
        )
        self.test_asset.reparent_to(self.game.root_node)
        self.test_asset.set_pos(0, 1000, 50)
        self.test_asset.set_scale(1)


class SceneDebug(Scene):
    def __init__(
        self,
        game,
    ):
        super().__init__(game=game)

        # Skybox
        self.skybox = Skybox(game=self.game)

        # Lights
        self.lighting = Lighting(game=self.game)
