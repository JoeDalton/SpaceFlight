from __future__ import annotations

import importlib.metadata
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import quaternion  # noqa: F401 - registers np.quaternion; needed before any use below
from direct.showbase.ShowBase import ShowBase
from world_builder.clouds.cloud import ATLAS_PNG as CLOUD_ATLAS_PNG

from space_flight import DATAFILES_PATH, LOGGER
from space_flight.global_architecture.asset_pools import SoundPool, TexturePool

if TYPE_CHECKING:
    from direct.task import Task
    from panda3d.core import NodePath

    from space_flight.game.flight_state import FlightState
    from space_flight.menus.splash_state import SplashState

# TODO use bam files for faster loading of 3D models


# Assets preloaded by the splash screen, by path (the cache's key)
# A model whose nodes are looked up or moved (a turret's joints, a GUI map's
# named parts) must say "flatten": False.
COMMON_ASSETS_TO_LOAD: dict[Path, dict[str, Any]] = {
    # UI
    DATAFILES_PATH / "menus/button_map.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/dec_map.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/inc_map.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/list_item_even.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/list_item_odd.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/thumb_map.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/xbone-icons.egg": {"type": "model", "flatten": False},
    DATAFILES_PATH / "menus/dialog.png": {"type": "texture"},
    # Ships
    DATAFILES_PATH / "models/ships/a-wing/cockpit/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/a-wing/exterior/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/x-wing/cockpit/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/x-wing/exterior/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/y-wing/cockpit/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/y-wing/exterior/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/tie_common/cockpit/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/tie-interceptor/exterior/scene.gltf": {
        "type": "model"
    },
    DATAFILES_PATH / "models/ships/tie-bomber/exterior/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/tie-fighter/exterior/scene.gltf": {"type": "model"},
    # Capital ships (heavy glTF — preload so the level build never blocks on them)
    DATAFILES_PATH / "models/ships/gr-75/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/ships/cr-90/scene.gltf": {"type": "model"},
    DATAFILES_PATH / "models/turrets/test/turret.glb": {
        "type": "model",
        "flatten": False,
    },
    DATAFILES_PATH / "models/star_wars_imperial-class_star_destroyer/scene.gltf": {
        "type": "model"
    },
    # Battle sounds
    DATAFILES_PATH / "sounds/impacts/player_crash/short": {
        "type": "3d_sound",
        "pattern": "*.wav",
    },
    DATAFILES_PATH / "sounds/impacts/player_crash/long": {
        "type": "3d_sound",
        "pattern": "*.wav",
    },
    DATAFILES_PATH / "sounds/impacts/laser_on_player_hull": {
        "type": "3d_sound",
        "pattern": "*.wav",
    },
    DATAFILES_PATH / "sounds/impacts/laser_on_player_shield": {
        "type": "3d_sound",
        "pattern": "*.ogg",
    },
    DATAFILES_PATH / "sounds/impacts/laser_distant_on_target": {
        "type": "sound",
        "pattern": "*.wav",
    },
    DATAFILES_PATH / "sounds/impacts/laser_distant_on_rock": {
        "type": "sound",
        "pattern": "*.wav",
    },
    DATAFILES_PATH / "sounds/weapons/TIE_BLASTER.wav": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/weapons/XWING_BLASTER.wav": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/weapons/YWING_BLASTER.wav": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/weapons/AA_TURRET_BLASTER.wav": {"type": "3d_sound"},
    # Ship engine sounds
    DATAFILES_PATH / "sounds/engines/capital_ships/test_capital_ext.ogg": {
        "type": "3d_sound"
    },
    DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_high.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_med.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/tie_common/tie_ext_low.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/a-wing/aw_ext_med.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/x-wing/xw_ext_med.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/y-wing/yw_ext_med.ogg": {"type": "3d_sound"},
    DATAFILES_PATH / "sounds/engines/tie_common/tie_int_high.ogg": {
        "type": "sound",
        "interior": True,
    },
    DATAFILES_PATH / "sounds/engines/tie_common/tie_int_med.ogg": {
        "type": "sound",
        "interior": True,
    },
    DATAFILES_PATH / "sounds/engines/tie_common/tie_int_low.ogg": {
        "type": "sound",
        "interior": True,
    },
    DATAFILES_PATH / "sounds/engines/a-wing/aw_int_med.ogg": {
        "type": "sound",
        "interior": True,
    },
    DATAFILES_PATH / "sounds/engines/x-wing/xw_int_med.ogg": {
        "type": "sound",
        "interior": True,
    },
    DATAFILES_PATH / "sounds/engines/y-wing/yw_int_med.ogg": {
        "type": "sound",
        "interior": True,
    },
    # Planet sprite (large PNG — preload so the level build never blocks on it;
    # loadTexture caches by path, so Planet2D's own load becomes a cache hit)
    DATAFILES_PATH / "sprites/planets_2d/terran.png": {"type": "texture"},
    # Cloud sprite atlas (loaded in CloudField's build preamble — preload so the
    # cloud build doesn't block ~77ms on it; WorldBuilder's atlas loader goes
    # through this asset manager, keyed by path)
    CLOUD_ATLAS_PNG: {"type": "texture"},
    # Dust textures
    DATAFILES_PATH / "sprites/dust/dust_blue.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/dust/dust_green.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/dust/dust_orange.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/dust/dust_pink.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/dust/dust_white.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/dust/dust_yellow.png": {"type": "texture"},
    # Explosion textures
    DATAFILES_PATH / "sprites/particles/fire_atlas.png": {"type": "texture"},
    DATAFILES_PATH / "sprites/particles/smoke_atlas.png": {"type": "texture"},
}


class AssetManager:
    """
    App-wide ``path -> loaded asset`` cache: preloads COMMON_ASSETS_TO_LOAD and
    loads anything else on first request.

    # TODO: Drop useless assets to free memory ? Ex going from one level to the other:
    we don't need the old scene's assets anymore
    """

    def __init__(self, app: ShowBase):
        self.app = app
        self.assets = {}

    def get_asset(
        self,
        asset_type: str,
        path: Path,
        pattern: str = "",
        flatten: bool | None = None,
        interior: bool | None = None,
    ) -> Any:
        """
        Returns the cached asset for *path*, loading and caching it first if needed

        :param asset_type: The type of asset (see :meth:`load_single_asset`)
        :param path: The path where the asset is found (the cache key)
        :param pattern: The asset pattern if path is a directory
        :param flatten: Whether a model loaded now is flattened (see
            :meth:`load_single_asset`); None = its COMMON_ASSETS_TO_LOAD flag,
            True for a path not listed. A cached model is returned as it was
            cached: the path's flag decides it once.
        :param interior: Whether a sound loaded now is a cockpit one (see
            :meth:`load_single_asset`); None = its COMMON_ASSETS_TO_LOAD flag,
            False for a path not listed
        :return: The model, cube map, :class:`TexturePool` or :class:`SoundPool`
        """
        try:
            # Assume the asset has already been loaded
            asset = self.assets[path]
        except KeyError:
            # Load it, store it and return it
            listed = COMMON_ASSETS_TO_LOAD.get(Path(path), {})
            if flatten is None:
                flatten = listed.get("flatten", True)
            if interior is None:
                interior = listed.get("interior", False)
            self.load_single_asset(
                asset_type=asset_type,
                path=path,
                pattern=pattern,
                flatten=flatten,
                interior=interior,
            )
            asset = self.assets[path]
        return asset

    def load_game_assets(self, app_state: SplashState):
        """
        Launches the load_assets task, which loads COMMON_ASSETS_TO_LOAD

        :param app_state: The state to report progress to (the splash screen)
        """
        self.assets_to_load = dict(COMMON_ASSETS_TO_LOAD)
        self.n_assets_to_load = len(self.assets_to_load)

        self.app.taskMgr.add(
            self.load_assets_task,
            "load-assets-task",
            extraArgs=[app_state],
            appendTask=True,
        )

    def load_assets_task(self, app_state: SplashState, task: Task) -> int:
        """
        Loads one queued asset per frame, updating the state's progress bar, and
        calls ``app_state.on_loading_finished()`` once the queue is empty

        :param app_state: The state to report progress to
        """
        if not self.assets_to_load:
            # Done loading
            self.app.taskMgr.remove("load-assets-task")
            app_state.on_loading_finished()
            return task.done
        # Select the next asset to load
        path = next(iter(self.assets_to_load))
        spec = self.assets_to_load.pop(path)
        # Load it from disk if it has not already been
        if path not in self.assets.keys():
            self.load_single_asset(
                asset_type=spec["type"],
                path=path,
                pattern=spec.get("pattern", ""),
                flatten=spec.get("flatten", True),
                interior=spec.get("interior", False),
            )
        # Update progress
        progress = (
            self.n_assets_to_load - len(self.assets_to_load)
        ) / self.n_assets_to_load
        app_state.progress_bar.update(value=progress)
        return task.cont

    def load_single_asset(
        self,
        asset_type: str,
        path: Path,
        pattern: str = "",
        flatten: bool = True,
        interior: bool = False,
    ):
        """
        Loads an asset from file into the cache

        :param asset_type: "model", "texture", "sound" or "3d_sound"
        :param path: The path where the asset is found
        :param pattern: The asset pattern if path is a directory
        :param flatten: For a model, merge it into as few geoms as possible
            (``flatten_strong``): its node transforms baked into its
            vertices, geoms sharing a state combined. Far fewer draw calls
            for a ship drawn in several passes, but its inner nodes are gone:
            False for a model whose nodes are looked up or moved (a turret's
            joints, a GUI map's named parts)
        :param interior: For a "sound", whether it is one of the player's
            cockpit sounds, on SFX's interior manager (see SoundPool)
        """
        if asset_type in ("sound", "3d_sound"):
            self.assets[path] = SoundPool(
                app=self.app,
                path=path,
                pattern=pattern,
                is_3d=asset_type == "3d_sound",
                interior=interior,
            )
        elif asset_type == "model":
            try:
                model = self.app.loader.loadModel(path)
            except Exception:
                LOGGER.exception(
                    "Failed to load model %s (resolved: %s, exists: %s, cwd: %s, "
                    "platform: %s, panda3d: %s, panda3d-gltf: %s)",
                    path,
                    Path(path).resolve(),
                    Path(path).exists(),
                    Path.cwd(),
                    platform.platform(),
                    importlib.metadata.version("panda3d"),
                    importlib.metadata.version("panda3d-gltf"),
                )
                raise
            if flatten:
                model.flatten_strong()
            self.assets[path] = model

        elif asset_type == "texture":
            self.assets[path] = TexturePool(app=self.app, path=path, pattern=pattern)
        else:
            raise ValueError(f"Unkown asset type {asset_type}")

    def instantiate_3d_model_to_node(self, path: Path | str, parent_node: NodePath):
        """
        Gets a cached 3D model and attaches an instance of it to the provided
        parent node

        Instances share their nodes: moving a node of one (e.g. a turret's
        swivelling joint) moves it in every instance. Use
        :meth:`copy_3d_model_to_node` for models whose parts move per copy.

        TODO: egg and bam files don't seem to be instantiable.
        For now they are loaded directly. Do something about it

        :param path: The path of the asset
        :param parent_node: The node to attach the instance to
        """
        model = self.get_asset(
            asset_type="model",
            path=path,
        )
        model.instanceTo(parent_node)

    def copy_3d_model_to_node(self, path: Path | str, parent_node: NodePath):
        """
        Gets a cached 3D model and attaches a copy of it to the provided parent
        node: the copy has nodes of its own (its geometry is still shared), so
        its parts can be moved independently of other copies (e.g. a turret's
        swivelling joints).

        :param path: The path of the asset
        :param parent_node: The node to attach the copy to
        """
        # Copies are for models whose parts move: never flattened
        model = self.get_asset(asset_type="model", path=path, flatten=False)
        model.copyTo(parent_node)


def gltf_model_tilt_quaternion(game: FlightState) -> np.quaternion:
    """
    The second-stage rotation composed into every glTF ship model's
    orientation (cockpit and exterior alike).

    Some Linux systems (confirmed: an Arch install and a WSL Ubuntu install)
    load models mis-rotated with the standard value, for a root cause that
    could not be reproduced locally, so the graphics setting
    ``compatibility.alternate_model_orientation`` swaps in an alternate value
    as an explicit, user-set workaround (no platform detection).

    :param game: The current game object; the standard value is used if it
        has no graphics settings
    """
    try:
        use_alternate = bool(
            game.app.graphics_settings.config.get("compatibility", {}).get(
                "alternate_model_orientation", False
            )
        )
    except AttributeError:
        use_alternate = False

    if use_alternate:
        return np.quaternion(0.0, 1.0, 0.0, 0.0)
    return np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
