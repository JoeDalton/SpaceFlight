"""
Entry point for the ``space_flight`` console script (see ``pyproject.toml``'s
``[tool.poetry.scripts]``). Mirrors ``scripts/launcher.py``, which remains the
way to run the game straight from a checkout (``python ./scripts/launcher.py``).
"""

from space_flight import RECORD_GAME
from space_flight.game.flight_state import FlightState
from space_flight.global_architecture.simulator import SpaceFlightSimulator


def simulator():
    app = SpaceFlightSimulator()
    try:
        app.run()
    except Exception as e:
        if RECORD_GAME:
            current_state = app.state_manager.get_current()
            if isinstance(current_state, FlightState):
                current_state.record.save()
        raise e
