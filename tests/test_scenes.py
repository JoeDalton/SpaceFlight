"""
Unit tests for what every scene shares (space_flight.scenes.scenes.Scene).
"""

from unittest.mock import MagicMock

from space_flight.scenes.scenes import Scene


def test_scenes_update_nothing_after_recenter_by_default():
    Scene(game=None).update_after_recenter()


def test_a_scene_has_no_split_cameras_until_it_builds_them():
    scene = Scene(game=None)
    assert scene.depth is None
    scene.release_depth()  # nothing to remove


def test_releasing_the_split_cameras_removes_them_once():
    scene = Scene(game=None)
    depth = scene.depth = MagicMock()

    scene.release_depth()
    scene.release_depth()

    depth.destroy.assert_called_once_with()
    assert scene.depth is None
