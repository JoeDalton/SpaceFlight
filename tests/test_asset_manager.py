"""
Integration test for AssetManager's real (non-mocked) loading path.

Regression test for stray glTF primitives that
only breaks Panda3D's *first*, uncached conversion of a model, so a warm
on-disk model cache hid it. Other tests mock `instantiate_3d_model_to_node`;
this one points the model cache at an empty directory, clears AssetManager's
in-memory cache, and drives `load_game_assets` the way `SplashState.enter()`
does, so an asset that fails only before it is cached is caught here rather
than on a player's first launch.
"""

import types
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import ConfigVariableFilename, loadPrcFileData

from space_flight import DATAFILES_PATH
from space_flight.global_architecture.asset_manager import (
    COMMON_ASSETS_TO_LOAD,
    AssetManager,
    gltf_model_tilt_quaternion,
)


class _StubProgressBar:
    def __init__(self):
        self.updates = []

    def update(self, value):
        self.updates.append(value)


class _StubSplashState:
    """Minimal stand-in for SplashState: only what load_assets_task touches."""

    def __init__(self):
        self.progress_bar = _StubProgressBar()
        self.finished = False

    def on_loading_finished(self):
        self.finished = True


def test_common_assets_load_through_splash_state_path(spaceflight_app, tmp_path):
    """
    Every COMMON_ASSETS_TO_LOAD entry loads without error via
    load_game_assets, from empty in-memory and on-disk caches (a fresh
    install).
    """
    asset_manager = spaceflight_app.asset_manager

    original_cache_dir = ConfigVariableFilename("model-cache-dir").getValue()
    loadPrcFileData("", f"model-cache-dir {tmp_path}")

    original_assets = dict(asset_manager.assets)
    asset_manager.assets.clear()

    app_state = _StubSplashState()
    try:
        asset_manager.load_game_assets(app_state=app_state)

        # One task step loads (at most) one asset; cap the loop so a stuck
        # task fails the test instead of hanging it.
        for _ in range(len(COMMON_ASSETS_TO_LOAD) + 5):
            if app_state.finished:
                break
            spaceflight_app.taskMgr.step()

        assert app_state.finished, "load_assets_task never reached on_loading_finished"
        assert app_state.progress_bar.updates[-1] == pytest.approx(1.0)

        for path in COMMON_ASSETS_TO_LOAD:
            assert path in asset_manager.assets, f"{path} was not loaded"
    finally:
        asset_manager.assets.clear()
        asset_manager.assets.update(original_assets)
        loadPrcFileData("", f"model-cache-dir {original_cache_dir}")


# ---------------------------
# gltf_model_tilt_quaternion
# ---------------------------


@pytest.fixture
def mock_game():
    """
    Minimal game mock with a real, empty dict for graphics_settings.config,
    so config.get(...) finds no alternate_model_orientation instead of a
    truthy MagicMock chain.
    """
    game = MagicMock()
    game.app.graphics_settings.config = {}
    return game


def test_gltf_model_tilt_quaternion_defaults_to_standard_value(mock_game):
    """
    With the compatibility flag absent, the tilt quaternion is the standard
    value.
    """
    tilt = gltf_model_tilt_quaternion(mock_game)
    expected = np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
    assert tilt == expected


def test_gltf_model_tilt_quaternion_uses_alternate_value_when_flag_set(mock_game):
    """
    Setting compatibility.alternate_model_orientation swaps in the alternate
    (pre-f833c5c) tilt quaternion.
    """
    mock_game.app.graphics_settings.config = {
        "compatibility": {"alternate_model_orientation": True}
    }
    tilt = gltf_model_tilt_quaternion(mock_game)
    assert tilt == np.quaternion(0.0, 1.0, 0.0, 0.0)


def test_gltf_model_tilt_quaternion_defaults_when_graphics_settings_missing():
    """
    A game stand-in with no graphics_settings at all (e.g. a lightweight
    headless stub) falls back to the standard value instead of raising.
    """
    game = types.SimpleNamespace(app=types.SimpleNamespace())
    tilt = gltf_model_tilt_quaternion(game)
    expected = np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
    assert tilt == expected


def test_copy_3d_model_to_node_copies_rather_than_instances():
    """
    copy_3d_model_to_node attaches a copy of the cached model (own nodes, so
    its parts move independently), where instantiate_3d_model_to_node attaches
    an instance (shared nodes).
    """
    asset_manager = object.__new__(AssetManager)
    model = MagicMock()
    asset_manager.assets = {"turret.glb": model}
    parent = MagicMock()

    asset_manager.copy_3d_model_to_node(path="turret.glb", parent_node=parent)
    asset_manager.instantiate_3d_model_to_node(path="turret.glb", parent_node=parent)

    model.copyTo.assert_called_once_with(parent)
    model.instanceTo.assert_called_once_with(parent)


# ---------------------------
# Flattening models at load
# ---------------------------

CR90 = DATAFILES_PATH / "models/ships/cr-90/scene.gltf"
TURRET = DATAFILES_PATH / "models/turrets/test/turret.glb"


def _geom_count(model) -> int:
    return sum(
        path.node().get_num_geoms() for path in model.find_all_matches("**/+GeomNode")
    )


def _fresh_manager(app) -> AssetManager:
    """An AssetManager with an empty cache, over the real app's loader."""
    return AssetManager(app=app)


def test_models_whose_nodes_are_used_are_not_flattened():
    """The turret's joints and the GUI maps' named parts must survive."""
    assert COMMON_ASSETS_TO_LOAD[TURRET]["flatten"] is False
    for path, spec in COMMON_ASSETS_TO_LOAD.items():
        if path.suffix == ".egg":
            assert spec["flatten"] is False, path


def test_a_model_is_flattened_by_default(spaceflight_app):
    """Loaded through the cache, a ship has far fewer geoms than as is."""
    raw = _geom_count(spaceflight_app.loader.loadModel(CR90))
    manager = _fresh_manager(spaceflight_app)
    flattened = _geom_count(manager.get_asset(asset_type="model", path=CR90))
    assert flattened < raw


def test_a_copied_model_keeps_its_joints(spaceflight_app):
    """copy_3d_model_to_node never flattens: the turret can still swivel."""
    manager = _fresh_manager(spaceflight_app)
    parent = spaceflight_app.render.attach_new_node("turret_parent")
    try:
        manager.copy_3d_model_to_node(path=TURRET, parent_node=parent)
        assert not parent.find("**/heading_axis").is_empty()
        assert not parent.find("**/cannon_axis").is_empty()
    finally:
        parent.remove_node()


def test_get_asset_takes_the_listed_flag(spaceflight_app):
    """With no flag given, the turret is loaded unflattened (its entry)."""
    manager = _fresh_manager(spaceflight_app)
    turret = manager.get_asset(asset_type="model", path=TURRET)
    assert not turret.find("**/heading_axis").is_empty()
