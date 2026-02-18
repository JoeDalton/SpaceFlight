import random
from pathlib import Path

from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH

ASSETS_TO_LOAD = [
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/laser_on_player"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_target"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
    # ("model", "models/ship.bam"),
    # ("model", "models/station.bam"),
    # ("texture", "textures/space.png"),
    # ("texture", "textures/ui.png"),
]
SOUND_POOL_LENGTH = 20


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

        asset_type, path = self.assets_to_load.pop(0)

        # path = Path("")

        if asset_type == "3d_sound":
            if path.is_dir():
                self.assets[path] = self.build_sound_pool(
                    directory=path, pattern="*.wav", is_3d=True
                )
            else:
                self.assets[path] = self.get_3d_sound(sound_file=path)
        elif asset_type == "sound":
            if path.is_dir():
                self.assets[path] = self.build_sound_pool(
                    directory=path, pattern="*.wav", is_3d=False
                )
            else:
                self.assets[path] = self.get_generic_sound(sound_file=path)

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

    def load_assets_task_placeholder(self, app_state, task):
        # simulate delay without blocking
        if not hasattr(task, "next_load_time"):
            task.next_load_time = task.time + 0.01

        if task.time < task.next_load_time:
            return task.cont

        if not self.assets_to_load:
            self.app.taskMgr.remove("load-assets-task")
            app_state.on_loading_finished()
            return task.done

        asset_type, path = self.assets_to_load.pop(0)

        progress = (self.n_assets - len(self.assets_to_load)) / self.n_assets

        app_state.progress_bar.update(value=progress)

        task.next_load_time = task.time + 0.01

        return task.cont

    def build_sound_pool(self, directory: Path, pattern: str, is_3d: bool) -> list:
        """
        Builds a sound pool from a glob pattern

        :param pattern: The glob pattern to find the sound files
        :return: a sound pool
        """
        sound_files = list(directory.glob(pattern))
        sound_pool = []
        for _ in range(SOUND_POOL_LENGTH):
            sound_file = random.choice(sound_files)
            if is_3d:
                sound = self.get_3d_sound(sound_file)
            else:
                sound = self.get_generic_sound(sound_file)
            sound_pool.append(sound)
        return sound_pool

    def get_3d_sound(self, sound_file: str) -> object:
        """
        Loads a 3D sound

        :param sound_file: The sound file to load
        :return: The 3d sound object
        """
        return self.app.sfx.audio3d.loadSfx(sound_file)

    def get_generic_sound(self, sound_file: str):
        """
        Loads a non-3d sound

        :param sound_file: The sound file to load
        :return: The sound object
        """
        return self.app.loader.loadSfx(sound_file)
