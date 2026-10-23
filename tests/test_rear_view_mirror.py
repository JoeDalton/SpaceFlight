"""
Unit tests for the rear-view mirror's camera (space_flight.ui.rear_view_mirror).

The mirror's buffer is a stand-in (there is no window headless); its camera
and lens are real.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from panda3d.core import NodePath, PerspectiveLens

from space_flight import CAMERA_FAR_M
from space_flight.ui.rear_view_mirror import RearViewMirror


def test_mirror_sees_the_whole_range_whatever_the_main_lens(spaceflight_app):
    """The main lens may hold a depth split's short range (2 km) when the
    mirror copies it: the mirror still reaches the camera's whole range."""
    lens = PerspectiveLens()
    lens.set_near_far(1.0, 2000.0 * 1.02)
    app = SimpleNamespace(
        camLens=lens,
        win=MagicMock(),
        graphics_settings=SimpleNamespace(config={"render": {"mirror_scale": 0.5}}),
    )
    mirror = RearViewMirror(SimpleNamespace(app=app), player_node=NodePath("ship"))
    try:
        mirror_lens = mirror.mirror_cam.get_lens()
        assert mirror_lens.get_near() == 1.0
        assert mirror_lens.get_far() == pytest.approx(CAMERA_FAR_M)
        assert lens.get_far() == pytest.approx(2040.0)  # the main lens untouched
    finally:
        mirror.mirror_card.remove_node()
        mirror.mirror_np.remove_node()
