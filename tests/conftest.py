"""
Session-level Panda3D configuration shared by all actor tests.

Setting window-type none and audio-library-name null before any
ShowBase is ever constructed keeps the test suite headless (no window,
no audio device) while still giving full access to the scene-graph API,
loaders, and math types from panda3d.core.
"""

import pytest
from panda3d.core import loadPrcFileData

# Must be applied before the first ShowBase construction.
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")


@pytest.fixture(scope="session")
def spaceflight_app():
    """
    The one headless :class:`SpaceFlightSimulator` for the whole test session.

    ShowBase is a per-process singleton (constructing a second instance
    raises), so every test that needs a live app — whether a full headless
    :class:`~space_flight.game.flight_state.FlightState` run or a lighter
    scene/asset test like test_clouds.py — must share this one fixture
    rather than building its own.
    """
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

    return SpaceFlightSimulator(headless=True)
