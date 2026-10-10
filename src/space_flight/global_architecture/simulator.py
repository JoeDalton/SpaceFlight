from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData

from space_flight.fx.sfx import SFX
from space_flight.game.flight_state import FlightState
from space_flight.game.hyperspace_loading_state import HyperspaceLoadingState
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.global_architecture.base_state import BaseState
from space_flight.global_architecture.gameplay_settings import GameplaySettings
from space_flight.global_architecture.graphics_manager import GraphicsManager
from space_flight.global_architecture.graphics_settings import GraphicsSettings
from space_flight.menus.gameplay_settings_menu_state import GameplaySettingsMenuState
from space_flight.menus.graphics_settings_menu_state import GraphicsSettingsMenuState
from space_flight.menus.input_settings_menu_state import InputSettingsMenuState
from space_flight.menus.level_end_state import LevelEndState
from space_flight.menus.level_selection_menu_state import LevelSelectionMenuState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.menu_utils import MenuModels
from space_flight.menus.pause_menu_state import PauseMenuState
from space_flight.menus.radial_menu_state import RadialMenuState
from space_flight.menus.settings_menu_state import SettingsMenuState
from space_flight.menus.splash_state import SplashState
from space_flight.ui.input_context import InputContextStack
from space_flight.ui.input_reader import load_bindings, reader_factory

if TYPE_CHECKING:
    from direct.task import Task

LOGGER = logging.getLogger()


loadPrcFileData("", "notify-level-ffmpeg error")

# Disable Panda's on-disk model cache (and with it the compiled-shader cache):
# it was implicated in glTF models failing to load on some systems.
loadPrcFileData("", "model-cache-dir")


class StateManager:
    """
    Stack-based state machine whose topmost entry is the active state.

    Entries below the top are paused, unless the state pushed above them has
    ``PAUSES_BELOW = False``. All concrete state classes are class attributes,
    so any module can reference them through StateManager without importing
    the state modules (which would create import cycles).
    """

    SPLASH_STATE = SplashState
    MAIN_MENU_STATE = MainMenuState
    LEVEL_SELECTION_MENU_STATE = LevelSelectionMenuState
    PAUSE_MENU_STATE = PauseMenuState
    SETTINGS_STATE = SettingsMenuState
    GAMEPLAY_SETTINGS_STATE = GameplaySettingsMenuState
    INPUT_SETTINGS_STATE = InputSettingsMenuState
    GRAPHICS_SETTINGS_STATE = GraphicsSettingsMenuState
    RADIAL_MENU_STATE = RadialMenuState
    LEVEL_END_STATE = LevelEndState
    GAME_STATE = FlightState
    HYPERSPACE_LOADING_STATE = HyperspaceLoadingState

    def __init__(self, app: SpaceFlightSimulator):
        self.app = app
        self.stack: list[BaseState] = []

    def push(self, state_class: type[BaseState], **kwargs: Any):
        """
        Pushes a new state onto the stack and enters it.

        Pauses the current top state first, unless *state_class* declares
        PAUSES_BELOW = False (overlays that keep game time running).

        :param state_class: The state class to instantiate and push.
        :param kwargs: Forwarded to the *state_class* constructor.
        """
        if self.stack and getattr(state_class, "PAUSES_BELOW", True):
            self.stack[-1].pause()
        state_instance = state_class(self.app, **kwargs)
        self.stack.append(state_instance)
        state_instance.enter()

    def pop(self):
        """
        Exits and removes the current top state, then resumes the new top (if
        any). Logs a warning and does nothing when the stack is empty.
        """
        if not self.stack:
            LOGGER.warning("No current state to pop")
            return

        top = self.stack.pop()
        top.exit()

        if self.stack:
            self.stack[-1].resume()

    def replace(self, state_class: type[BaseState]):
        """
        Replaces the current top state: :meth:`pop` then :meth:`push`.

        :param state_class: The state class to instantiate in its place.
        """
        self.pop()
        self.push(state_class)

    def get_current(self) -> BaseState | None:
        """
        Returns the state currently at the top of the stack.

        :return:
            The active :class:`BaseState` instance, or None if the stack
            is empty.
        """
        return self.stack[-1] if self.stack else None

    def clear(self):
        """
        Exits and discards every state below the current top state, which
        stays active.
        """
        if self.stack:
            for state_idx in range(len(self.stack) - 1):
                self.stack[state_idx].exit()
            self.stack = [self.get_current()]


class SpaceFlightSimulator(ShowBase):
    """
    Root ShowBase subclass that builds and owns every app-lifetime subsystem:
    graphics (:class:`GraphicsSettings`, :class:`GraphicsManager`), gameplay
    settings (:class:`GameplaySettings`), the state machine
    (:class:`StateManager`), input (:class:`InputContextStack` and the reader
    from :func:`reader_factory`), assets (:class:`AssetManager`), shared menu
    geometry (:class:`MenuModels`) and sound effects (:class:`SFX`), then pushes
    :class:`SplashState`.
    """

    def __init__(self, headless: bool = False):
        """
        :param headless: when True, skip the splash screen/menus (which need a
            real window) and leave the state stack empty. Intended for
            optimization-loop callers, which push :class:`FlightState` with
            headless=True themselves once the app is built.
        """
        ShowBase.__init__(self)
        self.disableMouse()

        # Use Physical Based Rendering pipeline. Messes with the ocean for now
        # import simplepbr
        # simplepbr.init()

        self.graphics_settings = GraphicsSettings()
        self.gameplay_settings = GameplaySettings()
        self.graphics_manager = GraphicsManager(app=self)
        self.state_manager = StateManager(app=self)
        self.input_context_stack = InputContextStack()
        # Real input needs a window (mouseWatcherNode), so it is skipped
        # headless. `bindings` is still loaded: input contexts (e.g.
        # FlightInputContext) read binding names even when nothing dispatches.
        if headless:
            self.bindings = load_bindings()
        else:
            self.input_reader = reader_factory(app=self)
            self.taskMgr.add(self.input_task, "input_task", sort=-100)
        self.asset_manager = AssetManager(app=self)
        self.menu_models = MenuModels(app=self)
        self.sfx = SFX(app=self)

        self.configuration = {}

        # Start with splash screen (skipped headless: it needs a real window,
        # and there is no menu flow to lead into)
        if not headless:
            self.state_manager.push(SplashState)

    def input_task(self, task: Task) -> int:
        state = self.input_reader.poll()
        self.input_context_stack.dispatch(state)
        return task.cont
