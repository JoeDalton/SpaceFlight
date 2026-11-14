"""
Unit tests for FlightState.end_level and FlightState.recenter_render_origin
(space_flight.game.flight_state).

These tests bypass FlightState.__init__ (which needs a live ShowBase) via
object.__new__() and set only the attributes each method reads. The
recentering tests use real (window-less) NodePaths, which need no ShowBase.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import NodePath

from space_flight import CAMERA_FAR_M
from space_flight.game.flight_state import FlightState
from space_flight.game.kills import DamageSource, KillLog, credit_hit
from space_flight.game.render_origin import RenderOrigin
from space_flight.game.scenario import Mission


def _make_flight_state(headless: bool) -> FlightState:
    fs = object.__new__(FlightState)
    fs.headless = headless
    fs.outcome = None
    fs.app = MagicMock()
    fs.game_time = SimpleNamespace(get_current_time=lambda: 0.0)
    fs.player = SimpleNamespace(pawn=SimpleNamespace(id="player-id", team=1))
    fs.kill_log = KillLog(fs)
    fs.mission = Mission(fs)
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
        stats=fs.level_stats,
    )


def test_end_level_does_not_push_any_state_when_headless():
    fs = _make_flight_state(headless=True)
    fs.end_level(outcome="death", text="Your ship was destroyed.")
    assert fs.outcome == "death"
    fs.app.state_manager.push.assert_not_called()


def test_end_level_tallies_the_players_kills_and_the_objectives():
    fs = _make_flight_state(headless=True)
    tie = SimpleNamespace(
        id="tie-id", parent=SimpleNamespace(name="tie"), team=2, category="fighter"
    )
    tie.health = 100.0
    credit_hit(tie, DamageSource.of(fs.player.pawn, fs))
    fs.kill_log.record(tie)
    fs.mission.objective("Shoot it down").complete()
    fs.mission.objective("Keep it secret").fail()
    fs.mission.objective("Get home")

    fs.end_level(outcome="victory")

    assert fs.level_stats == {
        "kills": 1,
        "by_category": {"fighter": 1},
        "friendly": 0,
        "objectives": {"total": 3, "complete": 1, "failed": 1},
    }


# The moon's distance: float32 steps are a metre there
_FAR_POSITION = np.array([3.0e6, -9.0e6, 1.234567e6])
# A cockpit-like offset from the ship node, under a metre
_COCKPIT_OFFSET = (0.0, 0.8, -0.2)


class _FakePawn:
    """A ship node written from the player's float64 position, as Ship does."""

    def __init__(self, fs: FlightState, node: NodePath):
        self.fs = fs
        self.node = node
        self.position = _FAR_POSITION.copy()

    def sync_render_node(self):
        self.node.setPos(*self.fs.render_origin.to_local(self.position))


def _make_recentering_state():
    """
    A FlightState with a render -> root_node -> ship -> cockpit chain and a
    render origin still at the world's origin, the player far from it.
    """
    fs = object.__new__(FlightState)
    render = NodePath("render")
    fs.root_node = render.attachNewNode("game_root_node")
    fs.render_origin = RenderOrigin(fs.root_node)
    ship = fs.root_node.attachNewNode("ship")
    ship.setHpr(37.0, -12.0, 5.0)
    cockpit = ship.attachNewNode("cockpit")
    cockpit.setPos(*_COCKPIT_OFFSET)
    fs.player = MagicMock()
    fs.player.pawn = _FakePawn(fs, ship)
    fs.player.pawn.sync_render_node()
    return fs, render, ship, cockpit


def test_recenter_render_origin_rebases_onto_the_player():
    fs, _, _, _ = _make_recentering_state()

    fs.recenter_render_origin()

    np.testing.assert_array_equal(fs.render_origin.origin, _FAR_POSITION)
    assert tuple(fs.root_node.getPos()) == (0.0, 0.0, 0.0)


def test_recenter_render_origin_puts_player_ship_exactly_at_render_origin():
    fs, render, ship, _ = _make_recentering_state()
    fs.recenter_render_origin()
    assert tuple(ship.getPos(render)) == (0.0, 0.0, 0.0)


def test_recenter_render_origin_gives_the_cockpit_a_precise_render_transform():
    fs, render, ship, cockpit = _make_recentering_state()
    expected = np.array(render.getRelativeVector(ship, _COCKPIT_OFFSET))

    # Without recentering, the cockpit's net position is rounded to the metre
    raw_error = np.abs(
        np.array(cockpit.getPos(render)) - _FAR_POSITION - expected
    ).max()
    assert raw_error > 1e-2

    fs.recenter_render_origin()
    np.testing.assert_allclose(np.array(cockpit.getPos(render)), expected, atol=1e-6)


def test_recenter_render_origin_keeps_world_coordinates():
    """Through the render origin, the scene graph still gives back world
    positions, now to the millimetre."""
    fs, _, ship, _ = _make_recentering_state()
    fs.recenter_render_origin()
    fs.player.pawn.position = _FAR_POSITION + np.array([1000.123, -2000.456, 3.789])
    fs.player.pawn.sync_render_node()
    fs.recenter_render_origin()

    world = fs.render_origin.to_world(ship.getPos(fs.root_node))

    np.testing.assert_allclose(world, fs.player.pawn.position, atol=1e-3)


def test_only_the_first_ending_counts():
    """A later ending (e.g. dying after a victory) changes nothing."""
    fs = _make_flight_state(headless=False)
    fs.end_level(outcome="victory", text="You won.")
    fs.end_level(outcome="death", text="Your ship was destroyed.")

    assert fs.outcome == "victory"
    fs.app.state_manager.push.assert_called_once()


def test_world_update_moves_the_scene_after_the_render_origin():
    """
    The terrain is placed around the player at the render origin: the scene
    must be updated after recenter_render_origin, in the same frame.
    """
    fs = object.__new__(FlightState)
    fs.is_paused = False
    order = MagicMock()
    for name in ("delayed_methods", "destructibles", "collision_system"):
        setattr(fs, name, MagicMock())
    fs.interactions = MagicMock()
    fs.integrator = MagicMock()
    fs.method_lists = {}
    fs.player = MagicMock(is_dying=False)
    fs.player.pawn.health = 1.0
    fs.scene = order.scene
    fs.scene.depth_ranges.return_value = (2000.0, 5e5)
    fs.split_depth = order.split_depth
    fs.translucent_volumes = set()
    fs.recenter_render_origin = order.recenter_render_origin
    task = SimpleNamespace(cont="cont")

    assert fs.update_game_world_task(task) == "cont"

    assert [c[0] for c in order.mock_calls] == [
        "recenter_render_origin",
        "scene.depth_ranges",
        "split_depth.update",
        "scene.update_after_recenter",
    ]
    order.split_depth.update.assert_called_once_with(
        2000.0, 5e5, translucent=fs.translucent_volumes
    )


def test_without_split_cameras_the_scene_still_follows_the_origin():
    """Headless there are no split cameras: the scene is updated all the same,
    and its sky reaches the camera's whole range."""
    fs = object.__new__(FlightState)
    fs.split_depth = None
    fs.recenter_render_origin = MagicMock()
    fs.scene = MagicMock()
    fs.follow_render_origin()
    fs.scene.update_after_recenter.assert_called_once()
    fs.scene.depth_ranges.assert_not_called()
    assert fs.depth_far == CAMERA_FAR_M


def test_depth_far_is_the_far_cameras():
    fs = object.__new__(FlightState)
    fs.split_depth = SimpleNamespace(far=123456.0)
    assert fs.depth_far == 123456.0


def test_headless_entry_centres_render_on_the_player_before_building():
    """A scene's loading steps work around the player: render is centred on
    it as soon as it exists, before the rest of the level is built."""
    fs, order = make_headless_entry_state()

    fs._enter_headless(SimpleNamespace(upfront=order.upfront, allow_warp=False))

    names = [c[0] for c in order.mock_calls]
    assert names.index("upfront") < names.index("recenter_render_origin")
    assert names.index("recenter_render_origin") < names.index("build_complete")


@pytest.mark.parametrize("allow_warp", [True, False])
def test_entry_lets_the_player_warp_as_the_level_says(allow_warp):
    fs, order = make_headless_entry_state()

    fs._enter_headless(SimpleNamespace(upfront=order.upfront, allow_warp=allow_warp))

    assert fs.player.warp_drive.allowed is allow_warp


def make_headless_entry_state():
    """A FlightState ready for _enter_headless, its steps recorded in order."""
    fs = object.__new__(FlightState)
    order = MagicMock()
    fs.player = MagicMock()
    fs.recenter_render_origin = order.recenter_render_origin
    fs._make_build_generator = lambda _entry: iter([order.build_step()])
    fs._on_build_complete = order.build_complete
    fs.resume = order.resume
    return fs, order


def test_the_split_keeps_off_translucent_volumes():
    """The split cameras get the scene's ranges and the translucent volumes
    (shield bubbles) to keep the split off."""
    fs = object.__new__(FlightState)
    fs.scene = SimpleNamespace(depth_ranges=lambda: (2000.0, 6e5))
    fs.split_depth = MagicMock()
    fs.translucent_volumes = {"bubble"}

    fs.update_split_depth()

    fs.split_depth.update.assert_called_once_with(
        2000.0, 6e5, translucent=fs.translucent_volumes
    )


def test_the_reveal_ends_the_loading_jump_engine_roar():
    """The level opens on a hyperspace jump, the engine roaring through it
    (from FlightState.enter): the reveal hands the engine back to the
    throttle."""
    fs = object.__new__(FlightState)
    fs.app = MagicMock()
    fs.player = SimpleNamespace(pawn=MagicMock())
    fs._jump_context = None
    fs.is_paused = True
    fs.interval_manager = MagicMock()
    fs.game_time = MagicMock()

    fs._on_reveal()

    fs.player.pawn.roar_engine_sound.assert_called_once_with(False)
    assert not fs.is_paused
