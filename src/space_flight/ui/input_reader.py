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
    Monkey-patch for :meth:`ShowBase.attachInputDevice` that avoids a
    ``UnicodeDecodeError`` on Windows.

    Panda3D's original implementation reads ``device.name`` via a C++ property
    that can return a raw byte string containing non-UTF-8 characters for some
    controllers.  Accessing that property in Python then raises a
    ``UnicodeDecodeError`` and crashes the game.  This replacement never
    touches ``device.name`` directly; :func:`safe_device_name` is used
    wherever a printable name is needed.

    A second existing workaround is also preserved: when no *prefix* is
    supplied the :class:`~panda3d.core.InputDeviceNode` and its
    :class:`~panda3d.core.ButtonThrower` are both named ``"gamepad"`` instead
    of falling back to the device's native name.

    :param device: The input device to attach.
    :param prefix: Optional event prefix string forwarded to
        :class:`~panda3d.core.ButtonThrower`.  Defaults to ``None``.

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


def _patched_detachInputDevice(self, device):
    """
    Monkey-patch for :meth:`ShowBase.detachInputDevice` that avoids a
    ``UnicodeDecodeError`` on Windows.

    Panda3D's original implementation reads ``device.name`` via a C++ property
    that can return a raw byte string containing non-UTF-8 characters for some
    controllers.  Accessing that property in Python then raises a
    ``UnicodeDecodeError`` and crashes the game.  This replacement mirrors the
    original ShowBase logic exactly, with the single fix of routing all
    device-name access through :func:`safe_device_name` instead of
    ``device.name``.

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


def safe_device_name(device) -> str:
    """
    Returns a printable name for *device*, working around a UTF-8 crash on
    Windows.

    Panda3D's ``device.name`` C++ property can return bytes containing
    non-UTF-8 characters for controllers with non-ASCII manufacturer strings.
    Three increasingly defensive strategies are attempted in order:

    1. Read ``device.name`` directly (works for most controllers).
    2. Re-encode via ``raw_unicode_escape`` and decode as Windows-1252.
    3. Build a ``VID_xxxx&PID_xxxx`` string from the USB vendor / product IDs.

    If all three fail, ``"Device (unknown)"`` is returned.

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
        """
        Initialises shared polling buffers and register global key callbacks.

        Sets up the per-frame comparison state and event-safety-net sets, then
        registers ``accept()`` callbacks for every key listed under
        ``app.bindings["global"]`` so that short presses that polling might
        miss between frames are still captured.

        :param app: The Panda3D application instance; ``app.bindings`` must
            already be populated (see :func:`reader_factory`).
        """
        self.app = app
        self.state = InputState()
        self.previous: dict[str, bool] = {}
        self.ev_pressed: set[str] = set()
        self.ev_released: set[str] = set()
        self.app.disableMouse()

        # Universal keyboard bindings
        # Registered on every reader regardless of device type
        self.global_keys: list[str] = list(app.bindings.get("global", {}).values())
        for hw_name in self.global_keys:
            app.accept(hw_name, lambda n=hw_name: self.ev_pressed.add(n))
            app.accept(hw_name + "-up", lambda n=hw_name: self.ev_released.add(n))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> InputState:
        """
        Reads all hardware, derives per-button transitions, and returns the
        updated :class:`InputState`.  Call exactly once per game frame.

        Steps performed each call:

        1. :meth:`_read_all_buttons` returns the raw current button state.
        2. Comparison with the previous frame produces ``buttons`` (newly
           pressed), ``repeats`` (held), and ``releases`` (newly released).
        3. The event-safety-net sets are OR-merged to catch inputs that were
           both pressed and released between two polls.
        4. :meth:`_read_axes` populates ``state.axes``.

        :return: The updated :class:`InputState` for this frame.
        """
        current = self.read_all_buttons()

        self.state.buttons.clear()
        self.state.repeats.clear()
        self.state.releases.clear()
        self.state.axes.clear()

        for name, is_down in current.items():
            was_down = self.previous.get(name, False)
            if is_down and not was_down:
                self.state.buttons[name] = True
            elif is_down and was_down:
                self.state.repeats[name] = True
            elif not is_down and was_down:
                self.state.releases[name] = True

        # Safety-net: catch brief press/release invisible to frame-rate polling
        for name in self.ev_pressed:
            self.state.buttons[name] = True
        for name in self.ev_released:
            self.state.releases[name] = True
        self.ev_pressed.clear()
        self.ev_released.clear()

        self.previous = current
        self.read_axes(self.state)
        return self.state

    def clean(self) -> None:
        """
        Unregisters all ``accept()`` callbacks and release held references.

        Must be called before the reader is discarded — for example when the
        user saves new settings and the reader is rebuilt from the updated
        configuration.  Subclasses that register additional handlers must call
        ``super().clean()`` after their own cleanup.
        """
        for hw_name in self.global_keys:
            self.app.ignore(hw_name)
            self.app.ignore(hw_name + "-up")
        self.global_keys = None
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
        Returns the current raw button state as a ``{hardware_name: is_down}``
        mapping.

        Called once per :meth:`poll` call.  Subclasses implement this using
        the appropriate hardware API (MouseWatcher for keyboard, direct device
        polling for gamepad / joystick).

        :return: Dict mapping each configured hardware name to its pressed
            state this frame.
        """
        raise NotImplementedError

    def read_axes(self, state: InputState) -> None:
        """
        Populates ``state.axes`` with dead-zoned axis values for this frame.

        Called at the end of :meth:`poll`.  Subclasses implement this using
        the appropriate hardware API.  Keyboard readers leave this as a no-op
        because virtual axes are synthesised by the input context layer.

        :param state: The :class:`InputState` being built; populate
            ``state.axes`` in place.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def collect_button_names(self, axis_names: frozenset[str]) -> frozenset[str]:
        """
        Scans all context bindings and returns the hardware names that are
        buttons (i.e. not continuous axes).

        Reads every binding value for the current input type across all
        contexts and excludes any name present in *axis_names*.

        :param axis_names: Frozenset of hardware names that represent
            continuous axes and must not be polled as buttons.
        :return: Frozenset of button hardware names from the configuration.
        """
        input_type = self.app.bindings["input_type"]
        names: set[str] = set()
        for ctx_data in self.app.bindings.get("contexts", {}).values():
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
        """
        Collects bound key names and register safety-net event callbacks.

        Calls :meth:`~InputReader.collect_button_names` with an empty axis
        set (keyboards have no analogue axes), then registers ``accept()``
        callbacks for every bound key so that short presses between polls are
        not missed.

        :param app: The Panda3D application instance.
        """
        super().__init__(app)
        self.button_names = self.collect_button_names(frozenset())
        self.registry = ButtonRegistry.ptr()

        for key in self.button_names:
            app.accept(key, lambda k=key: self.ev_pressed.add(k))
            app.accept(key + "-up", lambda k=key: self.ev_released.add(k))

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls every bound key via the MouseWatcher.

        :return: Dict mapping hardware name → ``True`` if the key is
            currently held down.
        """
        result: dict[str, bool] = {}
        for key in self.button_names:
            handle = self.registry.getButton(key)
            result[key] = self.app.mouseWatcherNode.isButtonDown(handle)
        return result

    def read_axes(self, state: InputState) -> None:
        """
        No-op — keyboards have no physical axes.

        Virtual axes (throttle, pitch, etc.) are synthesised from button
        states by the flight input context layer.

        :param state: Unused.
        """
        pass  # Keyboard has no physical axes; FlightInputContext synthesises them

    def clean(self) -> None:
        """
        Unregisters key event callbacks, then delegate to the base class.
        """
        for key in self.button_names:
            self.app.ignore(key)
            self.app.ignore(key + "-up")
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
        """
        Detects a connected gamepad and registers hot-plug and button events.

        If a gamepad is already connected it is attached immediately via
        :meth:`_connect`.  If none is found, an on-screen warning label is
        shown.  Hot-plug events are accepted so the reader adapts at runtime.

        Safety-net ``accept()`` callbacks are registered for every bound
        button, mapping Panda3D's ``"gamepad-lshoulder"`` event names to the
        ``"gamepad_lshoulder"`` hardware names used in the configuration.

        :param app: The Panda3D application instance.
        """
        super().__init__(app)
        self.button_names = self.collect_button_names(GAMEPAD_AXIS_NAMES)
        self.dead_zones = app.bindings.get("dead_zones", {})
        self.gamepad = None

        devices = app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self.connect(devices[0])
        else:
            self.lbl = OnscreenText(text="No gamepad found", fg=(1, 0, 0, 1), scale=0.2)

        app.accept("connect-device", self.connect)
        app.accept("disconnect-device", self.disconnect)

        # Safety-net events for named gamepad buttons
        # Hardware name "gamepad_lshoulder" → Panda3D event "gamepad-lshoulder"
        for hw in self.button_names:
            evt = "gamepad-" + hw[len("gamepad_") :]
            app.accept(evt, lambda n=hw: self.ev_pressed.add(n))
            app.accept(evt + "-up", lambda n=hw: self.ev_released.add(n))

    # ------------------------------------------------------------------

    def connect(self, device) -> None:
        """
        Attaches *device* if it is a gamepad and no gamepad is already active.

        :param device: The device that was just connected.
        """
        if device.device_class == InputDevice.DeviceClass.gamepad and not self.gamepad:
            print(f"Gamepad connected: {safe_device_name(device)}")
            self.gamepad = device
            self.app.attachInputDevice(device, prefix="gamepad")
            if hasattr(self, "_lbl"):
                self.lbl.hide()

    def disconnect(self, device) -> None:
        """
        Detaches *device* and fall back to another gamepad if one is available.

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
        elif hasattr(self, "_lbl"):
            self.lbl.show()

    # ------------------------------------------------------------------

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls the physical state of every bound gamepad button.

        Uses :data:`GAMEPAD_BUTTON_CODES` to map hardware names to Panda3D
        :class:`~panda3d.core.GamepadButton` handles, then reads the
        ``pressed`` flag directly from the device.

        :return: Dict mapping hardware name → ``True`` if the button is held.
        """
        if not self.gamepad:
            return {name: False for name in self.button_names}
        result: dict[str, bool] = {}
        for hw in self.button_names:
            code = GAMEPAD_BUTTON_CODES.get(hw)
            if code is not None:
                btn = self.gamepad.findButton(code)
                result[hw] = bool(btn.pressed) if btn else False
            else:
                result[hw] = False
        return result

    @staticmethod
    def dz(value: float, dead_zone: float) -> float:
        """
        Applies a symmetric dead zone to a raw axis value.

        Values within ±*dead_zone* of centre are zeroed; values outside are
        linearly rescaled so that the output starts at zero at the dead-zone
        boundary.

        :param value: Raw axis value in the range [-1, 1].
        :param dead_zone: Half-width of the dead-zone band.
        :return: Dead-zoned axis value.
        """
        if abs(value) < dead_zone:
            return 0.0
        return value - np.sign(value) * dead_zone

    def read_axes(self, state: InputState) -> None:
        """
        Reads and dead-zones all six gamepad axes into ``state.axes``.

        Left-stick X/Y axes are sign-inverted to match the flight control
        conventions used elsewhere in the game.

        :param state: The :class:`InputState` being built; ``state.axes`` is
            populated in place.
        """
        if not self.gamepad:
            return
        sdz = self.dead_zones.get("stick", DEFAULT_STICK_DEAD_ZONE)
        tdz = self.dead_zones.get("throttle", DEFAULT_THROTTLE_DEAD_ZONE)

        # Sign conventions match the original Gamepad.get_inputs() behaviour
        state.axes["right_trigger"] = self.dz(
            self.gamepad.findAxis(InputDevice.Axis.right_trigger).value, tdz
        )
        state.axes["left_trigger"] = self.dz(
            self.gamepad.findAxis(InputDevice.Axis.left_trigger).value, tdz
        )
        state.axes["left_x"] = self.dz(
            -self.gamepad.findAxis(InputDevice.Axis.left_x).value, sdz
        )
        state.axes["left_y"] = self.dz(
            -self.gamepad.findAxis(InputDevice.Axis.left_y).value, sdz
        )
        state.axes["right_x"] = self.dz(
            self.gamepad.findAxis(InputDevice.Axis.right_x).value, sdz
        )
        state.axes["right_y"] = self.dz(
            self.gamepad.findAxis(InputDevice.Axis.right_y).value, sdz
        )

    def clean(self) -> None:
        """
        Detaches the gamepad, destroys the warning label, unregisters all event
        callbacks, then delegates to the base class.
        """
        if self.gamepad:
            try:
                self.app.detachInputDevice(self.gamepad)
            except AssertionError:
                pass
            self.gamepad = None
        if hasattr(self, "_lbl"):
            self.lbl.destroy()
        for hw in self.button_names:
            evt = "gamepad-" + hw[len("gamepad_") :]
            self.app.ignore(evt)
            self.app.ignore(evt + "-up")
        self.app.ignore("connect-device")
        self.app.ignore("disconnect-device")
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
        """
        Detects a connected flight stick and register hot-plug events.

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
        else:
            self.lbl = OnscreenText(
                text="No joystick found", fg=(1, 0, 0, 1), scale=0.2
            )

        app.accept("connect-device", self.connect)
        app.accept("disconnect-device", self.disconnect)
        # No button events — polling-only for joystick buttons

    # ------------------------------------------------------------------

    def connect(self, device) -> None:
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
            if hasattr(self, "_lbl"):
                self.lbl.hide()

    def disconnect(self, device) -> None:
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
        elif hasattr(self, "_lbl"):
            self.lbl.show()

    # ------------------------------------------------------------------

    @staticmethod
    def button_index(hw_name: str) -> int | None:
        """
        Converts a ``"stick_button_N"`` name to a zero-based hardware index.

        Joystick buttons are addressed by index in the device's button array.
        The YAML convention uses 1-based names (``stick_button_1`` is index 0).

        :param hw_name: Hardware name such as ``"stick_button_3"``.
        :return: Zero-based button index, or ``None`` if the trailing suffix
            is not a digit string.
        """
        suffix = hw_name.rsplit("_", 1)[-1]
        return int(suffix) - 1 if suffix.isdigit() else None

    def read_all_buttons(self) -> dict[str, bool]:
        """
        Polls every bound flight-stick button by its zero-based hardware index.

        Returns all-false when no stick is connected or when a button index
        is out of range for the attached device.

        :return: Dict mapping hardware name → ``True`` if the button is held.
        """
        if not self.flightStick:
            return {name: False for name in self.button_names}
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

    @staticmethod
    def dz(value: float, dead_zone: float) -> float:
        """
        Applies a symmetric dead zone to a raw axis value.

        :param value: Raw axis value in the range [-1, 1].
        :param dead_zone: Half-width of the dead-zone band.
        :return: Dead-zoned axis value.
        """
        if abs(value) < dead_zone:
            return 0.0
        return value - np.sign(value) * dead_zone

    def read_axes(self, state: InputState) -> None:
        """
        Reads and dead-zone the four flight-stick axes into ``state.axes``.

        The throttle axis is inverted (``1 − raw``) so that pulling the lever
        towards the pilot increases the output value.

        :param state: The :class:`InputState` being built; ``state.axes`` is
            populated in place.
        """
        if not self.flightStick:
            return
        sdz = self.dead_zones.get("stick", DEFAULT_STICK_DEAD_ZONE)
        tdz = self.dead_zones.get("throttle", DEFAULT_THROTTLE_DEAD_ZONE)

        state.axes["throttle"] = self.dz(
            1 - self.flightStick.findAxis(InputDevice.Axis.throttle).value, tdz
        )
        state.axes["yaw"] = self.dz(
            self.flightStick.findAxis(InputDevice.Axis.yaw).value, sdz
        )
        state.axes["pitch"] = self.dz(
            self.flightStick.findAxis(InputDevice.Axis.pitch).value, sdz
        )
        state.axes["roll"] = self.dz(
            self.flightStick.findAxis(InputDevice.Axis.roll).value, sdz
        )

    def clean(self) -> None:
        """
        Detaches the flight stick, destroys the warning label, unregisters hot-plug
        events, then delegates to the base class.
        """
        if self.flightStick:
            self.app.detachInputDevice(self.flightStick)
            self.flightStick = None
        if hasattr(self, "_lbl"):
            self.lbl.destroy()
        self.app.ignore("connect-device")
        self.app.ignore("disconnect-device")
        super().clean()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def load_bindings() -> dict:
    """
    Reads and parses ``configuration/configuration.yaml``.

    :return: Parsed configuration dict.
    """
    filepath = CONFIGURATION_PATH / "configuration.yaml"
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


def reader_factory(app) -> InputReader:
    """
    Loads the configuration, stores it on ``app.bindings``, and instantiates the
    appropriate :class:`InputReader` subclass for the configured input type.

    Called at application startup and again when the user saves new settings
    so the reader reflects updated hardware names and dead zones without a
    restart.

    :param app: The Panda3D application instance.
    :return: A :class:`KeyboardReader`, :class:`GamepadReader`, or
        :class:`JoystickReader` ready to be polled each frame.
    :raises NotImplementedError: If ``input_type`` is not one of
        ``"keyboard"``, ``"gamepad"``, or ``"joystick"``.
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
