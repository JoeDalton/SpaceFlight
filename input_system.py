import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from panda3d.core import InputDevice
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import Quat

STICK_DEAD_ZONE = 0.02
THROTTLE_DEAD_ZONE = 0.02

class Joystick:
    def __init__(self, app: ShowBase):
        self.app = app

        self.lblWarning = OnscreenText(
            text = "No devices found",
            fg=(1,0,0,1),
            scale = .25)

        self.lblAction = OnscreenText(
            text = "Action",
            fg=(1,1,1,1),
            scale = .15)
        self.lblAction.hide()

        # Is there a joystick connected?
        self.flightStick = None
        devices = self.app.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])

        # Accept device dis-/connection events
        self.app.accept("connect-device", self.connect)
        self.app.accept("disconnect-device", self.disconnect)

        self.app.accept("escape", exit)
        self.app.accept("flight_stick0-start", exit)

        # Accept button events of the first connected flight stick
        self.app.accept("flight_stick0-trigger", self.action, extraArgs=["Trigger"])
        self.app.accept("flight_stick0-trigger-up", self.actionUp)

        self.app.disableMouse()

    def connect(self, device):
        """Event handler that is called when a device is discovered."""

        # We're only interested if this is a flight stick and we don't have a
        # flight stick yet.
        if device.device_class == InputDevice.DeviceClass.flight_stick and not self.flightStick:
            print("Found %s" % (device))
            self.flightStick = device

            # Enable this device to ShowBase so that we can receive events.
            # We set up the events with a prefix of "flight_stick0-".
            self.app.attachInputDevice(device, prefix="flight_stick0")

            # Hide the warning that we have no devices.
            self.lblWarning.hide()

    def disconnect(self, device):
        """Event handler that is called when a device is removed."""

        if self.flightStick != device:
            # We don't care since it's not our gamepad.
            return

        # Tell ShowBase that the device is no longer needed.
        print("Disconnected %s" % (device))
        self.app.detachInputDevice(device)
        self.flightStick = None

        # Do we have any other gamepads?  Attach the first other gamepad.
        devices = self.devices.getDevices(InputDevice.DeviceClass.flight_stick)
        if devices:
            self.connect(devices[0])
        else:
            # No devices.  Show the warning.
            self.lblWarning.show()

    def action(self, button):
        # Just show which button has been pressed.
        self.lblAction.text = "Pressed %s" % button
        self.lblAction.show()

    def actionUp(self):
        # Hide the label showing which button is pressed.
        self.lblAction.hide()

    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, roll, pitch, yaw
        """
        
        if not self.flightStick:
            return 0.0, 0.0, 0.0, 0.0
        
        throttle = 1 - self.flightStick.findAxis(InputDevice.Axis.throttle).value
        if abs(throttle) < THROTTLE_DEAD_ZONE:
            throttle = 0

        yaw = self.flightStick.findAxis(InputDevice.Axis.yaw).value
        if abs(yaw) < STICK_DEAD_ZONE:
            yaw = 0

        pitch = self.flightStick.findAxis(InputDevice.Axis.pitch).value
        if abs(pitch) < STICK_DEAD_ZONE:
            pitch= 0

        roll = self.flightStick.findAxis(InputDevice.Axis.roll).value
        if abs(roll) < STICK_DEAD_ZONE:
            roll = 0

        return throttle, roll, pitch, yaw
