from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.asset_pools import SoundPool, TexturePool

ASSETS_TO_LOAD = [
    # Battle sounds
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/laser_on_player", "*.wav"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_target", "*.wav"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/TIE_BLASTER.mp3", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/XWING_BLASTER.mp3", ""),
    # Dust textures
    ("texture", DATAFILES_PATH / "sprites/dust/dust_blue.png", ""),
    ("texture", DATAFILES_PATH / "sprites/dust/dust_green.png", ""),
    ("texture", DATAFILES_PATH / "sprites/dust/dust_orange.png", ""),
    ("texture", DATAFILES_PATH / "sprites/dust/dust_pink.png", ""),
    ("texture", DATAFILES_PATH / "sprites/dust/dust_white.png", ""),
    ("texture", DATAFILES_PATH / "sprites/dust/dust_yellow.png", ""),
    # Laser textures
    ("texture", DATAFILES_PATH / "sprites/lasers/laser_red.png", ""),
    ("texture", DATAFILES_PATH / "sprites/lasers/laser_green.png", ""),
    ("texture", DATAFILES_PATH / "sprites/lasers/laser_blue.png", ""),
    # Explosion textures
    ("texture", DATAFILES_PATH / "sprites/particles/explosion", "*.png"),
    ("texture", DATAFILES_PATH / "sprites/particles/black_smoke", "*.png"),
    # Asteroids # TODO use bam files for faster loading
    ("model", DATAFILES_PATH / "models/asteroids/toutatis_asteroid/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/asteroids/54509_asteroid/scene.gltf", ""),
    # Skyboxes
    ("model", DATAFILES_PATH / "models/skyboxes/sky_purple.bam", ""),
    # Ships # TODO use bam files for faster loading
    ("model", DATAFILES_PATH / "models/ships/a-wing/cockpit/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/a-wing/exterior/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/x-wing/cockpit/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/x-wing/exterior/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/y-wing/cockpit/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/y-wing/exterior/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/tie_common/cockpit/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/tie-interceptor/exterior/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/tie-bomber/exterior/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/tie-fighter/exterior/scene.gltf", ""),
]


class AssetManager:
    """
    A class to pre-load and store assets

    TODO add something to load objects "on the fly"
    if they were not loaded during init ?
    """

    def __init__(self, app: ShowBase):
        self.app = app
        self.assets_to_load = ASSETS_TO_LOAD.copy()
        self.n_assets = len(self.assets_to_load)
        self.assets = {}

    def load_game_assets(self, app_state):
        self.app.taskMgr.add(
            self.load_assets_task,
            "load-assets-task",
            extraArgs=[app_state],
            appendTask=True,
        )

    def load_assets_task(self, app_state, task):
        if not self.assets_to_load:
            # Done loading
            self.app.taskMgr.remove("load-assets-task")
            app_state.on_loading_finished()
            return task.done

        asset_type, path, pattern = self.assets_to_load.pop(0)

        if asset_type == "3d_sound":
            self.assets[path] = SoundPool(
                app=self.app, path=path, pattern=pattern, is_3d=True
            )
        elif asset_type == "sound":
            self.assets[path] = SoundPool(
                app=self.app, path=path, pattern=pattern, is_3d=False
            )
        elif asset_type == "model":
            self.assets[path] = self.app.loader.loadModel(path)

        elif asset_type == "texture":
            self.assets[path] = TexturePool(app=self.app, path=path, pattern=pattern)
        else:
            raise ValueError(f"Unkown asset type {asset_type}")

        # Update progress
        progress = (self.n_assets - len(self.assets_to_load)) / self.n_assets
        app_state.progress_bar.update(value=progress)
        return task.cont
