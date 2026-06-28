import logging

from direct.showbase.ShowBase import ShowBase
from panda3d.core import loadPrcFileData

from space_flight.fx.sfx import SFX
from space_flight.game.flight_state import FlightState
from space_flight.game.hyperspace_loading_state import HyperspaceLoadingState
from space_flight.game.loading_state import LoadingState
from space_flight.global_architecture.asset_manager import AssetManager
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.death_menu_state import DeathMenuState
from space_flight.menus.input_settings_menu_state import InputSettingsMenuState
from space_flight.menus.level_selection_menu_state import LevelSelectionMenuState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.menu_utils import MenuModels
from space_flight.menus.pause_menu_state import PauseMenuState
from space_flight.menus.radial_menu_state import RadialMenuState
from space_flight.menus.splash_state import SplashState
from space_flight.ui.input_context import InputContextStack
from space_flight.ui.input_reader import reader_factory

LOGGER = logging.getLogger()


loadPrcFileData("", "notify-level-ffmpeg error")

# NOTE: we do NOT enable Panda's on-disk cache (model-cache-dir). It is the only
# switch for the compiled-shader binary cache, but it also routes glTF loading
# through panda3d-gltf, whose calculate_tangents() crashes on models containing
# a non-triangle primitive (e.g. the x-wing cockpit: "not enough values to
# unpack (expected 3, got 2)"). Shader compilation was measured at ~4ms and was
# never the loading bottleneck, so the cache is not worth breaking model loading.


class StateManager:
    """
    Stack-based state machine whose topmost entry is the active state.

    Only one state is active at any given time; every other entry on the
    stack is either paused or acting as an inactive background state.
    All concrete state classes are declared as class attributes so that
    any module in the project can reference them through ``StateManager``
    without needing direct imports of individual state modules.
    """

    SPLASH_STATE = SplashState
    MAIN_MENU_STATE = MainMenuState
    LEVEL_SELECTION_MENU_STATE = LevelSelectionMenuState
    PAUSE_MENU_STATE = PauseMenuState
    INPUT_SETTINGS_STATE = InputSettingsMenuState
    RADIAL_MENU_STATE = RadialMenuState
    DEATH_MENU_STATE = DeathMenuState
    GAME_STATE = FlightState
    LOADING_STATE = LoadingState
    HYPERSPACE_LOADING_STATE = HyperspaceLoadingState

    def __init__(self, app):
        self.app = app
        self.stack: list[BaseState] = []

    def push(self, state_class: BaseState, **kwargs):
        """
        Pushes a new state onto the stack and activates it.

        Pauses the current top state first, unless *state_class* declares
        ``PAUSES_BELOW = False`` (e.g. overlays that keep game time running).
        Extra *kwargs* are forwarded to the state constructor.

        :param state_class:
            The state class to instantiate and push onto the stack.
        :param kwargs:
            Optional keyword arguments forwarded verbatim to the
            *state_class* constructor.
        """
        if self.stack and getattr(state_class, "PAUSES_BELOW", True):
            self.stack[-1].pause()
        state_instance = state_class(self.app, **kwargs)
        self.stack.append(state_instance)
        state_instance.enter()

    def pop(self: BaseState):
        """
        Exits and removes the current top state, then resumes the one below it.

        Calls ``exit()`` on the state that is removed. If the stack is not
        empty afterwards, calls ``resume()`` on the new top state. Logs a
        warning and returns early when the stack is already empty.
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
        Replaces the current top state with a new one at the same stack depth.

        Equivalent to calling :meth:`pop` followed by :meth:`push`. The
        replaced state is exited and discarded; *state_class* is entered in
        its place.

        :param state_class:
            The state class to instantiate and place at the top of the stack,
            replacing whatever state was there before.
        """
        self.pop()
        self.push(state_class)

    def get_current(self):
        """
        Returns the state currently at the top of the stack.

        :return:
            The active :class:`BaseState` instance, or ``None`` if the stack
            is empty.
        """
        return self.stack[-1] if self.stack else None

    def clear(self):
        """
        Exits and discard every state below the current top state.

        The topmost state is preserved and remains active. All other entries
        have their ``exit()`` method called before being removed from the
        stack.
        """
        if self.stack:
            for state_idx in range(len(self.stack) - 1):
                self.stack[state_idx].exit()
            self.stack = [self.get_current()]


class SpaceFlightSimulator(ShowBase):
    """
    Root ShowBase subclass that wires together all subsystems of the game.

    Responsible for initialising and owning every major subsystem: the
    state machine (:class:`StateManager`), input pipeline
    (:class:`InputContextStack` and the reader returned by
    :func:`reader_factory`), asset loading (:class:`AssetManager`), shared
    menu geometry (:class:`MenuModels`), and sound effects (:class:`SFX`).
    The constructor ends by pushing the initial :class:`SplashState` onto
    the state manager to begin the application flow.
    """

    def __init__(self):
        ShowBase.__init__(self)
        self.disableMouse()

        # Use Physical Based Rendering pipeline. Messes with the ocean for now
        # import simplepbr
        # simplepbr.init()

        self.state_manager = StateManager(app=self)
        self.input_context_stack = InputContextStack()
        self.input_reader = reader_factory(app=self)
        self.taskMgr.add(self.input_task, "input_task", sort=-100)
        self.asset_manager = AssetManager(app=self)
        self.menu_models = MenuModels(app=self)
        self.sfx = SFX(app=self)

        self.configuration = {}

        # Start with splash screen
        self.state_manager.push(SplashState)

    def input_task(self, task):
        state = self.input_reader.poll()
        self.input_context_stack.dispatch(state)
        return task.cont
