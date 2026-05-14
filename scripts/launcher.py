from space_flight.global_architecture.simulator import SpaceFlightSimulator

simulator = SpaceFlightSimulator()
try:
    simulator.run()
except Exception as e:
    game = simulator.state_manager.get_current()
    game.record.save()
    raise e
