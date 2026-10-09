"""
Input context layer.

An InputContext interprets a frame's InputState and drives game objects.
Only the top context on the InputContextStack receives input each frame, so
pushing a radial-menu context over the flight context lets the ship hold its
current trajectory while the menu is open.

Adding a new game mode means writing a new InputContext subclass and pushing
it at the right moment — no changes to the reader or the game loop.

Every device's bindings are live at once: an action fires from whichever
device it is bound on.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from space_flight import THROTTLE_BOOST_VALUE
from space_flight.actors.energy import BALANCED, ENGINES, LASERS, SHIELDS
from space_flight.utils import low_pass_filter_first_order

if TYPE_CHECKING:
    from space_flight.actors.player import Player
    from space_flight.game.flight_state import FlightState
    from space_flight.global_architecture.base_state import BaseState
    from space_flight.global_architecture.simulator import SpaceFlightSimulator
    from space_flight.ui.input_reader import InputState

VIEW_BUTTON_INCREMENT = 1.0

# Devices whose flight axes are read from analog values (the keyboard
# synthesises its own from buttons)
ANALOG_DEVICES = ("gamepad", "joystick")
# Keyboard throttle change per frame while a throttle key is held
KEYBOARD_THROTTLE_STEP = 0.005
# How far an analog throttle must move to take the throttle over
THROTTLE_TAKEOVER = 0.05

# Flight actions selecting an energy distribution mode
ENERGY_MODE_ACTIONS = {
    "energy_engines": ENGINES,
    "energy_lasers": LASERS,
    "energy_shields": SHIELDS,
    "energy_balanced": BALANCED,
}


def bound_keys(bindings: dict, context: str, action: str) -> frozenset[str]:
    """
    Hardware names bound to *action* under *context*, on every device.

    :param bindings: The parsed bindings config (``app.bindings``)
    :param context: The bindings context the action lives under (e.g. "flight")
    :param action: The action name within that context (e.g. "pause")
    :return: The bound hardware names, possibly empty
    """
    devices = bindings.get("contexts", {}).get(context, {})
    return frozenset(
        key
        for device_bindings in devices.values()
        if isinstance(key := device_bindings.get(action), str) and key
    )


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

    def on_activate(self):
        pass

    def on_deactivate(self):
        pass

    @abstractmethod
    def consume(self, state: InputState):
        """
        Interprets *state* and drives game objects. Called once per frame
        while this context is on top of the stack.

        :param state: The :class:`~space_flight.ui.input_reader.InputState`
            produced by the active reader this frame.
        """

    def clean(self):
        pass

    def refresh_bindings(self, app: SpaceFlightSimulator):
        pass

    @staticmethod
    def key_label(
        app: SpaceFlightSimulator, context: str, action: str, fallback: str = ""
    ) -> str:
        """
        Human-readable keybinding label for a bound action, e.g. "R" for the
        keyboard's radial_menu binding under the "flight" context.

        The one shared place for the "read the last used device's raw binding
        and uppercase it" pattern needed to show a keybinding to the player
        (e.g. a HUD prompt or an on-screen hint) so it stays correct if they
        rebind the key, instead of every caller hardcoding a key name or
        re-deriving this lookup itself.

        :param app: The simulator app; its input reader tells the last used
            device (keyboard without a reader, e.g. headless)
        :param context: The bindings context the action lives under (e.g. "flight")
        :param action: The action name within that context (e.g. "radial_menu")
        :param fallback: Returned instead if the action has no binding
        :return: The uppercased key label, or fallback
        """
        reader = getattr(app, "input_reader", None)
        device = getattr(reader, "last_device", "keyboard")
        key = (
            app.bindings.get("contexts", {})
            .get(context, {})
            .get(device, {})
            .get(action, "")
        )
        return key.upper() if key else fallback


class InputContextStack:
    """
    LIFO stack of :class:`InputContext` objects.

    Only the top context receives input.  Pushing a new context deactivates
    the previous top; popping restores it.  The stack is owned by the app
    (``SpaceFlightSimulator.input_context_stack``); states push and pop
    their own contexts on it.
    """

    def __init__(self):
        self.stack: list[InputContext] = []

    def push(self, context: InputContext):
        """
        Pushes *context* onto the stack, making it the active context.

        :param context: The context to activate.
        """
        if self.stack:
            self.stack[-1].on_deactivate()
        self.stack.append(context)
        context.on_activate()

    def pop(self):
        """
        Removes the top context, cleans it, and re-activates the one below.
        """
        if not self.stack:
            return
        top = self.stack.pop()
        top.on_deactivate()
        top.clean()
        if self.stack:
            self.stack[-1].on_activate()

    def dispatch(self, state: InputState):
        """
        Passes *state* to the top context.  No-op if the stack is empty.

        :param state: Current frame's
            :class:`~space_flight.ui.input_reader.InputState`.
        """
        if self.stack:
            self.stack[-1].consume(state)

    def clean(self):
        """Pops and cleans all remaining contexts."""
        while self.stack:
            top = self.stack.pop()
            top.on_deactivate()
            top.clean()

    def refresh_all_bindings(self, app: SpaceFlightSimulator):
        """Call refresh_bindings on every context in the stack."""
        for context in self.stack:
            context.refresh_bindings(app)


# ---------------------------------------------------------------------------
# FlightInputContext
# ---------------------------------------------------------------------------


class FlightInputContext(InputContext):
    """
    In-game flight context.  Maps hardware input onto ship controls, weapon
    fire, boost, targeting, and camera look.

    Bindings are loaded from the contexts.flight section of bindings.yaml,
    every device at once, so that every action can be remapped without
    touching code.

    Yaw/pitch/roll add up across devices; the keyboard's pass through a
    low-pass filter first to soften the step response.

    The throttle follows the device that last touched it: the keyboard steps
    it (+=) each frame a throttle key is held, from wherever it is, and an
    analog throttle sets it directly once moved by more than
    THROTTLE_TAKEOVER, so a lever left forward does not hold it.
    """

    def __init__(
        self,
        game: FlightState,
        player: Player,
        radial_menu_factory: Callable | None = None,
    ):
        """
        :param game: Active :class:`~space_flight.game.flight_state.FlightState`.
        :param player: The human :class:`~space_flight.actors.player.Player`.
        :param radial_menu_factory: Zero-argument callable that opens the radial
            menu when the radial_menu binding is pressed.  None disables
            the trigger.
        """
        self.game = game
        self.player = player
        self.radial_menu_factory = radial_menu_factory

        self.refresh_bindings(game.app)

        # Persistent flight state
        self.throttle = 0.0
        # Device driving the throttle (None until one touches it)
        self.throttle_owner: str | None = None
        # Each analog throttle's value when it last owned the throttle (or
        # when first seen): moving away from it takes the throttle over
        self.throttle_anchors: dict[str, float] = {}
        self.is_boost = False

        # Keyboard axis smoothing state
        self.yaw_smoothed = 0.0
        self.pitch_smoothed = 0.0
        self.roll_smoothed = 0.0

    # ------------------------------------------------------------------
    # InputContext interface
    # ------------------------------------------------------------------

    def consume(self, state: InputState):
        """
        :param state: Current
            :class:`~space_flight.ui.input_reader.InputState`.
        """
        self.handle_actions(state)
        throttle, yaw, pitch, roll = self.flight_axes(state)
        self.player.throttle = throttle
        self.player.yaw_rate = yaw
        self.player.pitch_rate = pitch
        self.player.roll_rate = roll

    def clean(self):
        self.game = None
        self.player = None
        self.radial_menu_factory = None

    def refresh_bindings(self, app: SpaceFlightSimulator):
        self.bindings = app.bindings

    # ------------------------------------------------------------------
    # Binding helpers
    # ------------------------------------------------------------------

    def pressed(self, state: InputState, action: str) -> bool:
        keys = bound_keys(self.bindings, "flight", action)
        return any(state.buttons.get(key) for key in keys)

    def held(self, state: InputState, action: str) -> bool:
        keys = bound_keys(self.bindings, "flight", action)
        return any(state.repeats.get(key) for key in keys)

    def active(self, state: InputState, action: str) -> bool:
        """True on the frame of first press OR while held."""
        return self.pressed(state, action) or self.held(state, action)

    def released(self, state: InputState, action: str) -> bool:
        keys = bound_keys(self.bindings, "flight", action)
        return any(state.releases.get(key) for key in keys)

    def axis(self, state: InputState, device: str, action: str) -> float | None:
        """
        :param state: Current input state.
        :param device: The device whose binding is read (e.g. "gamepad").
        :param action: The axis action (e.g. "yaw").
        :return: The bound axis value, inverted if configured, or None if the
            action is unbound or the device is not connected.
        """
        device_bindings = self.bindings["contexts"]["flight"].get(device, {})
        key = device_bindings.get(action)
        if not key or key not in state.axes:
            return None
        value = state.axes[key]
        if device_bindings.get(f"invert_{action}"):
            value = -value
        return value

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def handle_actions(self, state: InputState):
        # Pause
        if self.pressed(state, "pause"):
            self.game.set_pause()

        # While dying, the controls are dead (see Player.move_player). Weapons
        # and targeting would also look up the player's pawn, which
        # Player.begin_death has removed from the interactions.
        if self.player.is_dying:
            return

        # Fire weapons
        if self.active(state, "fire"):
            self.player.pawn.laser_cannon.fire()

        # Secondary weapon (bombs, rockets, missiles) and flares. Launches are
        # self-guarding: they refuse while reloading or out of stock, so holding
        # the key just fires at the reload rate, and a ship without that ordnance
        # is a harmless no-op.
        if self.pressed(state, "cycle_secondary"):
            self.player.pawn.cycle_secondary()
        if self.active(state, "fire_secondary"):
            self.player.pawn.fire_secondary()
        if self.active(state, "drop_flare"):
            self.player.pawn.drop_flare()

        # Boost
        if self.pressed(state, "boost_on"):
            self.is_boost = True
        if self.released(state, "boost_off"):
            self.is_boost = False

        # Energy distribution: favour one system, back to balanced, or cycle
        energy = self.player.pawn.energy
        for action, mode in ENERGY_MODE_ACTIONS.items():
            if self.pressed(state, action):
                energy.set_mode(mode)
        if self.pressed(state, "cycle_energy"):
            energy.cycle_mode()

        # Target selection
        if self.pressed(state, "loop_target"):
            self.player.loop_target(1)
        if self.pressed(state, "loop_target_reverse"):
            self.player.loop_target(-1)
        if self.pressed(state, "point_target"):
            self.player.point_target()

        # Rear-view mirror
        if self.pressed(state, "toggle_mirror"):
            self.player.rear_view_mirror.toggle_mirror()

        # Radial menu
        if self.radial_menu_factory is not None and self.pressed(state, "radial_menu"):
            self.radial_menu_factory()

        # Head-look (button-based: keyboard hat keys, joystick hat)
        if self.active(state, "view_up"):
            self.player.view_offset[0] += VIEW_BUTTON_INCREMENT
        if self.active(state, "view_down"):
            self.player.view_offset[0] -= VIEW_BUTTON_INCREMENT
        if self.active(state, "view_left"):
            self.player.view_offset[1] += VIEW_BUTTON_INCREMENT
        if self.active(state, "view_right"):
            self.player.view_offset[1] -= VIEW_BUTTON_INCREMENT

    # ------------------------------------------------------------------
    # Flight axes
    # ------------------------------------------------------------------

    def flight_axes(self, state: InputState) -> tuple[float, float, float, float]:
        yaw, pitch, roll = self.keyboard_rates(state)
        for device in ANALOG_DEVICES:
            yaw += self.axis(state, device, "yaw") or 0.0
            pitch += self.axis(state, device, "pitch") or 0.0
            roll += self.axis(state, device, "roll") or 0.0
        throttle = self.update_throttle(state)
        if self.is_boost:
            throttle = THROTTLE_BOOST_VALUE
        return throttle, clamp_unit(yaw), clamp_unit(pitch), clamp_unit(roll)

    def keyboard_rates(self, state: InputState) -> tuple[float, float, float]:
        """
        :param state: Current input state.
        :return: The smoothed (yaw, pitch, roll) from the rotation keys.
        """
        yaw = float(self.active(state, "yaw_left")) - float(
            self.active(state, "yaw_right")
        )
        pitch = float(self.active(state, "pitch_up")) - float(
            self.active(state, "pitch_down")
        )
        roll = float(self.active(state, "roll_right")) - float(
            self.active(state, "roll_left")
        )

        dt = self.game.game_time.get_time_step()
        self.yaw_smoothed = low_pass_filter_first_order(
            value=yaw, previous=self.yaw_smoothed, dt=dt, rise_time=0.05, fall_time=0.01
        )
        self.pitch_smoothed = low_pass_filter_first_order(
            value=pitch,
            previous=self.pitch_smoothed,
            dt=dt,
            rise_time=0.05,
            fall_time=0.01,
        )
        self.roll_smoothed = low_pass_filter_first_order(
            value=roll,
            previous=self.roll_smoothed,
            dt=dt,
            rise_time=0.05,
            fall_time=0.01,
        )
        return self.yaw_smoothed, self.pitch_smoothed, self.roll_smoothed

    def update_throttle(self, state: InputState) -> float:
        """
        Hands the throttle to the device that last touched it and returns it.

        :param state: Current input state.
        :return: The throttle, before boost.
        """
        for device in ANALOG_DEVICES:
            value = self.axis(state, device, "throttle")
            if value is None:
                continue
            anchor = self.throttle_anchors.setdefault(device, value)
            if device == self.throttle_owner or abs(value - anchor) > THROTTLE_TAKEOVER:
                self.throttle_owner = device
                self.throttle_anchors[device] = value
                self.throttle = value

        throttle_up = self.active(state, "throttle_up")
        throttle_down = self.active(state, "throttle_down")
        if throttle_up or throttle_down:
            # Steps from the current throttle, whichever device set it
            self.throttle_owner = "keyboard"
            self.throttle += KEYBOARD_THROTTLE_STEP * (
                float(throttle_up) - float(throttle_down)
            )
            self.throttle = max(0.0, min(1.0, self.throttle))
        return self.throttle


def clamp_unit(value: float) -> float:
    """
    :param value: Any value.
    :return: *value* clamped to [-1, 1].
    """
    return max(-1.0, min(1.0, value))


# ---------------------------------------------------------------------------
# PauseMenuInputContext
# ---------------------------------------------------------------------------


class PauseMenuInputContext(InputContext):
    """
    Pushed onto the stack when the game is paused.

    Blocks all flight inputs (FlightInputContext is below and not ticked).
    Pressing the pause key again calls state_manager.pop(), popping the top
    menu state (normally PauseMenuState, whose exit() pops this context and
    lets FlightState resume).

    The flight pause binding of every device is checked.
    """

    def __init__(self, app: SpaceFlightSimulator):
        """
        :param app: The simulator app
        """
        self.app = app
        self.pause_keys = bound_keys(app.bindings, "flight", "pause")

    def consume(self, state: InputState):
        """
        :param state: the current input state
        """
        for key in self.pause_keys:
            if state.buttons.get(key):
                self.app.state_manager.pop()
                return

    def refresh_bindings(self, app: SpaceFlightSimulator):
        self.pause_keys = bound_keys(app.bindings, "flight", "pause")

    def clean(self):
        self.game = None


# ---------------------------------------------------------------------------
# HyperspaceInputContext
# ---------------------------------------------------------------------------


class HyperspaceInputContext(InputContext):
    """
    Pushed while the hyperspace loading screen waits for the player to drop out.

    It is a thin trigger: each time the drop_hyperspace key is pressed it
    calls *on_trigger* until the callback accepts it (returns True), then
    ignores further input (the level reveal pops it).
    Being on top of the stack, it also blocks the flight context below
    so the ship cannot be controlled until the world is revealed.

    The drop_hyperspace binding of every device is honoured.
    """

    def __init__(self, app: SpaceFlightSimulator, on_trigger: Callable):
        """
        :param app: the simulator app
        :param on_trigger: zero-argument callback fired on key press; returns
            True when the press was accepted (the context then latches)
        """
        self.app = app
        self.on_trigger = on_trigger
        self.triggered = False
        self.drop_keys = bound_keys(app.bindings, "hyperspace", "drop_hyperspace")

    def consume(self, state: InputState):
        """
        :param state: the current input state
        """
        if self.triggered:
            return
        for key in self.drop_keys:
            if state.buttons.get(key):
                # Latch only once the callback accepts the press: the overlay
                # may not be waiting for the key yet, and an early press must
                # not use up the trigger.
                if self.on_trigger():
                    self.triggered = True
                return

    def refresh_bindings(self, app: SpaceFlightSimulator):
        self.drop_keys = bound_keys(app.bindings, "hyperspace", "drop_hyperspace")

    def clean(self):
        self.on_trigger = None


# ---------------------------------------------------------------------------
# RadialMenuInputContext
# ---------------------------------------------------------------------------


def angle_to_slice(x: float, y: float, n_slices: int) -> int:
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

    Reads a 2-D direction vector each frame (the sum over every device of its
    analog axes or directional keys, as configured in the radial_menu YAML
    context) and
    determines which slice the player is pointing at.  The last slice pointed
    at stays selected when the direction returns to the dead zone, until
    another slice is pointed at.  When a trigger button is released the
    on_select callback receives the chosen slice index (or None if no slice was
    ever pointed at, i.e. the vector magnitude never reached min_magnitude).

    On release it calls state_manager.pop(); the exit() of
    :class:`~space_flight.menus.radial_menu_state.RadialMenuState` then pops
    this context and destroys the visual overlay.
    """

    def __init__(
        self,
        game: BaseState,
        n_slices: int,
        on_select: Callable,
        trigger_hw_names: frozenset[str],
        on_hover: Callable | None = None,
        min_magnitude: float = 0.8,
    ):
        """
        :param game: Active game state.
        :param n_slices: Number of radial slices.
        :param on_select: Called with the selected slice index (or None)
            when the trigger is released.
        :param trigger_hw_names: Hardware names of the buttons that open the
            menu, on every device.  Releasing any of them closes the menu.
        :param on_hover: Optional callback called every frame with the
            currently highlighted slice index (or None); used to update
            the visual overlay.
        :param min_magnitude: Direction vector magnitude below which no slice
            is selected.
        """
        self.game = game
        self.n_slices = n_slices
        self.on_select = on_select
        self.trigger_hw_names = trigger_hw_names
        self.on_hover = on_hover
        self.min_magnitude = min_magnitude

        self.bindings: dict[str, dict] = game.app.bindings.get("contexts", {}).get(
            "radial_menu", {}
        )
        self.selected_slice: int | None = None

    # ------------------------------------------------------------------
    # InputContext interface
    # ------------------------------------------------------------------

    def consume(self, state: InputState):
        """
        :param state: Current
            :class:`~space_flight.ui.input_reader.InputState`.
        """
        x, y = self.read_direction(state)
        mag = (x**2 + y**2) ** 0.5
        # The selection is latched: returning the stick to centre (or letting
        # go of the direction key) before releasing the trigger keeps the last
        # slice, so the player doesn't have to release both at the same instant.
        if mag >= self.min_magnitude:
            self.selected_slice = angle_to_slice(x, y, self.n_slices)

        if self.on_hover is not None:
            self.on_hover(self.selected_slice)

        if any(state.releases.get(key) for key in self.trigger_hw_names):
            selected = self.selected_slice
            on_select = self.on_select
            self.game.app.state_manager.pop()
            on_select(selected)

    def clean(self):
        self.game = None
        self.on_select = None
        self.on_hover = None

    # ------------------------------------------------------------------
    # Direction reading
    # ------------------------------------------------------------------

    def read_direction(self, state: InputState) -> tuple[float, float]:
        """
        Return (x, y) summed over every device's direction.

        :param state: Current input state.
        :return: (x, y) direction tuple.
        """
        x = y = 0.0
        for device_bindings in self.bindings.values():
            dx, dy = self.device_direction(state, device_bindings)
            x += dx
            y += dy
        return x, y

    @staticmethod
    def device_direction(state: InputState, bindings: dict) -> tuple[float, float]:
        """
        Return (x, y) in [-1, 1] from one device's analog axes or keys.

        :param state: Current input state.
        :param bindings: The device's radial_menu bindings.
        :return: (x, y) direction tuple.
        """
        ax = bindings.get("axis_x")
        ay = bindings.get("axis_y")
        if ax and ay:
            return state.axes.get(ax, 0.0), state.axes.get(ay, 0.0)

        def active(key: str) -> float:
            if not key:
                return 0.0
            return 1.0 if (state.buttons.get(key) or state.repeats.get(key)) else 0.0

        right = active(bindings.get("dir_right", ""))
        left = active(bindings.get("dir_left", ""))
        up = active(bindings.get("dir_up", ""))
        down = active(bindings.get("dir_down", ""))
        return right - left, up - down
