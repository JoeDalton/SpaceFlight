import numpy as np
import yaml
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d.core import ButtonThrower, InputDevice, InputDeviceNode

from space_flight import CONFIGURATION_PATH
from space_flight.utils import low_pass_filter_first_order

DEFAULT_STICK_DEAD_ZONE = 0.15
DEFAULT_THROTTLE_DEAD_ZONE = 0.04
THROTTLE_BOOST_VALUE = 2.0


def _patched_attachInputDevice(self, device, prefix=None, watch=False):
    """
    Some controllers have a name with characters that make the game crash
    on windows. This is fixed by replacing a Panda3d function

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


def safe_device_name(device):
    """
    Returns a printable name for a device, working around Panda3D's
    UTF-8 bug on windows machines.
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
        return f"Gamepad (VID_{device.vendor_id:04X}&PID_{device.product_id:04X})"
    except Exception:
        return "Gamepad (unknown)"


def input_system_factory(game, player):
    filepath = CONFIGURATION_PATH / "configuration.yaml"
    with open(filepath, "r") as f:
        game.bindings = yaml.safe_load(f)

    input_type = game.bindings["input_type"]
    if input_type == "joystick":
        return Joystick(game=game, player=player)
    elif input_type == "keyboard":
        return Keyboard(game=game, player=player)
    elif input_type == "gamepad":
        return Gamepad(game=game, player=player)
    else:
        raise NotImplementedError


class InputSystem:
    def __init__(self, game, player):
        self.game = game
        self.player = player
        self.view_offset = np.zeros(2)
        self.game.app.disableMouse()
        self.is_boost = False
        self.is_laser_fire = False
        # Game UI
        self.game.app.accept("escape", self.game.set_pause)
        self.lblWarning = OnscreenText(text="", fg=(1, 0, 0, 1), scale=0.25)

    def action(self, button):
        # Just show which button has been pressed.
        print("Pressed once %s" % button)

    def actionRepeat(self, button):
        # Just show which button has been pressed.
        print("Pressed continuously %s" % button)

    def actionUp(self, button):
        # Just show which button has been released.
        print("Released %s" % button)

    def view_up(self):
        self.view_offset[0] += 1

    def view_down(self):
        self.view_offset[0] -= 1

    def view_right(self):
        self.view_offset[1] -= 1

    def view_left(self):
        self.view_offset[1] += 1

    def activate_boost(self):
        self.is_boost = True

    def deactivate_boost(self):
        self.is_boost = False

    def activate_laser(self):
        self.is_laser_fire = True

    def deactivate_laser(self):
        self.is_laser_fire = False

    def smooth_button(
        self,
        value: float,  # current raw input: 1.0 if pressed, 0.0 if not
        previous: float,  # previous smoothed output
        rise_time: float = 1.0,  # seconds to reach ~63% when pressed
        fall_time: float = 0.5,  # seconds to decay when released
    ):
        """
        Returns a smoothed value in [0, 1] based on button presses.

        Snappy feel:
            rise_time=0.1
            fall_time=0.05

        Mid feel:
            rise_time=0.5
            fall_time=0.1

        Sluggish feel:
            rise_time=1.0
            fall_time=0.5
        """
        dt = self.game.game_time.get_time_step()
        return low_pass_filter_first_order(
            value=float(value),
            previous=float(previous),
            dt=dt,
            rise_time=rise_time,
            fall_time=fall_time,
        )


class Keyboard(InputSystem):
    def __init__(self, game, player):
        super().__init__(game=game, player=player)

        self.throttle = 0.0
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.yaw_rate_smoothed = 0.0
        self.pitch_rate_smoothed = 0.0
        self.roll_rate_smoothed = 0.0

        self.keys = {k: False for k in self.game.bindings["keyboard_bindings"].keys()}

        # Flight control events
        for k in self.keys:
            self.game.app.accept(
                self.game.bindings["keyboard_bindings"][k],
                self.keys.__setitem__,
                [k, True],
            )
            self.game.app.accept(
                self.game.bindings["keyboard_bindings"][k] + "-up",
                self.keys.__setitem__,
                [k, False],
            )
        self.game.app.accept(
            self.game.bindings["keyboard_bindings"]["boost"],
            self.activate_boost,
        )
        self.game.app.accept(
            self.game.bindings["keyboard_bindings"]["boost"] + "-up",
            self.deactivate_boost,
        )

    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, roll, pitch, yaw
        """
        # Get inputs from key strokes
        self.throttle += 0.005 * (self.keys["throttle_up"] - self.keys["throttle_down"])
        self.yaw_rate = self.keys["yaw_left"] - self.keys["yaw_right"]
        self.pitch_rate = self.keys["pitch_up"] - self.keys["pitch_down"]
        self.roll_rate = self.keys["roll_right"] - self.keys["roll_left"]

        # Low pass filter for axes
        self.yaw_rate_smoothed = self.smooth_button(
            value=self.yaw_rate, previous=self.yaw_rate_smoothed
        )
        self.pitch_rate_smoothed = self.smooth_button(
            value=self.pitch_rate, previous=self.pitch_rate_smoothed
        )
        self.roll_rate_smoothed = self.smooth_button(
            value=self.roll_rate, previous=self.roll_rate_smoothed
        )

        # Bound results
        self.throttle = max(min(self.throttle, 1.0), 0.0)
        self.yaw_rate_smoothed = max(min(self.yaw_rate_smoothed, 1.0), -1.0)
        self.pitch_rate_smoothed = max(min(self.pitch_rate_smoothed, 1.0), -1.0)
        self.roll_rate_smoothed = max(min(self.roll_rate_smoothed, 1.0), -1.0)

        # Fire weapons
        if self.keys["fire_primary"]:
            self.player.ship.laser_cannon.fire()

        # Boost usage
        if self.is_boost:
            throttle = THROTTLE_BOOST_VALUE
        else:
            throttle = self.throttle
        return (
            throttle,
            self.yaw_rate_smoothed,
            self.pitch_rate_smoothed,
            self.roll_rate_smoothed,
        )

    def clean(self):
        self.game = None


class Joystick(InputSystem):
    # TODO add a joystick center and deadzone calibration utility
    def __init__(self, game, player):
        super().__init__(game=game, player=player)

        self.lblWarning["text"] = "No devices found"

        self.lblAction = OnscreenText(text="Action", fg=(1, 1, 1, 1), scale=0.15)
        self.lblAction.hide()

        # Is there a joystick connected?
        self.flightStick = None
        devices = self.game.app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])

        # Keep track of previous button states
        self.previous_button_states = [False] * len(self.flightStick.buttons)
        # Polling task to create events for unnamed buttons
        self.game.app.taskMgr.add(self.poll_buttons_task, "PollButtonsTask")

        # Accept device dis-/connection events
        self.game.app.accept("connect-device", self.connect)
        self.game.app.accept("disconnect-device", self.disconnect)

        self.game.app.accept("stick-start", self.game.set_pause)

        # Accept trigger event to fire lasers
        self.game.app.accept("stick-button1", self.player.ship.laser_cannon.fire)
        self.game.app.accept("stick-button1-repeat", self.player.ship.laser_cannon.fire)

        # Accept button events on the thumb hat
        # to change head orientation
        self.game.app.accept("stick-button19", self.view_down)
        self.game.app.accept("stick-button18", self.view_up)
        self.game.app.accept("stick-button17", self.view_right)
        self.game.app.accept("stick-button16", self.view_left)
        self.game.app.accept("stick-button19-repeat", self.view_down)
        self.game.app.accept("stick-button18-repeat", self.view_up)
        self.game.app.accept("stick-button17-repeat", self.view_right)
        self.game.app.accept("stick-button16-repeat", self.view_left)

        # Accept boost toggle
        self.game.app.accept("stick-button8", self.activate_boost)
        self.game.app.accept("stick-button8-up", self.deactivate_boost)

        # Register joystick dead zone
        self.stick_dead_zone = self.game.bindings.get(
            "stick_dead_zone", DEFAULT_STICK_DEAD_ZONE
        )
        self.throttle_dead_zone = self.game.bindings.get(
            "throttle_dead_zone", DEFAULT_THROTTLE_DEAD_ZONE
        )

    def connect(self, device):
        """Event handler that is called when a device is discovered."""

        # We're only interested if this is a flight stick and we don't have a
        # flight stick yet.
        if (
            device.device_class == InputDevice.DeviceClass.flight_stick
            and not self.flightStick
        ):
            print("Found %s" % (device))
            self.flightStick = device

            # Enable this device to ShowBase so that we can receive events.
            # We set up the events with a prefix of "stick-".
            self.game.app.attachInputDevice(device, prefix="stick")

            # Hide the warning that we have no devices.
            self.lblWarning.hide()

    def disconnect(self, device):
        """Event handler that is called when a device is removed."""

        if self.flightStick != device:
            # We don't care since it's not our gamepad.
            return

        # Tell ShowBase that the device is no longer needed.
        print("Disconnected %s" % (device))
        self.game.app.detachInputDevice(device)
        self.flightStick = None

        # Do we have any other gamepads?  Attach the first other gamepad.
        devices = self.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])
        else:
            # No devices.  Show the warning.
            self.lblWarning.show()

    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, yaw_rate, pitch_rate, roll_rate
        """

        if not self.flightStick:
            return 0.0, 0.0, 0.0, 0.0

        if self.is_boost:
            throttle = THROTTLE_BOOST_VALUE
        else:
            throttle = 1 - self.flightStick.findAxis(InputDevice.Axis.throttle).value
            if abs(throttle) < self.throttle_dead_zone:
                throttle = 0

        yaw_rate = self.flightStick.findAxis(InputDevice.Axis.yaw).value
        if abs(yaw_rate) < self.stick_dead_zone:
            yaw_rate = 0
        else:
            yaw_rate = yaw_rate - np.sign(yaw_rate) * self.stick_dead_zone

        pitch_rate = self.flightStick.findAxis(InputDevice.Axis.pitch).value
        if abs(pitch_rate) < self.stick_dead_zone:
            pitch_rate = 0
        else:
            pitch_rate = pitch_rate - np.sign(pitch_rate) * self.stick_dead_zone

        roll_rate = self.flightStick.findAxis(InputDevice.Axis.roll).value
        if abs(roll_rate) < self.stick_dead_zone:
            roll_rate = 0
        else:
            roll_rate = roll_rate - np.sign(roll_rate) * self.stick_dead_zone

        return throttle, yaw_rate, pitch_rate, roll_rate

    def poll_buttons_task(self, task):
        if not self.flightStick:
            return task.cont

        for i, button in enumerate(self.flightStick.buttons):
            is_pressed = button.pressed
            was_pressed = self.previous_button_states[i]

            if is_pressed and not was_pressed:
                self.game.app.messenger.send(f"stick-button{i+1}")
            elif not is_pressed and was_pressed:
                self.game.app.messenger.send(f"stick-button{i+1}-up")
            elif is_pressed and was_pressed:
                self.game.app.messenger.send(f"stick-button{i+1}-repeat")

            self.previous_button_states[i] = is_pressed

        return task.cont

    def clean(self):
        self.game.app.detachInputDevice(self.flightStick)
        self.game.app.ignore("escape")
        self.flightStick = None
        self.game = None


class Gamepad(InputSystem):
    # TODO add a gamepad center and deadzone calibration utility
    def __init__(self, game, player):
        super().__init__(game=game, player=player)

        self.lblWarning["text"] = "Node devices found"

        self.lblAction = OnscreenText(text="Action", fg=(1, 1, 1, 1), scale=0.15)
        self.lblAction.hide()

        # Is there a gamepad connected?
        self.gamepad = None
        devices = self.game.app.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self.connect(devices[0])

        # Accept device dis-/connection events
        self.game.app.accept("connect-device", self.connect)
        self.game.app.accept("disconnect-device", self.disconnect)

        self.game.app.accept("gamepad-start", self.game.set_pause)
        self.game.app.accept("gamepad-back", self.game.set_pause)

        # Accept trigger event to fire lasers
        self.game.app.accept("gamepad-lshoulder", self.activate_laser)
        self.game.app.accept("gamepad-lshoulder-up", self.deactivate_laser)

        # Accept boost toggle
        self.game.app.accept("gamepad-rshoulder", self.activate_boost)
        self.game.app.accept("gamepad-rshoulder-up", self.deactivate_boost)

        # Register gamepad dead zone
        self.stick_dead_zone = self.game.bindings.get(
            "stick_dead_zone", DEFAULT_STICK_DEAD_ZONE
        )
        self.throttle_dead_zone = self.game.bindings.get(
            "throttle_dead_zone", DEFAULT_THROTTLE_DEAD_ZONE
        )

    def connect(self, device):
        """Event handler that is called when a device is discovered."""

        # We're only interested if this is a flight stick and we don't have a
        # flight stick yet.
        if device.device_class == InputDevice.DeviceClass.gamepad and not self.gamepad:
            print("Found %s" % safe_device_name(device))
            self.gamepad = device

            # Enable this device to ShowBase so that we can receive events.
            # We set up the events with a prefix of "gamepad-".
            self.game.app.attachInputDevice(device, prefix="gamepad")

            # Hide the warning that we have no devices.
            self.lblWarning.hide()

    def disconnect(self, device):
        """Event handler that is called when a device is removed."""

        if self.gamepad != device:
            # We don't care since it's not our gamepad.
            return

        # Tell ShowBase that the device is no longer needed.
        print("Disconnected %s" % safe_device_name(device))
        self.game.app.detachInputDevice(device)
        self.gamepad = None

        # Do we have any other gamepads?  Attach the first other gamepad.
        devices = self.devices.getDevices(InputDevice.DeviceClass.gamepad)
        if devices:
            self.connect(devices[0])
        else:
            # No devices.  Show the warning.
            self.lblWarning.show()

    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, yaw_rate, pitch_rate, roll_rate
        """

        if not self.gamepad:
            return 0.0, 0.0, 0.0, 0.0

        if self.is_laser_fire:
            self.player.ship.laser_cannon.fire()

        if self.is_boost:
            throttle = THROTTLE_BOOST_VALUE
        else:
            throttle = self.gamepad.findAxis(InputDevice.Axis.right_trigger).value
            if abs(throttle) < self.throttle_dead_zone:
                throttle = 0

        yaw_rate = -self.gamepad.findAxis(InputDevice.Axis.left_x).value
        if abs(yaw_rate) < self.stick_dead_zone:
            yaw_rate = 0
        else:
            yaw_rate = yaw_rate - np.sign(yaw_rate) * self.stick_dead_zone

        pitch_rate = -self.gamepad.findAxis(InputDevice.Axis.left_y).value
        if abs(pitch_rate) < self.stick_dead_zone:
            pitch_rate = 0
        else:
            pitch_rate = pitch_rate - np.sign(pitch_rate) * self.stick_dead_zone

        roll_rate = self.gamepad.findAxis(InputDevice.Axis.right_x).value
        if abs(roll_rate) < self.stick_dead_zone:
            roll_rate = 0
        else:
            roll_rate = roll_rate - np.sign(roll_rate) * self.stick_dead_zone

        return throttle, yaw_rate, pitch_rate, roll_rate

    def clean(self):
        try:
            self.game.app.detachInputDevice(self.gamepad)
        except AssertionError:
            pass
        self.lblWarning.destroy()
        self.game.app.ignore("escape")
        self.gamepad = None
        self.game = None
