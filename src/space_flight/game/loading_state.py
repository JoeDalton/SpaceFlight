from direct.gui.DirectGui import DirectWaitBar

from space_flight.game.flight_state import FlightState
from space_flight.global_architecture.base_state import BaseState


class LoadingState(BaseState):
    """
    A State to load the assets needed for a specific scene/scenario
    and initialising the game

    # TODO
    """

    def __init__(self, app, level_path):
        super().__init__(app)
        self.level_path = level_path
        self.loaded_model = None

    def enter(self):
        self.progress = DirectWaitBar(
            text="Loading Level...", value=0, pos=(0, 0, 0), scale=0.6
        )

        # Start threaded loading
        self.app.loader.loadModel(self.level_path, callback=self.on_level_loaded)

    def on_level_loaded(self, model):
        self.loaded_model = model
        self.progress["value"] = 100

        # Transition to FlightState
        self.app.state_manager.change_state(
            lambda app: FlightState(app, self.loaded_model)
        )

    def exit(self):
        self.progress.destroy()
