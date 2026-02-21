import logging

from direct.showbase.ShowBase import ShowBase

from space_flight.fx.sfx import SFX
from space_flight.game.game_state import GameState
from space_flight.game.loading_state import LoadingState
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.pause_menu_state import PauseMenuState
from space_flight.splash.splash_state import SplashState

LOGGER = logging.getLogger()


class StateManager:
    # TODO: stacked state manager ? Better for nested menus ?
    SPLASH_STATE = SplashState
    MAIN_MENU_STATE = MainMenuState
    PAUSE_MENU_STATE = PauseMenuState
    GAME_STATE = GameState
    LOADING_STATE = LoadingState

    def __init__(self, app):
        self.app = app

        self.current_state: BaseState = None
        self.saved_states: list[BaseState] = []

    def change_state(
        self,
        new_state_class: BaseState,
        pause_current_state: bool = False,
        resume_new_state: bool = False,
    ):
        if pause_current_state and self.current_state:
            self.saved_states.append(self.current_state)
        elif pause_current_state and not self.current_state:
            LOGGER.warning("No current state to pause and save")
        elif not pause_current_state and self.current_state:
            self.current_state.exit()
        else:
            # Last case, nothing to do
            pass

        if resume_new_state:
            n_saved_states = len(self.saved_states)
            if n_saved_states != 0:
                next_state_idx = -1
                # Find the index of the state to resume
                for idx in range(n_saved_states):
                    if isinstance(self.saved_states[idx], new_state_class):
                        next_state_idx = idx
                        break
                if next_state_idx == -1:
                    raise RuntimeError(
                        "Can't resume state because there "
                        "are no saved states of matching type"
                    )
                else:
                    # Remove saved state from self.saved_states
                    # and sets it as the current state
                    self.current_state = self.saved_states.pop(next_state_idx)
                    self.current_state.resume()

            else:
                raise RuntimeError(
                    "Can't resume state because there are no saved states"
                )
        else:
            self.current_state = new_state_class(self.app)
            self.current_state.enter()


class SpaceFlightSimulator(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        self.disableMouse()

        self.state_manager = StateManager(self)
        self.asset_manager = AssetManager(app=self)
        self.sfx = SFX(app=self)

        # Start with splash screen
        self.state_manager.change_state(SplashState)
