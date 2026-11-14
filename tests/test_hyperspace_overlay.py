"""
Unit tests for the shared hyperspace overlay (space_flight.fx.hyperspace_overlay).

The overlay runs on FakeQuads (see hyperspace_fakes.py): no GPU, no shader.
"""

from unittest.mock import MagicMock

import pytest
from hyperspace_fakes import make_win
from panda3d.core import LVecBase2f

from space_flight import WARP_MAX_WHITEOUT, WARP_TUNNEL_OPACITY
from space_flight.fx.hyperspace_overlay import (
    FADE_DURATION,
    LOADING_LOOK,
    MAX_DT,
    WARP_LOOK,
    set_resolution,
)


def advance(overlay, seconds: float, step: float = MAX_DT / 2):
    """Update the overlay in small steps for (about) the given time."""
    for _ in range(round(seconds / step)):
        overlay.update(step)


def visible_quads(overlay):
    return [quad for quad in overlay._quads if not quad.isHidden()]


# ---------------------------
# Looks
# ---------------------------


def test_loading_look_is_the_original_opaque_effect():
    """The loading look leaves the shaders' original output unchanged."""
    assert LOADING_LOOK.background_opacity == 1.0
    assert LOADING_LOOK.tunnel_opacity == 1.0
    assert LOADING_LOOK.max_whiteout == 1.0


def test_warp_look_shows_the_scene_through():
    assert WARP_LOOK.background_opacity == 0.0
    assert WARP_LOOK.tunnel_opacity == WARP_TUNNEL_OPACITY
    assert WARP_LOOK.max_whiteout == WARP_MAX_WHITEOUT


def test_look_is_fed_to_the_shaders(fake_overlay_factory):
    overlay = fake_overlay_factory(look=WARP_LOOK)

    for quad in overlay._quads:
        assert quad.inputs["iBackgroundOpacity"] == WARP_LOOK.background_opacity
        assert quad.inputs["iTunnelOpacity"] == WARP_LOOK.tunnel_opacity
        assert quad.inputs["iMaxWhiteout"] == WARP_LOOK.max_whiteout
        assert quad.inputs["iCenterOffset"] == WARP_LOOK.center_offset


# ---------------------------
# Phases and fades
# ---------------------------


def test_starts_hidden(fake_overlay_factory):
    overlay = fake_overlay_factory()

    assert overlay.phase is None
    assert not overlay.visible
    assert visible_quads(overlay) == []


def test_show_draws_one_opaque_phase(fake_overlay_factory):
    overlay = fake_overlay_factory()

    overlay.show("into")

    assert overlay.phase == "into"
    assert overlay.visible
    [quad] = visible_quads(overlay)
    assert quad.inputs["iAlpha"] == 1.0


def test_update_advances_the_phase_time(fake_overlay_factory):
    overlay = fake_overlay_factory()
    overlay.show("into")

    overlay.update(0.01)
    overlay.update(0.02)

    assert overlay.phase_time == pytest.approx(0.03)
    [quad] = visible_quads(overlay)
    assert quad.inputs["iTime"] == pytest.approx(0.03)


def test_update_clamps_frame_time(fake_overlay_factory):
    """A long stalled frame advances the animation by MAX_DT only."""
    overlay = fake_overlay_factory()
    overlay.show("outof")

    overlay.update(5.0)

    assert overlay.phase_time == pytest.approx(MAX_DT)


def test_cross_fade_brings_the_next_phase_in_on_top(fake_overlay_factory):
    overlay = fake_overlay_factory()
    overlay.show("into")
    back = visible_quads(overlay)[0]

    overlay.cross_fade_to("inside")
    advance(overlay, FADE_DURATION / 2)

    # Still settled on "into" while fading; both drawn, the back one opaque
    assert overlay.transitioning
    assert overlay.phase == "into"
    assert len(visible_quads(overlay)) == 2
    assert back.inputs["iAlpha"] == 1.0
    front = next(quad for quad in overlay._quads if quad is not back)
    assert 0.0 < front.inputs["iAlpha"] < 1.0


def test_cross_fade_settles_on_the_next_phase(fake_overlay_factory):
    overlay = fake_overlay_factory()
    overlay.show("into")

    overlay.cross_fade_to("inside")
    advance(overlay, FADE_DURATION + MAX_DT)

    assert not overlay.transitioning
    assert overlay.phase == "inside"
    [quad] = visible_quads(overlay)
    assert quad.inputs["iAlpha"] == 1.0
    assert quad.bin == ("fixed", 0)
    # The phase clock started with the fade
    assert overlay.phase_time == pytest.approx(FADE_DURATION + MAX_DT, abs=MAX_DT)


def test_cross_fade_during_a_cross_fade_completes_the_first(fake_overlay_factory):
    """Asking for a new phase mid-fade settles the running fade at once."""
    overlay = fake_overlay_factory()
    overlay.show("into")
    overlay.cross_fade_to("inside")
    advance(overlay, FADE_DURATION / 2)

    overlay.cross_fade_to("outof")

    assert overlay.phase == "inside"
    assert overlay._next_phase == "outof"
    advance(overlay, FADE_DURATION + MAX_DT)
    assert overlay.phase == "outof"
    assert len(visible_quads(overlay)) == 1


def test_cross_fade_from_nothing_shows_at_once(fake_overlay_factory):
    overlay = fake_overlay_factory()

    overlay.cross_fade_to("into")

    assert overlay.phase == "into"
    assert not overlay.transitioning


def test_fade_out_hides_everything(fake_overlay_factory):
    overlay = fake_overlay_factory()
    overlay.show("into")
    [quad] = visible_quads(overlay)

    overlay.fade_out()
    advance(overlay, FADE_DURATION / 2)
    assert 0.0 < quad.inputs["iAlpha"] < 1.0
    assert overlay.visible

    advance(overlay, FADE_DURATION / 2 + MAX_DT)
    assert overlay.phase is None
    assert not overlay.visible
    assert visible_quads(overlay) == []


def test_fade_out_when_hidden_does_nothing(fake_overlay_factory):
    overlay = fake_overlay_factory()

    overlay.fade_out()

    assert not overlay.visible


def test_show_after_fade_out_reuses_the_overlay(fake_overlay_factory):
    overlay = fake_overlay_factory()
    overlay.show("into")
    overlay.fade_out()
    advance(overlay, FADE_DURATION + MAX_DT)

    overlay.show("into")

    assert overlay.phase == "into"
    assert overlay.phase_time == 0.0
    [quad] = visible_quads(overlay)
    assert quad.inputs["iAlpha"] == 1.0


def test_destroy_removes_the_quads(fake_overlay_factory):
    overlay = fake_overlay_factory()
    quads = list(overlay._quads)
    overlay.show("inside")

    overlay.destroy()

    assert all(quad.removed for quad in quads)
    assert not overlay.visible


# ---------------------------
# Resolution
# ---------------------------


def test_set_resolution_reads_the_output_size():
    """The quads get the size of what they cover, a window or an offscreen
    buffer alike (a buffer has no window properties)."""
    buffer = make_win(1600, 900)
    quads = [MagicMock(), MagicMock()]

    set_resolution(quads, buffer)

    for quad in quads:
        quad.setShaderInput.assert_called_once_with(
            "iResolution", LVecBase2f(1600, 900)
        )


def test_update_follows_window_resizes(fake_overlay_factory):
    win = make_win(1600, 900)
    overlay = fake_overlay_factory(win=win)
    assert overlay._quads[0].inputs["iResolution"] == LVecBase2f(1600, 900)

    win.getXSize.return_value = 800
    win.getYSize.return_value = 600
    overlay.update(0.01)

    for quad in overlay._quads:
        assert quad.inputs["iResolution"] == LVecBase2f(800, 600)
