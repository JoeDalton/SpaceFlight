"""
Input system — hardware layer.

Responsibilities:
- Read physical device state each frame (polling).
- Register accept() for press/release events as a safety net for brief inputs
  that polling might miss between frames.
- Derive pressed / held / released per button by comparing current poll to the
  previous frame.
- Apply dead zones to axis values.
- Store everything in a plain InputState that contexts read.
- Run every device reader at once and merge their states, so the keyboard,
  a gamepad and a flight stick can all be used at the same time.

No game logic lives here.  Contexts (see input_context.py) decide what a
button press *means* in a given game mode.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml
from direct.showbase.DirectObject import DirectObject
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    ButtonHandle,
    ButtonRegistry,
    ButtonThrower,
    GamepadButton,
    InputDevice,
    InputDeviceNode,
    MouseWatcher,
    WindowProperties,
)

from space_flight import CONFIGURATION_PATH

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator

DEFAULT_STICK_DEAD_ZONE = 0.15
DEFAULT_THROTTLE_DEAD_ZONE = 0.04

# ---------------------------------------------------------------------------
# Panda3D monkey-patch (Windows UTF-8 device-name workaround)
# ---------------------------------------------------------------------------


def _patched_attachInputDevice(
    self: ShowBase,
    device: InputDevice,
    prefix: str | None = None,
    watch: bool = False,
):
    """
    Monkey-patch for :meth:`ShowBase.attachInputDevice` that avoids a
    UnicodeDecodeError on Windows.

    Panda3D's original implementation reads device.name via a C++ property
    that can return a raw byte string containing non-UTF-8 characters for some
    controllers.  Accessing that property in Python then raises a
    UnicodeDecodeError and crashes the game.  This replacement never
    touches device.name directly; :func:`safe_device_name` is used
    wherever a printable name is needed.

    For the same reason, when no *prefix* is supplied the
    :class:`~panda3d.core.InputDeviceNode` and its
    :class:`~panda3d.core.ButtonThrower` are both named "gamepad" instead
    of after the device.

    :param device: The input device to attach.
    :param prefix: Optional event prefix string forwarded to
        :class:`~panda3d.core.ButtonThrower`.
    :param watch: Also route the device into the mouse watcher, as in
        ShowBase; without a *prefix*, no button thrower is created then.

    TODO Propose this as a contribution to panda3d
    """
    assert device not in self._ShowBase__inputDeviceNodes
    idn = self.dataRoot.attachNewNode(InputDeviceNode(device, prefix or "gamepad"))
    if prefix is not None or not watch:
        bt = idn.attachNewNode(ButtonThrower(prefix or "gamepad"))
        if prefix is not None:
            bt.node().setPrefix(prefix + "-")
        self.deviceButtonThrowers.append(bt)
    self._ShowBase__inputDeviceNodes[device] = idn
    if watch:
        idn.node().addChild(self.mouseWatcherNode)


ShowBase.attachInputDevice = _patched_attachInputDevice


def _patched_detachInputDevice(self: ShowBase, device: InputDevice):
    """
    Monkey-patch for :meth:`ShowBase.detachInputDevice` that avoids a
    UnicodeDecodeError on Windows.

    Panda3D's original implementation reads device.name via a C++ property
    that can return a raw byte string containing non-UTF-8 characters for some
    controllers.  Accessing that property in Python then raises a
    UnicodeDecodeError and crashes the game.  This replacement mirrors the
    original ShowBase logic exactly, with the single fix of routing all
    device-name access through :func:`safe_device_name` instead of
    device.name.

    :param device: The input device to detach.
    """
    if device not in self._ShowBase__inputDeviceNodes:
        assert device in self._ShowBase__inputDeviceNodes
        return

    assert self.notify.debug("Detached device {0}".format(safe_device_name(device)))

    idn = self._ShowBase__inputDeviceNodes[device]
    for bt in self.deviceButtonThrowers:
        if idn.isAncestorOf(bt):
            self.deviceButtonThrowers.remove(bt)
            break

    idn.removeNode()
    del self._ShowBase__inputDeviceNodes[device]


ShowBase.detachInputDevice = _patched_detachInputDevice


def safe_device_name(device: InputDevice) -> str:
    """
    Returns a printable name for *device*, working around a UTF-8 crash on
    Windows.

    Panda3D's device.name C++ property can return bytes containing
    non-UTF-8 characters for controllers with non-ASCII manufacturer strings.
    Three increasingly defensive strategies are attempted in order:

    1. Read device.name directly (works for most controllers).
    2. Re-encode via raw_unicode_escape and decode as Windows-1252.
    3. Build a VID_xxxx&PID_xxxx string from the USB vendor / product IDs.

    If all three fail, "Device (unknown)" is returned.

    :param device: The input device whose name is needed.
    :return: A printable device name string.
    """
    try:
        return device.name
    except UnicodeDecodeError:
        pass
    try:
        return device.name.encode("raw_unicode_escape").decode(
            "windows-1252", errors="replace"
        )
    except Exception:
        pass
    try:
        return f"Device (VID_{device.vendor_id:04X}&PID_{device.product_id:04X})"
    except Exception:
        return "Device (unknown)"


# ---------------------------------------------------------------------------
# Hardware name → Panda3D ButtonHandle mappings
# ---------------------------------------------------------------------------

GAMEPAD_BUTTON_CODES: dict[str, object] = {
    "gamepad_lshoulder": GamepadButton.lshoulder(),
    "gamepad_rshoulder": GamepadButton.rshoulder(),
    "gamepad_start": GamepadButton.start(),
    "gamepad_back": GamepadButton.back(),
    "gamepad_face_a": GamepadButton.face_a(),
    "gamepad_face_b": GamepadButton.face_b(),
    "gamepad_face_x": GamepadButton.face_x(),
    "gamepad_face_y": GamepadButton.face_y(),
    "gamepad_dpad_up": GamepadButton.dpad_up(),
    "gamepad_dpad_down": GamepadButton.dpad_down(),
    "gamepad_dpad_left": GamepadButton.dpad_left(),
    "gamepad_dpad_right": GamepadButton.dpad_right(),
    "gamepad_lstick": GamepadButton.lstick(),
    "gamepad_rstick": GamepadButton.rstick(),
}

# Axis names that must NOT be treated as buttons when scanning context bindings
GAMEPAD_AXIS_NAMES: frozenset[str] = frozenset(
    {"left_x", "left_y", "right_x", "right_y", "right_trigger", "left_trigger"}
)
JOYSTICK_AXIS_NAMES: frozenset[str] = frozenset({"pitch", "roll", "yaw", "throttle"})

# An axis pushed past this makes its device the last used one (see
# CompositeInputReader.last_device)
LAST_DEVICE_AXIS_THRESHOLD = 0.5

# Menu navigation keys (see MenuInputContext), hardcoded and polled whatever
# the bindings; the joystick's come from its flight bindings instead
MENU_BUTTONS: dict[str, dict[str, tuple[str, ...]]] = {
    "keyboard": {
        "up": ("arrow_up",),
        "down": ("arrow_down",),
        "left": ("arrow_left",),
        "right": ("arrow_right",),
        "confirm": ("enter", "space"),
        "back": ("escape",),
    },
    "gamepad": {
        "up": ("gamepad_dpad_up",),
        "down": ("gamepad_dpad_down",),
        "left": ("gamepad_dpad_left",),
        "right": ("gamepad_dpad_right",),
        "confirm": ("gamepad_face_a",),
        "back": ("gamepad_face_b",),
    },
}


def layout_only_keys(app: SpaceFlightSimulator) -> dict[str, str]:
    """
    The keys of the current keyboard layout that Panda3D only reports as raw
    (physical) buttons: those typing a non-ASCII character, such as é, è, ç, à
    or ù on a French keyboard. Panda3D throws no button event for them, and
    the MouseWatcher does not track them; only their raw events fire, named
    after the key's place on a US keyboard ("raw-2" for é on a French one).

    :param app: The Panda3D application instance
    :return: The raw button name of each such key, by the character it types
        (lowercase); empty without a window
    """
    window = getattr(app, "win", None)
    keyboard_map = window.getKeyboardMap() if window is not None else None
    if keyboard_map is None:
        return {}
    keys: dict[str, str] = {}
    for index in range(keyboard_map.getNumButtons()):
        if keyboard_map.getMappedButton(index) != ButtonHandle.none():
            continue
        label = keyboard_map.getMappedButtonLabel(index).lower()
        if label:
            keys.setdefault(label, keyboard_map.getRawButton(index).getName())
    return keys


# ---------------------------------------------------------------------------
# InputState  — plain data container, written by the reader, read by contexts
# ---------------------------------------------------------------------------


class InputState:
    """
    Snapshot of hardware input for one frame.

    buttons  — hardware names whose button transitioned up→down this frame.
    repeats  — hardware names that were held down both this frame and last.
    releases — hardware names that transitioned down→up this frame.
    axes     — dead-zoned continuous axis values.
    mouse_moved — whether the mouse pointer moved this frame (set by
               :class:`CompositeInputReader` only).

    All dicts are rebuilt each frame by each :class:`InputReader`, and merged
    by :class:`CompositeInputReader`.  Contexts must not mutate them.
    """

    __slots__ = ("buttons", "repeats", "releases", "axes", "mouse_moved")

    def __init__(self):
        self.buttons: dict[str, bool] = {}
        self.repeats: dict[str, bool] = {}
        self.releases: dict[str, bool] = {}
        self.axes: dict[str, float] = {}
        self.mouse_moved = False

    def clear(self):
        """Empty the per-frame dicts (mouse_moved is set on its own)."""
        self.buttons.clear()
        self.repeats.clear()
        self.releases.clear()
        self.axes.clear()


# ---------------------------------------------------------------------------
# InputReader base class
# ---------------------------------------------------------------------------


class InputReader(DirectObject):
    """
    Base class for all device readers.

    Each reader is its own DirectObject so that its accept() callbacks
    (e.g. connect-device) never replace another reader's.

    Hybrid detection strategy
    -------------------------
    * **Polling** (primary) — read_all_buttons() returns the current
      hardware state each frame.  Comparison with previous gives
      pressed / held / released without duplicates.
    * **Events** (safety net) — accept() callbacks for press and release
      write into ev_pressed / ev_released.  They are merged with the
      comparison pass to catch inputs that were pressed *and* released
      between two frames.
    * **Deduplication** — the two sources may report the same press (or
      release) on different frames, e.g. the event one frame after polling
      saw the button go down.  A per-button logical state (``logical_down``)
      reports a press only if the button is not already known to be down,
      and a release only if it is not already known to be up.
    * event-repeat is intentionally **not** registered; repeated-held
      state is derived from polling alone.
    """

    # Device key of this reader's bindings under each context
    # ("keyboard", "gamepad" or "joystick")
    device_type: str = ""

    def __init__(self, app: SpaceFlightSimulator):
        """
        Initialises shared polling buffers.

        :param app: The Panda3D application instance; app.bindings must
            already be populated (see :func:`reader_factory`).
        """
        self.app = app
        self.state = InputState()
        self.previous: dict[str, bool] = {}
        # Whether each button is known to be down, from either source (absent
        # until first seen): dedupes a press reported by both polling and an
        # event on different frames
        self.logical_down: dict[str, bool] = {}
        self.ev_pressed: set[str] = set()
        self.ev_released: set[str] = set()
        self.app.disableMouse()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> InputState:
        """
        Reads all hardware, derives per-button transitions, and returns the
        updated :class:`InputState`.  Call exactly once per game frame.

        Steps performed each call:

        1. :meth:`read_all_buttons` returns the raw current button state.
        2. Comparison with the previous frame, merged with the event
           safety-net sets (which catch inputs both pressed and released
           between two polls), produces buttons (newly pressed), repeats
           (held), and releases (newly released) -- each press or release
           reported once, even when both sources see it on different frames.
        3. :meth:`read_axes` populates state.axes.

        :return: The updated :class:`InputState` for this frame.
        """
        current = self.read_all_buttons()

        self.state.clear()

        for name in current.keys() | self.ev_pressed | self.ev_released:
            is_down = current.get(name, False)
            was_down = self.previous.get(name, False)
            pressed = (is_down and not was_down) or name in self.ev_pressed
            released = (not is_down and was_down) or name in self.ev_released
            known_down = self.logical_down.get(name)

            if pressed and released:
                if known_down:
                    # Released, then pressed again, between two polls
                    self.state.releases[name] = True
                    self.state.buttons[name] = True
                else:
                    # A brief tap between two polls
                    self.state.buttons[name] = True
                    self.state.releases[name] = True
                    self.logical_down[name] = False
            elif pressed:
                if known_down:
                    # The other source already reported this press
                    if is_down:
                        self.state.repeats[name] = True
                else:
                    self.state.buttons[name] = True
                    self.logical_down[name] = True
            elif released:
                if known_down is not False:
                    self.state.releases[name] = True
                self.logical_down[name] = False
            elif is_down and was_down:
                self.state.repeats[name] = True

        self.ev_pressed.clear()
        self.ev_released.clear()

        self.previous = current
        self.read_axes(self.state)
        return self.state

    def clean(self):
        """
        Unregisters all accept() callbacks and releases held references.

        Must be called before the reader is discarded — for example when the
        user saves new settings and the reader is rebuilt from the updated
        configuration.  Subclasses that hold devices must call super().clean()
        after releasing them.
        """
        self.ignoreAll()
        self.app = None
        self.state = None
        self.previous = None
        self.ev_pressed = None
        self.ev_released = None

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Returns the current raw button state as a {hardware_name: is_down}
        mapping.

        Called once per :meth:`poll` call.  Subclasses implement this using
        the appropriate hardware API (MouseWatcher for keyboard, direct device
        polling for gamepad / joystick).

        :return: Dict mapping each configured hardware name to its pressed
            state this frame.
        """
        raise NotImplementedError

    #: The device axes read_axes reads (see _read_device_axes)
    AXES: tuple = ()

    def _read_device_axes(self, device: InputDevice, state: InputState):
        """
        Read and dead-zone the device's :attr:`AXES` into state.axes.

        :param device: The connected device
        :param state: The :class:`InputState` being built
        """
        dead_zones = {
            "stick": self.dead_zones.get("stick", DEFAULT_STICK_DEAD_ZONE),
            "throttle": self.dead_zones.get("throttle", DEFAULT_THROTTLE_DEAD_ZONE),
        }
        for name, axis, dead_zone, inverted in self.AXES:
            value = device.findAxis(axis).value
            if inverted:
                value = 1 - value
            state.axes[name] = self.apply_dead_zone(value, dead_zones[dead_zone])

    def read_axes(self, state: InputState):
        """
        Populates state.axes with dead-zoned axis values for this frame.

        Called at the end of :meth:`poll`.  Subclasses implement this using
        the appropriate hardware API.  Keyboard readers leave this as a no-op
        because virtual axes are synthesised by the input context layer.

        :param state: The :class:`InputState` being built; populate
            state.axes in place.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def apply_dead_zone(value: float, dead_zone: float) -> float:
        """
        Applies a symmetric dead zone to a raw axis value.

        Values within ±*dead_zone* of centre are zeroed; values outside are
        shifted towards zero by *dead_zone* so that the output starts at zero
        at the dead-zone boundary (not renormalised: full deflection gives
        1 - dead_zone).

        :param value: Raw axis value in the range [-1, 1].
        :param dead_zone: Half-width of the dead-zone band.
        :return: Dead-zoned axis value.
        """
        if abs(value) < dead_zone:
            return 0.0
        return value - np.sign(value) * dead_zone

    def collect_button_names(self, axis_names: frozenset[str]) -> frozenset[str]:
        """
        Scans all context bindings and returns the hardware names that are
        buttons (i.e. not continuous axes).

        Reads every binding value of this reader's :attr:`device_type` across
        all contexts and excludes any name present in *axis_names*, then adds
        the device's :data:`MENU_BUTTONS`.

        :param axis_names: Frozenset of hardware names that represent
            continuous axes and must not be polled as buttons.
        :return: Frozenset of button hardware names from the configuration.
        """
        names: set[str] = set()
        for ctx_data in self.app.bindings.get("contexts", {}).values():
            for hw_name in ctx_data.get(self.device_type, {}).values():
                if isinstance(hw_name, str) and hw_name not in axis_names:
                    names.add(hw_name)
        for hw_names in MENU_BUTTONS.get(self.device_type, {}).values():
            names.update(hw_names)
        return frozenset(names)


# ---------------------------------------------------------------------------
# KeyboardReader
# ---------------------------------------------------------------------------


class KeyboardReader(InputReader):
    """
    Reads keyboard state via Panda3D's MouseWatcher (polling) plus
    accept() events as a safety net.

    Keys typing a non-ASCII character (see :func:`layout_only_keys`) are bound
    by that character, but the MouseWatcher never sees them: their state comes
    from their raw events instead.
    """

    device_type = "keyboard"

    def __init__(self, app: SpaceFlightSimulator):
        """
        Collects bound key names and registers safety-net event callbacks.

        Calls :meth:`~InputReader.collect_button_names` with an empty axis
        set (keyboards have no analogue axes), then registers accept()
        callbacks for every bound key so that short presses between polls are
        not missed.

        :param app: The Panda3D application instance.
        """
        super().__init__(app)
        self.button_names = self.collect_button_names(frozenset())
        self.registry = ButtonRegistry.ptr()

        # Bound keys only reported as raw buttons: their raw button names, and
        # whether each is down, from its raw events
        layout_keys = layout_only_keys(app)
        self.raw_keys: dict[str, str] = {
            key: layout_keys[key.lower()]
            for key in self.button_names
            if key.lower() in layout_keys
        }
        self.raw_down: dict[str, bool] = {}

        for key in self.button_names:
            if key in self.raw_keys:
                event = "raw-" + self.raw_keys[key]
                self.accept(event, self.on_raw_key, [key, True])
                self.accept(event + "-up", self.on_raw_key, [key, False])
            else:
                self.accept(key, lambda k=key: self.ev_pressed.add(k))
                self.accept(key + "-up", lambda k=key: self.ev_released.add(k))

    def on_raw_key(self, key: str, is_down: bool):
        """
        Tracks a key only reported as a raw button.

        :param key: The key's binding name
        :param is_down: Whether the event is its press (else its release)
        """
        self.raw_down[key] = is_down
        (self.ev_pressed if is_down else self.ev_released).add(key)

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls every bound key via the MouseWatcher, or, for keys only
        reported as raw buttons, from their raw events.

        :return: Dict mapping hardware name → True if the key is
            currently held down.
        """
        result: dict[str, bool] = {}
        for key in self.button_names:
            if key in self.raw_keys:
                result[key] = self.raw_down.get(key, False)
                continue
            handle = self.registry.getButton(key)
            result[key] = self.app.mouseWatcherNode.isButtonDown(handle)
        return result

    def read_axes(self, state: InputState):
        """
        No-op — keyboards have no physical axes.

        Virtual axes (throttle, pitch, etc.) are synthesised from button
        states by the flight input context layer.

        :param state: Unused.
        """
        pass  # Keyboard has no physical axes; FlightInputContext synthesises them


# ---------------------------------------------------------------------------
# GamepadReader
# ---------------------------------------------------------------------------


class GamepadReader(InputReader):
    """
    Reads gamepad state.  Named buttons support both polling and events.
    Axes are dead-zoned only; sign flips come from the invert_* bindings
    applied by :class:`~space_flight.ui.input_context.FlightInputContext`.
    """

    device_type = "gamepad"
    #: (state axis name, device axis, dead zone kind, inverted)
    AXES = (
        ("right_trigger", InputDevice.Axis.right_trigger, "throttle", False),
        ("left_trigger", InputDevice.Axis.left_trigger, "throttle", False),
        ("left_x", InputDevice.Axis.left_x, "stick", False),
        ("left_y", InputDevice.Axis.left_y, "stick", False),
        ("right_x", InputDevice.Axis.right_x, "stick", False),
        ("right_y", InputDevice.Axis.right_y, "stick", False),
    )

    def __init__(self, app: SpaceFlightSimulator):
        """
        Detects a connected gamepad and registers hot-plug and button events.

        If a gamepad is already connected it is attached immediately via
        :meth:`connect`.  Hot-plug events are accepted so the reader adapts at
        runtime; with no gamepad, the reader simply reports nothing.

        Safety-net accept() callbacks are registered for every bound
        button, mapping Panda3D's "gamepad-lshoulder" event names to the
        "gamepad_lshoulder" hardware names used in the configuration.

        :param app: The Panda3D application instance.
        """
        super().__init__(app)
        self.button_names = self.collect_button_names(GAMEPAD_AXIS_NAMES)
        self.dead_zones = app.bindings.get("dead_zones", {})
        self.gamepad = None

        devices = app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self.connect(devices[0])

        self.accept("connect-device", self.connect)
        self.accept("disconnect-device", self.disconnect)

        # Safety-net events for named gamepad buttons
        # Hardware name "gamepad_lshoulder" → Panda3D event "gamepad-lshoulder"
        for hw in self.button_names:
            evt = "gamepad-" + hw[len("gamepad_") :]
            self.accept(evt, lambda n=hw: self.ev_pressed.add(n))
            self.accept(evt + "-up", lambda n=hw: self.ev_released.add(n))

    # ------------------------------------------------------------------

    def connect(self, device: InputDevice):
        """
        Attaches *device* if it is a gamepad and no gamepad is already active.

        :param device: The device that was just connected.
        """
        if device.device_class == InputDevice.DeviceClass.gamepad and not self.gamepad:
            print(f"Gamepad connected: {safe_device_name(device)}")
            self.gamepad = device
            self.app.attachInputDevice(device, prefix="gamepad")

    def disconnect(self, device: InputDevice):
        """
        Detaches *device* and falls back to another gamepad if one is available.

        :param device: The device that was just disconnected.
        """
        if self.gamepad != device:
            return
        print(f"Gamepad disconnected: {safe_device_name(device)}")
        self.app.detachInputDevice(device)
        self.gamepad = None
        devices = self.app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self.connect(devices[0])

    # ------------------------------------------------------------------

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls the physical state of every bound gamepad button.

        Uses :data:`GAMEPAD_BUTTON_CODES` to map hardware names to Panda3D
        :class:`~panda3d.core.GamepadButton` handles, then reads the
        pressed flag directly from the device.

        :return: Dict mapping hardware name → True if the button is held.
        """
        if not self.gamepad:
            return dict.fromkeys(self.button_names, False)
        result: dict[str, bool] = {}
        for hw in self.button_names:
            code = GAMEPAD_BUTTON_CODES.get(hw)
            if code is not None:
                btn = self.gamepad.findButton(code)
                result[hw] = bool(btn.pressed) if btn else False
            else:
                result[hw] = False
        return result

    def read_axes(self, state: InputState):
        """
        Reads and dead-zones all six gamepad axes into state.axes.

        :param state: The :class:`InputState` being built; state.axes is
            populated in place.
        """
        if not self.gamepad:
            return
        self._read_device_axes(self.gamepad, state)

    def clean(self):
        """
        Detaches the gamepad, then delegates to the base class.
        """
        if self.gamepad:
            with contextlib.suppress(AssertionError):
                self.app.detachInputDevice(self.gamepad)
            self.gamepad = None
        super().clean()


# ---------------------------------------------------------------------------
# JoystickReader
# ---------------------------------------------------------------------------


class JoystickReader(InputReader):
    """
    Reads flight-stick state.  Buttons are polled directly because unnamed
    buttons on most sticks do not generate Panda3D events reliably; no
    safety-net accept() is registered for them.
    """

    device_type = "joystick"
    #: (state axis name, device axis, dead zone kind, inverted). The throttle
    #: is inverted (1 - raw), so pulling the lever towards the pilot
    #: increases it.
    AXES = (
        ("throttle", InputDevice.Axis.throttle, "throttle", True),
        ("yaw", InputDevice.Axis.yaw, "stick", False),
        ("pitch", InputDevice.Axis.pitch, "stick", False),
        ("roll", InputDevice.Axis.roll, "stick", False),
    )

    def __init__(self, app: SpaceFlightSimulator):
        """
        Detects a connected flight stick and registers hot-plug events.

        Unlike :class:`GamepadReader`, no safety-net button event callbacks
        are registered because most flight-stick buttons do not generate
        reliable Panda3D events; button state is read by polling only.

        :param app: The Panda3D application instance.
        """
        super().__init__(app)
        self.button_names = self.collect_button_names(JOYSTICK_AXIS_NAMES)
        self.dead_zones = app.bindings.get("dead_zones", {})
        self.flightStick = None

        devices = app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])

        self.accept("connect-device", self.connect)
        self.accept("disconnect-device", self.disconnect)
        # No button events — polling-only for joystick buttons

    # ------------------------------------------------------------------

    def connect(self, device: InputDevice):
        """
        Attaches *device* if it is a flight stick and none is already active.

        :param device: The device that was just connected.
        """
        if (
            device.device_class == InputDevice.DeviceClass.flight_stick
            and not self.flightStick
        ):
            print(f"Joystick connected: {device}")
            self.flightStick = device
            self.app.attachInputDevice(device, prefix="stick")

    def disconnect(self, device: InputDevice):
        """
        Detaches *device* and falls back to another flight stick if available.

        :param device: The device that was just disconnected.
        """
        if self.flightStick != device:
            return
        print(f"Joystick disconnected: {device}")
        self.app.detachInputDevice(device)
        self.flightStick = None
        devices = self.app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])

    # ------------------------------------------------------------------

    @staticmethod
    def button_index(hw_name: str) -> int | None:
        """
        Converts a "stick_button_N" name to a zero-based hardware index.

        Joystick buttons are addressed by index in the device's button array.
        The YAML convention uses 1-based names (stick_button_1 is index 0).

        :param hw_name: Hardware name such as "stick_button_3".
        :return: Zero-based button index, or None if the trailing suffix
            is not a digit string.
        """
        suffix = hw_name.rsplit("_", 1)[-1]
        return int(suffix) - 1 if suffix.isdigit() else None

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls every bound flight-stick button by its zero-based hardware index.

        Returns all-false when no stick is connected or when a button index
        is out of range for the attached device.

        :return: Dict mapping hardware name → True if the button is held.
        """
        if not self.flightStick:
            return dict.fromkeys(self.button_names, False)
        n = len(self.flightStick.buttons)
        result: dict[str, bool] = {}
        for hw in self.button_names:
            idx = self.button_index(hw)
            result[hw] = (
                bool(self.flightStick.buttons[idx].pressed)
                if idx is not None and 0 <= idx < n
                else False
            )
        return result

    def read_axes(self, state: InputState):
        """
        Reads and dead-zones the four flight-stick axes into state.axes.

        The throttle axis is inverted (1 − raw) so that pulling the lever
        towards the pilot increases the output value.

        :param state: The :class:`InputState` being built; state.axes is
            populated in place.
        """
        if not self.flightStick:
            return
        self._read_device_axes(self.flightStick, state)

    def clean(self):
        """
        Detaches the flight stick, then delegates to the base class.
        """
        if self.flightStick:
            self.app.detachInputDevice(self.flightStick)
            self.flightStick = None
        super().clean()


# ---------------------------------------------------------------------------
# CompositeInputReader
# ---------------------------------------------------------------------------


class CompositeInputReader:
    """
    Polls every device reader each frame and merges their states, so the
    keyboard, a gamepad and a flight stick can all be used at the same time.

    Hardware names never collide across devices (keyboard keys,
    gamepad_* / left_x…, stick_button_N / pitch…), so merging is a plain
    dict union.  Each reader keeps its own transition state.

    It also tells whether the mouse moved (InputState.mouse_moved), and hides
    the mouse cursor while another device is in use, showing it again as
    soon as the mouse moves.  While hidden, the GUI ignores the pointer, so
    an invisible cursor never hovers a widget (e.g. one a newly opened menu
    draws under it).
    """

    def __init__(self, app: SpaceFlightSimulator, readers: list[InputReader]):
        """
        :param app: The Panda3D application instance.
        :param readers: The device readers to poll, one per device type.
        """
        self.app = app
        self.readers = readers
        self.state = InputState()
        # Device type of the last reader that saw a button press or an axis
        # pushed past LAST_DEVICE_AXIS_THRESHOLD; picks which binding the
        # on-screen prompts show (see InputContext.key_label)
        self.last_device = "keyboard"
        # Axes currently past the threshold: only crossing it counts, so a
        # throttle lever resting forward does not keep claiming last_device
        self.pushed_axes: set[str] = set()
        self.mouse_position: tuple[float, float] | None = None
        # Given to the GUI while the cursor is hidden: outside the data graph,
        # it never sees the mouse
        self.blind_mouse_watcher = MouseWatcher("hidden-cursor")

    def poll(self) -> InputState:
        """
        Polls every reader and merges their states, then updates the cursor.
        Call exactly once per game frame.

        :return: The merged :class:`InputState` for this frame.
        """
        self.state.clear()
        device_used = False
        for reader in self.readers:
            state = reader.poll()
            if state.buttons or self.update_pushed_axes(state.axes):
                self.last_device = reader.device_type
                device_used = True
            self.state.buttons.update(state.buttons)
            self.state.repeats.update(state.repeats)
            self.state.releases.update(state.releases)
            self.state.axes.update(state.axes)
        self.state.mouse_moved = self.read_mouse_moved()
        if self.state.mouse_moved:
            self.set_cursor_hidden(False)
        elif device_used:
            self.set_cursor_hidden(True)
        return self.state

    def read_mouse_moved(self) -> bool:
        """
        :return: True if the mouse pointer moved since last frame.
        """
        watcher = self.app.mouseWatcherNode
        if not watcher.hasMouse():
            return False
        position = (watcher.getMouseX(), watcher.getMouseY())
        moved = self.mouse_position is not None and position != self.mouse_position
        self.mouse_position = position
        return moved

    def set_cursor_hidden(self, hidden: bool):
        """
        Hides or shows the mouse cursor, if not already, and makes the GUI
        ignore the pointer while hidden.

        :param hidden: Whether the cursor should be hidden.
        """
        window = self.app.win
        if window is None or window.getProperties().getCursorHidden() == hidden:
            return
        properties = WindowProperties()
        properties.setCursorHidden(hidden)
        window.requestProperties(properties)
        self.app.aspect2d.node().setMouseWatcher(
            self.blind_mouse_watcher if hidden else self.app.mouseWatcherNode
        )

    def update_pushed_axes(self, axes: dict[str, float]) -> bool:
        """
        Tracks which axes are pushed past LAST_DEVICE_AXIS_THRESHOLD.

        :param axes: One reader's axis values this frame.
        :return: True if any axis crossed the threshold this frame.
        """
        crossed = False
        for name, value in axes.items():
            if abs(value) > LAST_DEVICE_AXIS_THRESHOLD:
                crossed |= name not in self.pushed_axes
                self.pushed_axes.add(name)
            else:
                self.pushed_axes.discard(name)
        return crossed

    def clean(self):
        """
        Cleans every reader.  Must be called before the reader is discarded.
        """
        for reader in self.readers:
            reader.clean()
        self.readers = []


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def load_bindings(path: Path = CONFIGURATION_PATH / "bindings.yaml") -> dict:
    """
    Reads and parses a bindings file, configuration/bindings.yaml by default.

    Drops the keys of older files that every device being live at once made
    obsolete (input_type, global), so they are not saved back.

    :param path: Path to the YAML bindings file.
    :return: Parsed configuration dict.
    """
    with open(path, "r") as f:
        bindings = yaml.safe_load(f)
    for key in ("input_type", "global"):
        bindings.pop(key, None)
    return bindings


def reader_factory(app: SpaceFlightSimulator) -> CompositeInputReader:
    """
    Loads the configuration, stores it on app.bindings, and builds a reader
    for every device type, merged into one :class:`CompositeInputReader`.

    Called at application startup and again when the user saves new settings
    so the reader reflects updated hardware names and dead zones without a
    restart.

    :param app: The Panda3D application instance.
    :return: A :class:`CompositeInputReader` ready to be polled each frame.
    """
    app.bindings = load_bindings()
    return CompositeInputReader(
        app,
        [KeyboardReader(app=app), GamepadReader(app=app), JoystickReader(app=app)],
    )
