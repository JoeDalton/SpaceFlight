"""
Integration test for AssetManager's real (non-mocked) loading path.

Regression test for the x-wing cockpit `OSError`: that bug (a stray glTF
primitive that only breaks Panda3D's *first*, uncached conversion of a
model) never reproduced on the dev machine because a pre-existing on-disk
model cache silently skipped the buggy conversion path. Every other test
that touches ship models mocks out `instantiate_3d_model_to_node`, so
nothing in the suite actually exercised a real, from-scratch load of
every asset the game preloads at startup. This test does exactly that: it
points Panda3D's on-disk model cache at an empty directory, clears
AssetManager's in-memory cache, and drives `load_game_assets` through the
task manager the same way `SplashState.enter()` does, so any asset that
only fails to convert once, before it's cached, gets caught here instead
of on a player's first launch.
"""

import types
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import ConfigVariableFilename, loadPrcFileData

from space_flight.global_architecture.asset_manager import (
    COMMON_ASSETS_TO_LOAD,
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
    AssetManager.load_game_assets -- the exact call SplashState.enter()
    makes -- starting from an empty in-memory asset cache and an empty
    on-disk model cache, i.e. a fresh install.
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

        for _asset_type, path, _pattern in COMMON_ASSETS_TO_LOAD:
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
    Minimal game mock with a real dict (not a MagicMock) for
    graphics_settings.config, so config.get(...) lookups behave like the
    real, un-configured default (alternate_model_orientation off) instead
    of a truthy MagicMock chain.
    """
    game = MagicMock()
    game.app.graphics_settings.config = {}
    return game


def testgltf_model_tilt_quaternion_defaults_to_standard_value(mock_game):
    """
    With the compatibility flag off (the default), the tilt quaternion is
    the value that has shipped since it replaced the pre-f833c5c value.
    """
    tilt = gltf_model_tilt_quaternion(mock_game)
    expected = np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
    assert tilt == expected


def testgltf_model_tilt_quaternion_uses_alternate_value_when_flag_set(mock_game):
    """
    Setting compatibility.alternate_model_orientation swaps in the
    pre-f833c5c tilt quaternion instead.
    """
    mock_game.app.graphics_settings.config = {
        "compatibility": {"alternate_model_orientation": True}
    }
    tilt = gltf_model_tilt_quaternion(mock_game)
    assert tilt == np.quaternion(0.0, 1.0, 0.0, 0.0)


def testgltf_model_tilt_quaternion_defaults_when_graphics_settings_missing():
    """
    A game stand-in with no graphics_settings at all (e.g. a lightweight
    headless stub) falls back to the standard value instead of raising.
    """
    game = types.SimpleNamespace(app=types.SimpleNamespace())
    tilt = gltf_model_tilt_quaternion(game)
    expected = np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
    assert tilt == expected
