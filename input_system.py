import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from panda3d.core import InputDevice
from direct.gui.OnscreenText import OnscreenText

STICK_DEAD_ZONE = 0.08
THROTTLE_DEAD_ZONE = 0.04

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

        # Keep track of previous button states
        self.previous_button_states = [False] * len(self.flightStick.buttons)
        # Polling task to create events for unnamed buttons
        self.app.taskMgr.add(self.poll_buttons_task, "PollButtonsTask")

        # Accept device dis-/connection events
        self.app.accept("connect-device", self.connect)
        self.app.accept("disconnect-device", self.disconnect)

        self.app.accept("escape", exit)
        self.app.accept("stick-start", exit)

        # Accept button events of the first connected flight stick
        self.app.accept("stick-trigger", self.action, extraArgs=["Trigger"])
        self.app.accept("stick-trigger-up", self.actionUp)

        # Accept button events on the thumb hat
        # to change head orientation 
        self.view_offset = np.zeros(2)
        self.app.accept("stick-button18", self.view_up)
        self.app.accept("stick-button17", self.view_down)
        self.app.accept("stick-button16", self.view_right)
        self.app.accept("stick-button15", self.view_left)

        self.app.disableMouse()

    def connect(self, device):
        """Event handler that is called when a device is discovered."""

        # We're only interested if this is a flight stick and we don't have a
        # flight stick yet.
        if device.device_class == InputDevice.DeviceClass.flight_stick and not self.flightStick:
            print("Found %s" % (device))
            self.flightStick = device

            # Enable this device to ShowBase so that we can receive events.
            # We set up the events with a prefix of "stick-".
            self.app.attachInputDevice(device, prefix="stick")

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

    def view_up(self):
        self.view_offset[0] +=1

    def view_down(self):
        self.view_offset[0] -=1

    def view_right(self):
        self.view_offset[1] -=1

    def view_left(self):
        self.view_offset[1] +=1

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

        return throttle, yaw, pitch, roll

    def poll_buttons_task(self, task):
        if not self.flightStick:
            return task.cont

        for i, button in enumerate(self.flightStick.buttons):
            is_pressed = button.pressed
            was_pressed = self.previous_button_states[i]

            if is_pressed and not was_pressed:
                self.app.messenger.send(f"stick-button{i}")
            elif not is_pressed and was_pressed:
                self.app.messenger.send(f"stick-button{i}-up")

            self.previous_button_states[i] = is_pressed

        return task.cont