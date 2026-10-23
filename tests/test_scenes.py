"""
Unit tests for what every scene shares (space_flight.scenes.scenes.Scene).
"""

from space_flight import CAMERA_FAR_M
from space_flight.scenes.scenes import DEFAULT_DEPTH_SPLIT_M, Scene


def test_scenes_split_depth_at_two_km_and_reach_the_cameras_range():
    """By default the main camera draws up to 2 km and the far camera the
    rest of the camera's range."""
    assert Scene(game=None).depth_ranges() == (DEFAULT_DEPTH_SPLIT_M, CAMERA_FAR_M)
    assert DEFAULT_DEPTH_SPLIT_M == 2000.0


def test_scenes_update_nothing_after_recenter_by_default():
    Scene(game=None).update_after_recenter()
