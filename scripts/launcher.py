from space_flight.global_architecture.simulator import SpaceFlightSimulator

simulator = SpaceFlightSimulator()
try:
    simulator.run()
except Exception as e:
    if "panda/src/pgraph/transformState.cxx" in str(e):
        game = simulator.state_manager.get_current()
        game.record.save()
        simulator.state_manager.clear()
        simulator.state_manager.replace(simulator.state_manager.MAIN_MENU_STATE)
    else:
        raise e
