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


def test_the_mirror_follows_the_views_depth_mode(spaceflight_app):
    """The world's reversed camera (WorldBuilder #57): the mirror's camera
    is reversed too (or the sky, pinned at the reversed far plane, fails its
    depth test there), culled to its standard range; back to the standard
    depth, as it was."""
    import math

    from panda3d.core import DepthTestAttrib
    from world_builder.depth import DEPTH_REVERSED_01, DEPTH_STANDARD

    app = SimpleNamespace(
        camLens=PerspectiveLens(),
        win=MagicMock(),
        graphics_settings=SimpleNamespace(config={"render": {"mirror_scale": 0.5}}),
    )
    mirror = RearViewMirror(SimpleNamespace(app=app), player_node=NodePath("ship"))
    try:
        node, lens = mirror.mirror_cam, mirror.mirror_cam.get_lens()
        mirror.set_depth_mode(DEPTH_REVERSED_01)
        assert math.isinf(lens.get_near()) and lens.get_far() == pytest.approx(1.0)
        state = node.get_initial_state()
        assert state.get_attrib(DepthTestAttrib).get_mode() == DepthTestAttrib.M_greater
        mirror.mirror_buffer.setClearDepth.assert_called_with(0.0)
        bounds = node.get_cull_bounds()
        reach = max(bounds.get_point(i).length() for i in range(8))
        assert CAMERA_FAR_M <= reach < 4.0 * CAMERA_FAR_M
        mirror.set_depth_mode(DEPTH_STANDARD)
        assert (lens.get_near(), lens.get_far()) == pytest.approx((1.0, CAMERA_FAR_M))
        assert not node.get_initial_state().has_attrib(DepthTestAttrib)
        mirror.mirror_buffer.setClearDepth.assert_called_with(1.0)
    finally:
        mirror.mirror_card.remove_node()
        mirror.mirror_np.remove_node()
