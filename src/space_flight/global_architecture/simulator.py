import logging

from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData

from space_flight.fx.sfx import SFX
from space_flight.game.game_state import GameState
from space_flight.game.loading_state import LoadingState
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.death_menu_state import DeathMenuState
from space_flight.menus.level_selection_menu_state import LevelSelectionMenuState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.menu_utils import MenuModels
from space_flight.menus.pause_menu_state import PauseMenuState
from space_flight.menus.splash_state import SplashState

LOGGER = logging.getLogger()


loadPrcFileData("", "notify-level-ffmpeg error")


class StateManager:
    SPLASH_STATE = SplashState
    MAIN_MENU_STATE = MainMenuState
    LEVEL_SELECTION_MENU_STATE = LevelSelectionMenuState
    PAUSE_MENU_STATE = PauseMenuState
    DEATH_MENU_STATE = DeathMenuState
    GAME_STATE = GameState
    LOADING_STATE = LoadingState

    def __init__(self, app):
        self.app = app
        self.stack: list[BaseState] = []

    def push(self, state_class: BaseState):
        """
        Pauses the currently running state then
        pushes a new state on top of the current stack.

        :param state_class: The new state class to enter
        """
        if self.stack:
            self.stack[-1].pause()
        state_instance = state_class(self.app)
        self.stack.append(state_instance)
        state_instance.enter()

    def pop(self: BaseState):
        """
        Exits the current state, removes it from the stack
        and resumes the new top of the stack
        """
        if not self.stack:
            LOGGER.warning("No current state to pop")
            return

        top = self.stack.pop()
        top.exit()

        if self.stack:
            self.stack[-1].resume()

    def replace(self, state_class: BaseState):
        """
        Replaces the current state by a new one. It takes it place in the stack.

        :param state_class: _description_
        """
        self.pop()
        self.push(state_class)

    def get_current(self):
        """
        Returns the current state

        :return: The current state
        """
        return self.stack[-1] if self.stack else None

    def clear(self):
        """
        Clears the stack below the current state
        """
        if self.stack:
            for state_idx in range(len(self.stack) - 1):
                self.stack[state_idx].exit()
            self.stack = [self.get_current()]


class SpaceFlightSimulator(ShowBase):
    def __init__(self):
        ShowBase.__init__(self)
        self.disableMouse()

        # Use Physical Based Rendering pipeline. Messes with the ocean for now
        # import simplepbr
        # simplepbr.init()

        self.state_manager = StateManager(app=self)
        self.asset_manager = AssetManager(app=self)
        self.menu_models = MenuModels(app=self)
        self.sfx = SFX(app=self)

        self.configuration = {}

        # Start with splash screen
        self.state_manager.push(SplashState)
