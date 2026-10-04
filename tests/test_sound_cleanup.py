"""
Unit tests for the sounds' lifecycle across a level: pooled sounds released on
level exit, sound effects paused behind menus, engine loops started only by
live ships (space_flight.global_architecture.asset_pools, space_flight.fx.sfx,
space_flight.game.flight_state, space_flight.actors.ship).

Like the rest of the suite, these bypass the constructors that need a live
ShowBase via object.__new__() and set only the attributes each method reads.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from panda3d.core import NodePath

from space_flight.actors.capital_ship import CapitalShip
from space_flight.actors.ship import Ship
from space_flight.fx.sfx import SFX
from space_flight.game.flight_state import FlightState
from space_flight.global_architecture.asset_pools import SoundPool
from space_flight.headless.harness import HeadlessHarness


def _make_sound_pool(n_sounds: int) -> SoundPool:
    pool = object.__new__(SoundPool)
    pool.pool = [MagicMock(name=f"sound{i}") for i in range(n_sounds)]
    pool.in_use = set()
    return pool


def test_in_use_sounds_lists_only_the_sounds_handed_out():
    pool = _make_sound_pool(3)
    first = pool.get_sound()
    second = pool.get_sound()
    assert pool.in_use_sounds() == [first, second]


def test_release_all_stops_the_sounds_in_use_and_frees_them():
    pool = _make_sound_pool(3)
    first = pool.get_sound()
    second = pool.get_sound()

    pool.release_all()

    first.stop.assert_called_once()
    second.stop.assert_called_once()
    pool.pool[2].stop.assert_not_called()
    assert pool.in_use == set()
    # Freed sounds are handed out again
    assert pool.get_sound() is first


def _make_sfx(assets: dict, camera: NodePath | None) -> SFX:
    sfx = object.__new__(SFX)
    sfx.app = SimpleNamespace(
        asset_manager=SimpleNamespace(assets=assets),
        camera=camera,
        sfxManagerList=[MagicMock()],
    )
    sfx.audio3d = MagicMock()
    return sfx


def test_stop_level_sounds_releases_and_detaches_every_pooled_sound_in_use():
    engines = _make_sound_pool(2)
    impacts = _make_sound_pool(2)
    engine = engines.get_sound()
    impact = impacts.get_sound()
    sfx = _make_sfx(
        assets={"engines": engines, "impacts": impacts, "model": NodePath("m")},
        camera=None,
    )

    sfx.stop_level_sounds()

    assert engines.in_use == set() and impacts.in_use == set()
    engine.stop.assert_called_once()
    impact.stop.assert_called_once()
    detached = [call.args[0] for call in sfx.audio3d.detachSound.call_args_list]
    assert detached == [engine, impact]


def test_stop_level_sounds_removes_the_sound_nodes_left_under_the_camera():
    camera = NodePath("camera")
    camera.attachNewNode("player_hit_sound_node")
    camera.attachNewNode("player_hit_sound_node")
    camera.attachNewNode("cockpit")
    sfx = _make_sfx(assets={}, camera=camera)

    sfx.stop_level_sounds()

    assert [child.getName() for child in camera.getChildren()] == ["cockpit"]


def test_sfx_pause_and_resume_toggle_the_sound_effects_manager():
    sfx = _make_sfx(assets={}, camera=None)
    manager = sfx.app.sfxManagerList[0]

    sfx.pause()
    manager.setActive.assert_called_with(False)
    sfx.resume()
    manager.setActive.assert_called_with(True)


def _make_pausable_flight_state() -> FlightState:
    fs = object.__new__(FlightState)
    fs.is_paused = False
    fs.interval_manager = MagicMock()
    fs.game_time = MagicMock()
    fs.app = MagicMock()
    return fs


def test_pausing_the_game_pauses_its_sounds():
    fs = _make_pausable_flight_state()

    fs.pause()
    fs.app.sfx.pause.assert_called_once()
    # Already paused: nothing more to do
    fs.pause()
    fs.app.sfx.pause.assert_called_once()


def test_resuming_the_game_resumes_its_sounds():
    fs = _make_pausable_flight_state()
    fs.resume()
    fs.app.sfx.resume.assert_not_called()

    fs.pause()
    fs.resume()
    fs.app.sfx.resume.assert_called_once()


def test_engine_sound_plays_after_its_delay_while_the_ship_lives():
    ship = object.__new__(Ship)
    ship.sound = MagicMock()
    ship._play_engine_sound()
    ship.sound.play.assert_called_once()


def test_engine_sound_stays_silent_once_the_ship_is_cleaned():
    # Ship.clean returns the sound to its pool and drops it
    ship = object.__new__(Ship)
    ship.sound = None
    ship._play_engine_sound()  # Must not raise nor play anything


@pytest.mark.skip("Headless tests fail on github's CI due to not found assets")
def test_level_exit_leaves_no_sound_in_use(spaceflight_app):
    """
    Each capital ship takes a single engine sound, and none of the level's
    pooled sounds stays in use once it exits ("Dev" spawns 3 capital ships
    after 2s; their engine sounds start 0.5s later).
    """
    harness = HeadlessHarness(app=spaceflight_app)

    with harness.run_level("Dev", max_steps=4 * 60) as flight_state:
        capital_ships = [
            actor
            for actor in flight_state.interactions.live_actors
            if isinstance(actor, CapitalShip)
        ]
        assert capital_ships
        engine_pool = capital_ships[0].sound_pool
        assert len(engine_pool.in_use) == len(capital_ships)

    sound_pools = [
        asset
        for asset in spaceflight_app.asset_manager.assets.values()
        if isinstance(asset, SoundPool)
    ]
    assert all(not pool.in_use for pool in sound_pools)
    assert spaceflight_app.sfx.audio3d.sound_dict == {}
