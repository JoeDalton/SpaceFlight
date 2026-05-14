from space_flight import RECORD_GAME
from space_flight.global_architecture.simulator import SpaceFlightSimulator

simulator = SpaceFlightSimulator()
try:
    simulator.run()
except Exception as e:
    if RECORD_GAME:
        game = simulator.state_manager.get_current()
        game.record.save()
    raise e
