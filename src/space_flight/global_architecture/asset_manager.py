from pathlib import Path

from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.asset_pools import SoundPool, TexturePool

# TODO use bam files for faster loading of 3D models

COMMON_ASSETS_TO_LOAD = [
    # UI
    ("model", DATAFILES_PATH / "menus/button_map.egg", ""),
    ("model", DATAFILES_PATH / "menus/dec_map.egg", ""),
    ("model", DATAFILES_PATH / "menus/inc_map.egg", ""),
    ("model", DATAFILES_PATH / "menus/list_item_even.egg", ""),
    ("model", DATAFILES_PATH / "menus/list_item_odd.egg", ""),
    ("model", DATAFILES_PATH / "menus/thumb_map.egg", ""),
    ("model", DATAFILES_PATH / "menus/xbone-icons.egg", ""),
    ("texture", DATAFILES_PATH / "menus/dialog.png", ""),
    # Asteroids
    ("model", DATAFILES_PATH / "models/asteroids/54509_asteroid/scene.gltf", ""),
    # Skyboxes
    ("model", DATAFILES_PATH / "models/skyboxes/purple.bam", ""),
    ("model", DATAFILES_PATH / "models/skyboxes/dusk.bam", ""),
    # Ships
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
    # Capital ships (heavy glTF — preload so the level build never blocks on them)
    ("model", DATAFILES_PATH / "models/ships/gr-75/scene.gltf", ""),
    ("model", DATAFILES_PATH / "models/ships/cr-90/scene.gltf", ""),
    (
        "model",
        DATAFILES_PATH / "models/star_wars_imperial-class_star_destroyer/scene.gltf",
        "",
    ),
    # Battle sounds
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/player_crash/short", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/player_crash/long", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/laser_on_player_hull", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/impacts/laser_on_player_shield", "*.ogg"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_target", "*.wav"),
    ("sound", DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock", "*.wav"),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/TIE_BLASTER.wav", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/XWING_BLASTER.wav", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/YWING_BLASTER.wav", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/weapons/AA_TURRET_BLASTER.wav", ""),
    # Ship engine sounds
    (
        "3d_sound",
        DATAFILES_PATH / "sounds/engines/capital_ships/test_capital_ext.ogg",
        "",
    ),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_high.ogg", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_med.ogg", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_low.ogg", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/a-wing/aw_ext_med.ogg", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/x-wing/xw_ext_med.ogg", ""),
    ("3d_sound", DATAFILES_PATH / "sounds/engines/y-wing/yw_ext_med.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_int_high.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_int_med.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/tie_common/tie_int_low.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/a-wing/aw_int_med.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/x-wing/xw_int_med.ogg", ""),
    ("sound", DATAFILES_PATH / "sounds/engines/y-wing/yw_int_med.ogg", ""),
    # Planet sprite (large PNG — preload so the level build never blocks on it;
    # loadTexture caches by path, so Planet2D's own load becomes a cache hit)
    ("texture", DATAFILES_PATH / "sprites/planets_2d/terran.png", ""),
    # Cloud sprite atlas (loaded in CloudField's build preamble — preload so the
    # cloud build doesn't block ~77ms on it; load_atlas keys get_asset by path)
    ("texture", DATAFILES_PATH.parent / "scenes/cloud/cloud_atlas.png", ""),
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
    ("texture", DATAFILES_PATH / "sprites/particles/fire_atlas.png", ""),
    ("texture", DATAFILES_PATH / "sprites/particles/smoke_atlas.png", ""),
]


class AssetManager:
    """
    A class to pre-load and store assets, with a possibility to load assets on the fly

    # TODO: Drop useless assets to free memory ? Ex going from one level to the other:
    we don't need the old scene's assets anymore
    """

    def __init__(self, app: ShowBase):
        self.app = app
        self.assets = {}

    def get_asset(self, asset_type: str, path: Path, pattern: str = "") -> object:
        """
        Gets an asset from the dictionary of already-loaded assets or load it from file
        and store it

        :param asset_type: The type of asset
        :param path: The path where the asset is found
        :param pattern: The asset pattern if path is a directory
        """
        try:
            # Assume the asset has already been loaded
            asset = self.assets[path]
        except KeyError:
            # Load it, store it and return it
            self.load_single_asset(asset_type=asset_type, path=path, pattern=pattern)
            asset = self.assets[path]
        return asset

    def load_game_assets(self, app_state, assets_to_load: tuple = None):
        """
        Launches the load_assets task. By default, load the common assets

        :param app_state: The app's state
        """
        if assets_to_load is None:
            self.assets_to_load = COMMON_ASSETS_TO_LOAD.copy()
        self.n_assets_to_load = len(self.assets_to_load)

        self.app.taskMgr.add(
            self.load_assets_task,
            "load-assets-task",
            extraArgs=[app_state],
            appendTask=True,
        )

    def load_assets_task(self, app_state, task):
        """
        The task to load assets at startup

        :param app_state: The app's state
        """
        if not self.assets_to_load:
            # Done loading
            self.app.taskMgr.remove("load-assets-task")
            app_state.on_loading_finished()
            return task.done
        # Select the next asset to load
        asset_type, path, pattern = self.assets_to_load.pop(0)
        # Load it from disk if it has not already been
        if path not in self.assets.keys():
            self.load_single_asset(asset_type=asset_type, path=path, pattern=pattern)
        # Update progress
        progress = (
            self.n_assets_to_load - len(self.assets_to_load)
        ) / self.n_assets_to_load
        app_state.progress_bar.update(value=progress)
        return task.cont

    def load_single_asset(self, asset_type: str, path: Path, pattern: str):
        """
        Loads an asset from file

        :param asset_type: The type of asset
        :param path: The path where the asset is found
        :param pattern: The asset pattern if path is a directory
        """
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

    def instantiate_3d_model_to_node(self, path: Path | str, parent_node):
        """
        Gets a 3D model form the dict of assets and attaches an instance to
        the provided parent node

        TODO: egg and bam files don't seem to be instatiable.
        For now they are loaded directly. Do something about it

        :param path: The path of the asset
        :param parent_node: The node to attach the instance to
        """
        model = self.get_asset(
            asset_type="model",
            path=path,
        )
        model.instanceTo(parent_node)
