from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.sound_pool import SoundPool

ASSETS_TO_LOAD = [
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/laser_on_player", "*.wav"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_target", "*.wav"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/TIE_BLASTER.mp3", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/XWING_BLASTER.mp3", ""),
    ("texture", DATAFILES_PATH / "models/lasers/laser_red.png", ""),
    ("texture", DATAFILES_PATH / "models/lasers/laser_green.png", ""),
    ("texture", DATAFILES_PATH / "models/lasers/laser_blue.png", ""),
    ("model", DATAFILES_PATH / "models/asteroids/toutatis_asteroid/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/asteroids/54509_asteroid/scene.gltf", ""),
]


class AssetManager:
    """
    A class to pre-load and store assets
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
            sound_pool = SoundPool(app=self.app, path=path, pattern=pattern, is_3d=True)
            self.assets[path] = sound_pool
        elif asset_type == "sound":
            sound_pool = SoundPool(
                app=self.app, path=path, pattern=pattern, is_3d=False
            )
            self.assets[path] = sound_pool

        elif asset_type == "model":
            self.assets[path] = self.app.loader.loadModel(path)

        elif asset_type == "texture":
            self.assets[path] = self.app.loader.loadTexture(path)
        else:
            raise ValueError(f"Unkown asset type {asset_type}")

        # Update progress
        progress = (self.n_assets - len(self.assets_to_load)) / self.n_assets
        app_state.progress_bar.update(value=progress)
        return task.cont
