"""
Input system — hardware layer.

Responsibilities:
- Read physical device state each frame (polling).
- Register accept() for press/release events as a safety net for brief inputs
  that polling might miss between frames.
- Derive pressed / held / released per button by comparing current poll to the
  previous frame.
- Apply dead zones and produce normalised axis values.
- Store everything in a plain InputState that contexts read.

No game logic lives here.  Contexts (see input_context.py) decide what a
button press *means* in a given game mode.
"""

from __future__ import annotations

import numpy as np
import yaml
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    ButtonRegistry,
    ButtonThrower,
    GamepadButton,
    InputDevice,
    InputDeviceNode,
)

from space_flight import CONFIGURATION_PATH

DEFAULT_STICK_DEAD_ZONE = 0.15
DEFAULT_THROTTLE_DEAD_ZONE = 0.04

# ---------------------------------------------------------------------------
# Panda3D monkey-patch (preserves existing workaround for Windows UTF-8 bug)
# ---------------------------------------------------------------------------


def _patched_attachInputDevice(self, device, prefix=None, watch=False):
    """
    Some controllers have a name with characters that crash the game on
    Windows.  This replaces the Panda3D method to work around the issue.

    TODO: Propose this as a contribution to panda3d
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


def safe_device_name(device) -> str:
    """
    Returns a printable name for a device, working around Panda3D's UTF-8 bug
    on Windows machines.
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


# ---------------------------------------------------------------------------
# InputState  — plain data container, written by the reader, read by contexts
# ---------------------------------------------------------------------------


class InputState:
    """
    Snapshot of hardware input for one frame.

    ``buttons``  — hardware names whose button transitioned up→down this frame.
    ``repeats``  — hardware names that were held down both this frame and last.
    ``releases`` — hardware names that transitioned down→up this frame.
    ``axes``     — normalised, dead-zoned continuous axis values.

    All dicts are rebuilt each frame by :class:`InputReader`.  Contexts must
    not mutate them.
    """

    __slots__ = ("buttons", "repeats", "releases", "axes")

    def __init__(self) -> None:
        self.buttons: dict[str, bool] = {}
        self.repeats: dict[str, bool] = {}
        self.releases: dict[str, bool] = {}
        self.axes: dict[str, float] = {}


# ---------------------------------------------------------------------------
# InputReader base class
# ---------------------------------------------------------------------------


class InputReader:
    """
    Base class for all device readers.

    Hybrid detection strategy
    -------------------------
    * **Polling** (primary) — ``_read_all_buttons()`` returns the current
      hardware state each frame.  Comparison with ``_previous`` gives
      pressed / held / released without duplicates.
    * **Events** (safety net) — ``accept()`` callbacks for press and release
      write into ``_ev_pressed`` / ``_ev_released``.  After the comparison
      pass these sets are OR-merged into ``buttons`` / ``releases`` to catch
      inputs that were pressed *and* released between two frames.
    * ``event-repeat`` is intentionally **not** registered; repeated-held
      state is derived from polling alone.
    """

    def __init__(self, app) -> None:
        self._app = app
        self._state = InputState()
        self._previous: dict[str, bool] = {}
        self._ev_pressed: set[str] = set()
        self._ev_released: set[str] = set()
        self._app.disableMouse()

        # Universal keyboard bindings
        # Registered on every reader regardless of device type
        self._global_keys: list[str] = list(app.bindings.get("global", {}).values())
        for hw_name in self._global_keys:
            app.accept(hw_name, lambda n=hw_name: self._ev_pressed.add(n))
            app.accept(hw_name + "-up", lambda n=hw_name: self._ev_released.add(n))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> InputState:
        """
        Reads all hardware, derives transitions, returns the updated
        :class:`InputState`.  Call exactly once per game frame.
        """
        current = self._read_all_buttons()

        self._state.buttons.clear()
        self._state.repeats.clear()
        self._state.releases.clear()
        self._state.axes.clear()

        for name, is_down in current.items():
            was_down = self._previous.get(name, False)
            if is_down and not was_down:
                self._state.buttons[name] = True
            elif is_down and was_down:
                self._state.repeats[name] = True
            elif not is_down and was_down:
                self._state.releases[name] = True

        # Safety-net: catch brief press/release invisible to frame-rate polling
        for name in self._ev_pressed:
            self._state.buttons[name] = True
        for name in self._ev_released:
            self._state.releases[name] = True
        self._ev_pressed.clear()
        self._ev_released.clear()

        self._previous = current
        self._read_axes(self._state)
        return self._state

    def clean(self) -> None:
        for hw_name in self._global_keys:
            self._app.ignore(hw_name)
            self._app.ignore(hw_name + "-up")
        self._global_keys = None
        self._app = None
        self._state = None
        self._previous = None
        self._ev_pressed = None
        self._ev_released = None

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    def _read_all_buttons(self) -> dict[str, bool]:
        raise NotImplementedError

    def _read_axes(self, state: InputState) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _collect_button_names(self, axis_names: frozenset[str]) -> frozenset[str]:
        """
        Scans all context bindings for the current input type and returns the
        set of hardware names that are NOT axes.
        """
        input_type = self._app.bindings["input_type"]
        names: set[str] = set()
        for ctx_data in self._app.bindings.get("contexts", {}).values():
            for hw_name in ctx_data.get(input_type, {}).values():
                if hw_name not in axis_names:
                    names.add(hw_name)
        return frozenset(names)


# ---------------------------------------------------------------------------
# KeyboardReader
# ---------------------------------------------------------------------------


class KeyboardReader(InputReader):
    """
    Reads keyboard state via Panda3D's MouseWatcher (polling) plus
    ``accept()`` events as a safety net.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._button_names = self._collect_button_names(frozenset())
        self._registry = ButtonRegistry.ptr()

        for key in self._button_names:
            app.accept(key, lambda k=key: self._ev_pressed.add(k))
            app.accept(key + "-up", lambda k=key: self._ev_released.add(k))

    def _read_all_buttons(self) -> dict[str, bool]:
        result: dict[str, bool] = {}
        for key in self._button_names:
            handle = self._registry.getButton(key)
            result[key] = self._app.mouseWatcherNode.isButtonDown(handle)
        return result

    def _read_axes(self, state: InputState) -> None:
        pass  # Keyboard has no physical axes; FlightInputContext synthesises them

    def clean(self) -> None:
        for key in self._button_names:
            self._app.ignore(key)
            self._app.ignore(key + "-up")
        super().clean()


# ---------------------------------------------------------------------------
# GamepadReader
# ---------------------------------------------------------------------------


class GamepadReader(InputReader):
    """
    Reads gamepad state.  Named buttons support both polling and events.
    Axes are dead-zoned; left stick and trigger axes are sign-corrected to
    match the expected flight control directions.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._button_names = self._collect_button_names(GAMEPAD_AXIS_NAMES)
        self._dead_zones = app.bindings.get("dead_zones", {})
        self.gamepad = None

        devices = app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self._connect(devices[0])
        else:
            self._lbl = OnscreenText(
                text="No gamepad found", fg=(1, 0, 0, 1), scale=0.2
            )

        app.accept("connect-device", self._connect)
        app.accept("disconnect-device", self._disconnect)

        # Safety-net events for named gamepad buttons
        # Hardware name "gamepad_lshoulder" → Panda3D event "gamepad-lshoulder"
        for hw in self._button_names:
            evt = "gamepad-" + hw[len("gamepad_") :]
            app.accept(evt, lambda n=hw: self._ev_pressed.add(n))
            app.accept(evt + "-up", lambda n=hw: self._ev_released.add(n))

    # ------------------------------------------------------------------

    def _connect(self, device) -> None:
        if device.device_class == InputDevice.DeviceClass.gamepad and not self.gamepad:
            print(f"Gamepad connected: {safe_device_name(device)}")
            self.gamepad = device
            self._app.attachInputDevice(device, prefix="gamepad")
            if hasattr(self, "_lbl"):
                self._lbl.hide()

    def _disconnect(self, device) -> None:
        if self.gamepad != device:
            return
        print(f"Gamepad disconnected: {safe_device_name(device)}")
        self._app.detachInputDevice(device)
        self.gamepad = None
        devices = self._app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self._connect(devices[0])
        elif hasattr(self, "_lbl"):
            self._lbl.show()

    # ------------------------------------------------------------------

    def _read_all_buttons(self) -> dict[str, bool]:
        if not self.gamepad:
            return {name: False for name in self._button_names}
        result: dict[str, bool] = {}
        for hw in self._button_names:
            code = GAMEPAD_BUTTON_CODES.get(hw)
            if code is not None:
                btn = self.gamepad.findButton(code)
                result[hw] = bool(btn.pressed) if btn else False
            else:
                result[hw] = False
        return result

    @staticmethod
    def _dz(value: float, dead_zone: float) -> float:
        if abs(value) < dead_zone:
            return 0.0
        return value - np.sign(value) * dead_zone

    def _read_axes(self, state: InputState) -> None:
        if not self.gamepad:
            return
        sdz = self._dead_zones.get("stick", DEFAULT_STICK_DEAD_ZONE)
        tdz = self._dead_zones.get("throttle", DEFAULT_THROTTLE_DEAD_ZONE)

        # Sign conventions match the original Gamepad.get_inputs() behaviour
        state.axes["right_trigger"] = self._dz(
            self.gamepad.findAxis(InputDevice.Axis.right_trigger).value, tdz
        )
        state.axes["left_trigger"] = self._dz(
            self.gamepad.findAxis(InputDevice.Axis.left_trigger).value, tdz
        )
        state.axes["left_x"] = self._dz(
            -self.gamepad.findAxis(InputDevice.Axis.left_x).value, sdz
        )
        state.axes["left_y"] = self._dz(
            -self.gamepad.findAxis(InputDevice.Axis.left_y).value, sdz
        )
        state.axes["right_x"] = self._dz(
            self.gamepad.findAxis(InputDevice.Axis.right_x).value, sdz
        )
        state.axes["right_y"] = self._dz(
            self.gamepad.findAxis(InputDevice.Axis.right_y).value, sdz
        )

    def clean(self) -> None:
        if self.gamepad:
            try:
                self._app.detachInputDevice(self.gamepad)
            except AssertionError:
                pass
            self.gamepad = None
        if hasattr(self, "_lbl"):
            self._lbl.destroy()
        for hw in self._button_names:
            evt = "gamepad-" + hw[len("gamepad_") :]
            self._app.ignore(evt)
            self._app.ignore(evt + "-up")
        self._app.ignore("connect-device")
        self._app.ignore("disconnect-device")
        super().clean()


# ---------------------------------------------------------------------------
# JoystickReader
# ---------------------------------------------------------------------------


class JoystickReader(InputReader):
    """
    Reads flight-stick state.  Buttons are polled directly because unnamed
    buttons on most sticks do not generate Panda3D events reliably; no
    safety-net ``accept()`` is registered for them.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._button_names = self._collect_button_names(JOYSTICK_AXIS_NAMES)
        self._dead_zones = app.bindings.get("dead_zones", {})
        self.flightStick = None

        devices = app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self._connect(devices[0])
        else:
            self._lbl = OnscreenText(
                text="No joystick found", fg=(1, 0, 0, 1), scale=0.2
            )

        app.accept("connect-device", self._connect)
        app.accept("disconnect-device", self._disconnect)
        # No button events — polling-only for joystick buttons

    # ------------------------------------------------------------------

    def _connect(self, device) -> None:
        if (
            device.device_class == InputDevice.DeviceClass.flight_stick
            and not self.flightStick
        ):
            print(f"Joystick connected: {device}")
            self.flightStick = device
            self._app.attachInputDevice(device, prefix="stick")
            if hasattr(self, "_lbl"):
                self._lbl.hide()

    def _disconnect(self, device) -> None:
        if self.flightStick != device:
            return
        print(f"Joystick disconnected: {device}")
        self._app.detachInputDevice(device)
        self.flightStick = None
        devices = self._app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self._connect(devices[0])
        elif hasattr(self, "_lbl"):
            self._lbl.show()

    # ------------------------------------------------------------------

    @staticmethod
    def _button_index(hw_name: str) -> int | None:
        """
        ``"stick_button_1"`` → ``0`` (0-indexed).
        Returns None for non-numeric names.
        """
        suffix = hw_name.rsplit("_", 1)[-1]
        return int(suffix) - 1 if suffix.isdigit() else None

    def _read_all_buttons(self) -> dict[str, bool]:
        if not self.flightStick:
            return {name: False for name in self._button_names}
        n = len(self.flightStick.buttons)
        result: dict[str, bool] = {}
        for hw in self._button_names:
            idx = self._button_index(hw)
            result[hw] = (
                bool(self.flightStick.buttons[idx].pressed)
                if idx is not None and 0 <= idx < n
                else False
            )
        return result

    @staticmethod
    def _dz(value: float, dead_zone: float) -> float:
        if abs(value) < dead_zone:
            return 0.0
        return value - np.sign(value) * dead_zone

    def _read_axes(self, state: InputState) -> None:
        if not self.flightStick:
            return
        sdz = self._dead_zones.get("stick", DEFAULT_STICK_DEAD_ZONE)
        tdz = self._dead_zones.get("throttle", DEFAULT_THROTTLE_DEAD_ZONE)

        state.axes["throttle"] = self._dz(
            1 - self.flightStick.findAxis(InputDevice.Axis.throttle).value, tdz
        )
        state.axes["yaw"] = self._dz(
            self.flightStick.findAxis(InputDevice.Axis.yaw).value, sdz
        )
        state.axes["pitch"] = self._dz(
            self.flightStick.findAxis(InputDevice.Axis.pitch).value, sdz
        )
        state.axes["roll"] = self._dz(
            self.flightStick.findAxis(InputDevice.Axis.roll).value, sdz
        )

    def clean(self) -> None:
        if self.flightStick:
            self._app.detachInputDevice(self.flightStick)
            self.flightStick = None
        if hasattr(self, "_lbl"):
            self._lbl.destroy()
        self._app.ignore("connect-device")
        self._app.ignore("disconnect-device")
        super().clean()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def load_bindings() -> dict:
    filepath = CONFIGURATION_PATH / "configuration.yaml"
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


def reader_factory(app) -> InputReader:
    """
    Loads configuration, stores it on ``app.bindings``, and returns the
    appropriate :class:`InputReader` subclass.
    """
    app.bindings = load_bindings()
    input_type = app.bindings["input_type"]
    if input_type == "keyboard":
        return KeyboardReader(app=app)
    elif input_type == "gamepad":
        return GamepadReader(app=app)
    elif input_type == "joystick":
        return JoystickReader(app=app)
    else:
        raise NotImplementedError(f"Unknown input_type: {input_type!r}")
