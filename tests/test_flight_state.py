"""
Unit tests for FlightState.end_level (space_flight.game.flight_state).

FlightState.__init__ requires a live Panda3D ShowBase (see other actor tests'
convention). These tests only exercise end_level, so they bypass __init__ via
object.__new__() and set only the attributes it reads.
"""

from unittest.mock import MagicMock

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
