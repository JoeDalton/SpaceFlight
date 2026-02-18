from direct.showbase.ShowBase import ShowBase

from space_flight.splash.splash_state import SplashState


class StateManager:
    def __init__(self, app):
        self.app = app
        self.current_state = None

    def change_state(self, new_state_class):
        if self.current_state:
            self.current_state.exit()

        self.current_state = new_state_class(self.app)
        self.current_state.enter()


class SpaceFlightSimulator(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        self.disableMouse()

        self.state_manager = StateManager(self)

        # Start with splash screen
        self.state_manager.change_state(SplashState)
