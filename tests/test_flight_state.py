"""
Unit tests for FlightState.end_level and FlightState.recenter_render_origin
(space_flight.game.flight_state).

These tests bypass FlightState.__init__ (which needs a live ShowBase) via
object.__new__() and set only the attributes each method reads. The
recentering tests use real (window-less) NodePaths, which need no ShowBase.
"""

from unittest.mock import MagicMock

import numpy as np
from panda3d.core import NodePath

from space_flight.game.flight_state import FlightState


def _make_flight_state(headless: bool) -> FlightState:
    fs = object.__new__(FlightState)
    fs.headless = headless
    fs.outcome = None
    fs.app = MagicMock()
    return fs


def test_end_level_records_outcome():
    fs = _make_flight_state(headless=False)
    fs.end_level(outcome="victory", text="You won.")
    assert fs.outcome == "victory"


def test_end_level_pushes_level_end_state_when_not_headless():
    fs = _make_flight_state(headless=False)
    fs.end_level(outcome="defeat", text="You lost.")
    fs.app.state_manager.push.assert_called_once_with(
        state_class=fs.app.state_manager.LEVEL_END_STATE,
        outcome="defeat",
        text="You lost.",
    )


def test_end_level_does_not_push_any_state_when_headless():
    fs = _make_flight_state(headless=True)
    fs.end_level(outcome="death", text="Your ship was destroyed.")
    assert fs.outcome == "death"
    fs.app.state_manager.push.assert_not_called()


# Far enough from the origin that float32 steps are ~8 mm
_FAR_POSITION = np.array([123456.789, -98765.4321, 54321.123])
# A cockpit-like offset from the ship node, under a metre
_COCKPIT_OFFSET = (0.0, 0.8, -0.2)


def _make_recentering_state():
    """
    A FlightState with a render -> root_node -> ship -> cockpit chain, the ship
    node written from the player's float64 position like Ship.move() does.
    """
    fs = object.__new__(FlightState)
    render = NodePath("render")
    fs.root_node = render.attachNewNode("game_root_node")
    fs.player = MagicMock()
    fs.player.pawn.position = _FAR_POSITION.copy()
    ship = fs.root_node.attachNewNode("ship")
    ship.setPos(*fs.player.pawn.position)
    ship.setHpr(37.0, -12.0, 5.0)
    cockpit = ship.attachNewNode("cockpit")
    cockpit.setPos(*_COCKPIT_OFFSET)
    return fs, render, ship, cockpit


def test_recenter_render_origin_offsets_root_by_minus_player_position():
    fs, _, _, _ = _make_recentering_state()
    fs.recenter_render_origin()
    np.testing.assert_allclose(
        np.array(fs.root_node.getPos()), -_FAR_POSITION, rtol=1e-7
    )


def test_recenter_render_origin_puts_player_ship_exactly_at_render_origin():
    fs, render, ship, _ = _make_recentering_state()
    fs.recenter_render_origin()
    assert tuple(ship.getPos(render)) == (0.0, 0.0, 0.0)


def test_recenter_render_origin_gives_the_cockpit_a_precise_render_transform():
    fs, render, ship, cockpit = _make_recentering_state()
    expected = np.array(render.getRelativeVector(ship, _COCKPIT_OFFSET))

    # Without recentering, the cockpit's net position is rounded at ~1e5 scale
    raw_error = np.abs(
        np.array(cockpit.getPos(render)) - _FAR_POSITION - expected
    ).max()
    assert raw_error > 1e-4

    fs.recenter_render_origin()
    np.testing.assert_allclose(np.array(cockpit.getPos(render)), expected, atol=1e-6)


def test_recenter_render_origin_keeps_world_coordinates_relative_to_root():
    fs, _, ship, _ = _make_recentering_state()
    before = np.array(ship.getPos(fs.root_node))
    fs.recenter_render_origin()
    np.testing.assert_array_equal(np.array(ship.getPos(fs.root_node)), before)
