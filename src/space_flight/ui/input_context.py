"""
Input context layer.

An InputContext interprets a frame's InputState and drives game objects.
Only the top context on the InputContextStack receives input each frame, so
pushing a radial-menu context over the flight context lets the ship hold its
current trajectory while the menu is open.

Adding a new game mode means writing a new InputContext subclass and pushing
it at the right moment — no changes to the reader or the game loop.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Callable

from space_flight.utils import low_pass_filter_first_order

THROTTLE_BOOST_VALUE = 2.0
VIEW_BUTTON_INCREMENT = 1.0


# ---------------------------------------------------------------------------
# Base class and stack
# ---------------------------------------------------------------------------


class InputContext(ABC):
    """
    Abstract base for all input contexts.

    Subclasses implement :meth:`consume` to map an :class:`InputState` onto
    game actions.  :meth:`on_activate` / :meth:`on_deactivate` are called
    when the context becomes or stops being the top of the stack.
    """

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    @abstractmethod
    def consume(self, state) -> None:
        """
        Interprets *state* and drives game objects. Called once per frame
        while this context is on top of the stack.

        :param state: The :class:`~space_flight.ui.input_system.InputState`
            produced by the active reader this frame.
        """

    def clean(self) -> None:
        pass


class InputContextStack:
    """
    LIFO stack of :class:`InputContext` objects.

    Only the top context receives input.  Pushing a new context deactivates
    the previous top; popping restores it.  The stack is owned by the active
    game state (e.g. :class:`~space_flight.game.flight_state.FlightState`).
    """

    def __init__(self) -> None:
        self._stack: list[InputContext] = []

    def push(self, context: InputContext) -> None:
        """
        Pushes *context* onto the stack, making it the active context.

        :param context: The context to activate.
        """
        if self._stack:
            self._stack[-1].on_deactivate()
        self._stack.append(context)
        context.on_activate()

    def pop(self) -> None:
        """
        Removes the top context, cleans it, and re-activates the one below.
        """
        if not self._stack:
            return
        top = self._stack.pop()
        top.on_deactivate()
        top.clean()
        if self._stack:
            self._stack[-1].on_activate()

    def dispatch(self, state) -> None:
        """
        Passes *state* to the top context.  No-op if the stack is empty.

        :param state: Current frame's
            :class:`~space_flight.ui.input_system.InputState`.
        """
        if self._stack:
            self._stack[-1].consume(state)

    def clean(self) -> None:
        """Pops and cleans all remaining contexts."""
        while self._stack:
            top = self._stack.pop()
            top.on_deactivate()
            top.clean()


# ---------------------------------------------------------------------------
# FlightInputContext
# ---------------------------------------------------------------------------


class FlightInputContext(InputContext):
    """
    In-game flight context.  Maps hardware input onto ship controls, weapon
    fire, boost, targeting, and camera look.

    Bindings are loaded from the ``contexts.flight.<input_type>`` section of
    ``configuration.yaml`` so that every action can be remapped without
    touching code.

    Keyboard throttle is accumulated (+=) each frame the key is held.
    Analog throttle is read directly from the axis value.
    Yaw/pitch/roll axes on keyboard pass through a low-pass filter to
    soften the step response.
    """

    def __init__(
        self, game, player, radial_menu_factory: Callable | None = None
    ) -> None:
        """
        :param game: Active :class:`~space_flight.game.flight_state.FlightState`.
        :param player: The human :class:`~space_flight.actors.player.Player`.
        :param radial_menu_factory: Zero-argument callable that opens the radial
            menu when the ``radial_menu`` binding is pressed.  ``None`` disables
            the trigger.
        """
        self._game = game
        self._player = player
        self._radial_menu_factory = radial_menu_factory

        input_type = game.app.bindings["input_type"]
        self._input_type = input_type
        self._bindings: dict[str, str] = game.app.bindings["contexts"]["flight"][
            input_type
        ]
        self._global_bindings: dict[str, str] = game.app.bindings.get("global", {})

        # Persistent flight state
        self._throttle = 0.0  # keyboard accumulator
        self._is_boost = False

        # Keyboard axis smoothing state
        self._yaw_smoothed = 0.0
        self._pitch_smoothed = 0.0
        self._roll_smoothed = 0.0

    # ------------------------------------------------------------------
    # InputContext interface
    # ------------------------------------------------------------------

    def consume(self, state) -> None:
        """
        :param state: Current
            :class:`~space_flight.ui.input_system.InputState`.
        """
        self._handle_actions(state)
        throttle, yaw, pitch, roll = self._flight_axes(state)
        self._player.throttle = throttle
        self._player.yaw_rate = yaw
        self._player.pitch_rate = pitch
        self._player.roll_rate = roll

    def clean(self) -> None:
        self._game = None
        self._player = None
        self._radial_menu_factory = None

    # ------------------------------------------------------------------
    # Binding helpers
    # ------------------------------------------------------------------

    def _pressed(self, state, action: str) -> bool:
        key = self._bindings.get(action)
        if key and state.buttons.get(key):
            return True
        key = self._global_bindings.get(action)
        return bool(key and state.buttons.get(key))

    def _held(self, state, action: str) -> bool:
        key = self._bindings.get(action)
        if key and state.repeats.get(key):
            return True
        key = self._global_bindings.get(action)
        return bool(key and state.repeats.get(key))

    def _active(self, state, action: str) -> bool:
        """True on the frame of first press OR while held."""
        return self._pressed(state, action) or self._held(state, action)

    def _released(self, state, action: str) -> bool:
        key = self._bindings.get(action)
        if key and state.releases.get(key):
            return True
        key = self._global_bindings.get(action)
        return bool(key and state.releases.get(key))

    def _axis(self, state, action: str) -> float:
        key = self._bindings.get(action)
        if not key:
            return 0.0
        return state.axes.get(key, 0.0)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _handle_actions(self, state) -> None:
        # Fire weapons
        if self._active(state, "fire"):
            self._player.pawn.laser_cannon.fire()

        # Boost
        if self._pressed(state, "boost_on"):
            self._is_boost = True
        if self._released(state, "boost_off"):
            self._is_boost = False

        # Pause
        if self._pressed(state, "pause"):
            self._game.set_pause()

        # Target selection
        if self._pressed(state, "loop_target"):
            self._player.loop_target(1)
        if self._pressed(state, "loop_target_reverse"):
            self._player.loop_target(-1)
        if self._pressed(state, "point_target"):
            self._player.point_target()

        # Rear-view mirror
        if self._pressed(state, "toggle_mirror"):
            self._player.rear_view_mirror.toggle_mirror()

        # Radial menu
        if self._radial_menu_factory is not None and self._pressed(
            state, "radial_menu"
        ):
            self._radial_menu_factory()

        # Head-look (button-based: keyboard hat keys, joystick hat)
        if self._active(state, "view_up"):
            self._player.view_offset[0] += VIEW_BUTTON_INCREMENT
        if self._active(state, "view_down"):
            self._player.view_offset[0] -= VIEW_BUTTON_INCREMENT
        if self._active(state, "view_left"):
            self._player.view_offset[1] += VIEW_BUTTON_INCREMENT
        if self._active(state, "view_right"):
            self._player.view_offset[1] -= VIEW_BUTTON_INCREMENT

    # ------------------------------------------------------------------
    # Flight axes
    # ------------------------------------------------------------------

    def _flight_axes(self, state) -> tuple[float, float, float, float]:
        if self._input_type == "keyboard":
            return self._keyboard_axes(state)
        return self._analog_axes(state)

    def _keyboard_axes(self, state) -> tuple[float, float, float, float]:
        throttle_up = self._active(state, "throttle_up")
        throttle_down = self._active(state, "throttle_down")
        self._throttle += 0.005 * (float(throttle_up) - float(throttle_down))
        self._throttle = max(0.0, min(1.0, self._throttle))

        yaw = float(self._active(state, "yaw_left")) - float(
            self._active(state, "yaw_right")
        )
        pitch = float(self._active(state, "pitch_up")) - float(
            self._active(state, "pitch_down")
        )
        roll = float(self._active(state, "roll_right")) - float(
            self._active(state, "roll_left")
        )

        dt = self._game.game_time.get_time_step()
        self._yaw_smoothed = low_pass_filter_first_order(
            yaw, self._yaw_smoothed, dt, 0.5, 0.1
        )
        self._pitch_smoothed = low_pass_filter_first_order(
            pitch, self._pitch_smoothed, dt, 0.5, 0.1
        )
        self._roll_smoothed = low_pass_filter_first_order(
            roll, self._roll_smoothed, dt, 0.5, 0.1
        )

        throttle = THROTTLE_BOOST_VALUE if self._is_boost else self._throttle
        return throttle, self._yaw_smoothed, self._pitch_smoothed, self._roll_smoothed

    def _analog_axes(self, state) -> tuple[float, float, float, float]:
        throttle = self._axis(state, "throttle")
        yaw = self._axis(state, "yaw")
        pitch = self._axis(state, "pitch")
        roll = self._axis(state, "roll")
        if self._is_boost:
            throttle = THROTTLE_BOOST_VALUE
        return throttle, yaw, pitch, roll


# ---------------------------------------------------------------------------
# PauseMenuInputContext
# ---------------------------------------------------------------------------


class PauseMenuInputContext(InputContext):
    """
    Pushed onto the stack when the game is paused.

    Blocks all flight inputs (``FlightInputContext`` is below and not ticked).
    Pressing the pause key again calls ``state_manager.pop()``, which triggers
    ``FlightState.resume()`` and pops this context.

    Both the device-specific pause binding and the global one are checked so
    that escape always works regardless of the active input type.
    """

    def __init__(self, app) -> None:
        """
        :param app: The simulator app
        """
        self.app = app
        input_type = app.bindings["input_type"]
        device_bindings = app.bindings["contexts"]["flight"].get(input_type, {})
        global_bindings = app.bindings.get("global", {})
        pause_device = device_bindings.get("pause")
        pause_global = global_bindings.get("pause")
        self._pause_keys: frozenset[str] = frozenset(
            k for k in (pause_device, pause_global) if k
        )

    def consume(self, state) -> None:
        """
        :param state: the current input state
        """
        for key in self._pause_keys:
            if state.buttons.get(key):
                self.app.state_manager.pop()
                return

    def clean(self) -> None:
        self._game = None


# ---------------------------------------------------------------------------
# RadialMenuInputContext
# ---------------------------------------------------------------------------


def _angle_to_slice(x: float, y: float, n_slices: int) -> int:
    """
    Map a 2-D direction to a slice index.

    Slice 0 is at the top (positive-y direction) and slices are numbered
    clockwise.

    :param x: Horizontal component of the direction vector.
    :param y: Vertical component of the direction vector.
    :param n_slices: Total number of slices.
    :return: Index of the slice the direction falls into.
    """
    angle = math.atan2(y, x)
    normalized = (math.pi / 2 - angle) % (2 * math.pi)
    return int(normalized / (2 * math.pi / n_slices)) % n_slices


class RadialMenuInputContext(InputContext):
    """
    Input context active while a radial menu is open.

    Reads a 2-D direction vector each frame (from analog axes or keyboard
    directional keys, as configured in the ``radial_menu`` YAML context) and
    determines which slice the player is pointing at.  When the trigger button
    is released the ``on_select`` callback receives the chosen slice index (or
    ``None`` if the vector magnitude was below ``min_magnitude``).

    The context pops itself by calling ``state_manager.pop()`` on release,
    which causes :class:`~space_flight.menus.radial_menu_state.RadialMenuState`
    to call ``exit()`` and clean up the visual overlay.

    The context never touches game time, so the simulation keeps running while
    the menu is open.
    """

    def __init__(
        self,
        game,
        n_slices: int,
        on_select: Callable,
        trigger_hw_name: str,
        on_hover: Callable | None = None,
        min_magnitude: float = 0.8,
    ) -> None:
        """
        :param game: Active game state.
        :param n_slices: Number of radial slices.
        :param on_select: Called with the selected slice index (or ``None``)
            when the trigger is released.
        :param trigger_hw_name: Hardware name of the button that opened the
            menu.  Release of this button closes the menu.
        :param on_hover: Optional callback called every frame with the
            currently highlighted slice index (or ``None``); used to update
            the visual overlay.
        :param min_magnitude: Direction vector magnitude below which no slice
            is selected.
        """
        self._game = game
        self._n_slices = n_slices
        self._on_select = on_select
        self._trigger_hw_name = trigger_hw_name
        self._on_hover = on_hover
        self._min_magnitude = min_magnitude

        input_type = game.app.bindings["input_type"]
        self._bindings: dict[str, str] = (
            game.app.bindings.get("contexts", {})
            .get("radial_menu", {})
            .get(input_type, {})
        )
        self._selected_slice: int | None = None

    # ------------------------------------------------------------------
    # InputContext interface
    # ------------------------------------------------------------------

    def consume(self, state) -> None:
        """
        :param state: Current
            :class:`~space_flight.ui.input_reader.InputState`.
        """
        x, y = self._read_direction(state)
        mag = (x**2 + y**2) ** 0.5
        if mag >= self._min_magnitude:
            self._selected_slice = _angle_to_slice(x, y, self._n_slices)
        else:
            self._selected_slice = None

        if self._on_hover is not None:
            self._on_hover(self._selected_slice)

        if state.releases.get(self._trigger_hw_name):
            selected = self._selected_slice
            on_select = self._on_select
            self._game.app.state_manager.pop()
            on_select(selected)

    def clean(self) -> None:
        self._game = None
        self._on_select = None
        self._on_hover = None

    # ------------------------------------------------------------------
    # Direction reading
    # ------------------------------------------------------------------

    def _read_direction(self, state) -> tuple[float, float]:
        """
        Return ``(x, y)`` in ``[-1, 1]`` from analog axes or keyboard keys.

        :param state: Current input state.
        :return: ``(x, y)`` direction tuple.
        """
        ax = self._bindings.get("axis_x")
        ay = self._bindings.get("axis_y")
        if ax and ay:
            return state.axes.get(ax, 0.0), state.axes.get(ay, 0.0)

        def _active(key: str) -> float:
            if not key:
                return 0.0
            return 1.0 if (state.buttons.get(key) or state.repeats.get(key)) else 0.0

        right = _active(self._bindings.get("dir_right", ""))
        left = _active(self._bindings.get("dir_left", ""))
        up = _active(self._bindings.get("dir_up", ""))
        down = _active(self._bindings.get("dir_down", ""))
        return right - left, up - down
