from space_flight import RECORD_GAME
from space_flight.game.flight_state import FlightState
from space_flight.global_architecture.simulator import SpaceFlightSimulator

simulator = SpaceFlightSimulator()
try:
    simulator.run()
except Exception as e:
    if RECORD_GAME:
        current_state = simulator.state_manager.get_current()
        if isinstance(current_state, FlightState):
            current_state.record.save()
    raise e
