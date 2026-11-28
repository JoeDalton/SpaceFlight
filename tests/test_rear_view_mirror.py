"""
Unit tests for the rear-view mirror's camera (space_flight.ui.rear_view_mirror).

The mirror's buffer is a stand-in (there is no window headless); its camera
and lens are real.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from panda3d.core import FrameBufferProperties, NodePath, PerspectiveLens, Texture
from world_builder.post import FSR1, RenderSettings

from space_flight import CAMERA_FAR_M
from space_flight.ui import rear_view_mirror
from space_flight.ui.rear_view_mirror import RearViewMirror, mirror_screen_size


def _app(lens=None, render: RenderSettings | None = None) -> SimpleNamespace:
    """A stand-in app: a mock window (real framebuffer properties), the
    graphics settings with the mirror's *render* settings."""
    win = MagicMock()
    win.getFbProperties.return_value = FrameBufferProperties()
    win.getYSize.return_value = 1440
    render = render or RenderSettings()
    return SimpleNamespace(
        camLens=lens or PerspectiveLens(),
        win=win,
        graphicsEngine=MagicMock(),
        taskMgr=MagicMock(),
        graphics_settings=SimpleNamespace(
            config={"mirror": {"scale": 0.5}},
            mirror_render_settings=lambda: render,
        ),
    )


def test_mirror_sees_the_whole_range_whatever_the_main_lens(spaceflight_app):
    """The main lens may hold a depth split's short range (2 km) when the
    mirror copies it: the mirror still reaches the camera's whole range."""
    lens = PerspectiveLens()
    lens.set_near_far(1.0, 2000.0 * 1.02)
    app = _app(lens)
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

    from panda3d.core import BoundingSphere, BoundingVolume, DepthTestAttrib, Point3
    from world_builder.depth import DEPTH_REVERSED_01, DEPTH_STANDARD

    app = _app()
    mirror = RearViewMirror(SimpleNamespace(app=app), player_node=NodePath("ship"))
    try:
        node, lens = mirror.mirror_cam, mirror.mirror_cam.get_lens()
        mirror.set_depth_mode(DEPTH_REVERSED_01)
        assert math.isinf(lens.get_near()) and lens.get_far() == pytest.approx(1.0)
        state = node.get_initial_state()
        assert state.get_attrib(DepthTestAttrib).get_mode() == DepthTestAttrib.M_greater
        mirror.mirror_buffer.setClearDepth.assert_called_with(0.0)
        # culled at the mirror's reach, not at infinity
        bounds = node.get_cull_bounds()
        for distance, inside in ((0.99, True), (1.01, False)):
            point = BoundingSphere(Point3(0.0, distance * CAMERA_FAR_M, 0.0), 1e-3)
            reached = bounds.contains(point) != BoundingVolume.IF_no_intersection
            assert reached == inside
        mirror.set_depth_mode(DEPTH_STANDARD)
        assert (lens.get_near(), lens.get_far()) == pytest.approx((1.0, CAMERA_FAR_M))
        assert not node.get_initial_state().has_attrib(DepthTestAttrib)
        mirror.mirror_buffer.setClearDepth.assert_called_with(1.0)
    finally:
        mirror.mirror_card.remove_node()
        mirror.mirror_np.remove_node()


def test_the_mirror_card_size_follows_the_window_height():
    """The card is 0.3 of aspect2d's 2 units high, twice as wide."""
    assert mirror_screen_size(1440) == (432, 216)
    assert mirror_screen_size(900) == (270, 135)


@pytest.mark.parametrize(
    "render,chained",
    [
        (RenderSettings(), False),
        (RenderSettings(msaa=4), False),
        (RenderSettings(fxaa=True), True),
        (RenderSettings(upscaler=FSR1, msaa=4), True),
    ],
)
def test_the_mirror_takes_its_render_settings(
    spaceflight_app, monkeypatch, render, chained
):
    """The buffer asks for the mirror's samples (its section of the graphics
    settings), with float depth;
    FSR 1 or FXAA upscale it to the card's size on screen through a post
    chain ending in a texture, which the card shows; else the card shows
    the buffer. Hiding the mirror stops the chain; clean removes it."""
    chains = []

    class FakeChain:
        def __init__(self, engine, window, source, settings, size, **kwargs):
            self.args = (source, settings, size, kwargs)
            self.texture = Texture("chain")
            self.active = []
            self.destroyed = False
            chains.append(self)

        def set_active(self, active):
            self.active.append(active)

        def destroy(self):
            self.destroyed = True

    monkeypatch.setattr(rear_view_mirror, "PostChain", FakeChain)
    app = _app(render=render)
    mirror = RearViewMirror(SimpleNamespace(app=app), player_node=NodePath("ship"))
    _pipe, _name, _sort, props, window, *_ = app.graphicsEngine.makeOutput.call_args[0]
    # Half the card's 432 x 216 on screen at 1440 px (mirror scale 0.5)
    assert (window.get_x_size(), window.get_y_size()) == (216, 108)
    buffer = app.graphicsEngine.makeOutput.return_value
    texture = buffer.addRenderTexture.call_args[0][0]
    assert props.get_float_depth() and props.get_multisamples() == render.msaa
    assert len(chains) == int(chained)
    if chained:
        chain = chains[0]
        source, settings, size, kwargs = chain.args
        assert source is texture and settings == render and size == (216, 108)
        assert kwargs["output_size"] == (432, 216)
        assert mirror.card_texture is chain.texture
        mirror.toggle_mirror()
        assert chain.active == [False]
    else:
        assert mirror.card_texture is texture
    mirror.clean()
    assert not chained or chains[0].destroyed


def test_the_mirror_buffer_follows_the_window_height(spaceflight_app):
    """A resized window: the buffer keeps its share of the card's new size
    on screen."""
    app = _app()
    mirror = RearViewMirror(SimpleNamespace(app=app), player_node=NodePath("ship"))
    try:
        app.win.getYSize.return_value = 900
        mirror._follow(MagicMock())
        buffer = app.graphicsEngine.makeOutput.return_value
        buffer.setSize.assert_called_with(136, 68)  # half of 270 x 135, rounded
        assert rear_view_mirror.mirror_render_size(900, 1.0) == (270, 135)
    finally:
        mirror.clean()
