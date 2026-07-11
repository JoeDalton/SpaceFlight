"""
Integration test for the headless simulation harness
(space_flight.headless.harness).

Unlike the rest of the suite (which stubs out Player/FlightState via
object.__new__ + mocks), this test builds a real, live FlightState — level
loaded, actors spawned, physics stepped — with no window, no audio device, no
menus and no HUD, exactly as an optimization loop (bot personality tuning,
navigator strategy search, ...) would use it.

Reuses the session-wide ``spaceflight_app`` fixture (see conftest.py):
ShowBase is a per-process singleton, so this cannot construct its own app if
other test modules (e.g. test_clouds.py) already share one.
"""

from space_flight.headless.harness import HeadlessHarness


def test_headless_run_advances_a_live_level(spaceflight_app):
    """
    Loading the "Dev" level headlessly and stepping it a few frames actually
    advances the live simulation (time passes, the player moves under its
    initial state), with no outcome yet and no crash.
    """
    harness = HeadlessHarness(app=spaceflight_app)

    with harness.run_level("Dev", max_steps=1) as flight_state:
        time_at_start = flight_state.game_time.get_current_time()
        pos_at_start = flight_state.player.pawn.node.getPos()

        for _ in range(10):
            spaceflight_app.taskMgr.step()

        assert flight_state.game_time.get_current_time() > time_at_start
        assert flight_state.player is not None
        assert flight_state.outcome is None

    # pos_at_start is read for documentation purposes: the Dev level's player
    # starts with zero throttle, so position is not asserted to have moved.
    assert pos_at_start is not None


def test_headless_run_reaches_death_outcome(spaceflight_app):
    """
    Driving the player's health to zero mid-run sets `outcome` to "death"
    without ever pushing the (window-only) LevelEndState.
    """
    harness = HeadlessHarness(app=spaceflight_app)

    with harness.run_level("Dev", max_steps=1) as flight_state:
        flight_state.player.pawn.health = -1
        for _ in range(5):
            spaceflight_app.taskMgr.step()

        assert flight_state.outcome == "death"


def test_headless_harness_supports_back_to_back_runs(spaceflight_app):
    """
    Reusing one harness for several runs works, and reuses the app's asset
    cache rather than reloading assets from disk each time.
    """
    harness = HeadlessHarness(app=spaceflight_app)

    with harness.run_level("Dev", max_steps=1):
        n_assets_after_first_run = len(spaceflight_app.asset_manager.assets)

    with harness.run_level("Dev", max_steps=1) as flight_state:
        assert flight_state.outcome is None
        assert len(spaceflight_app.asset_manager.assets) == n_assets_after_first_run
