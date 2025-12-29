import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from panda3d.core import InputDevice
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBaseGlobal import globalClock

from utils import low_pass_filter_first_order

STICK_DEAD_ZONE = 0.15
THROTTLE_DEAD_ZONE = 0.04

class InputSystem:
    def __init__(self, app: ShowBase, player):
        self.app = app
        self.player = player
        self.view_offset = np.zeros(2)
        self.app.disableMouse()

    def action(self, button):
        # Just show which button has been pressed.
        self.lblAction.text = "Pressed once %s" % button
        self.lblAction.show()
        
    def actionRepeat(self, button):
        # Just show which button has been pressed.
        self.lblAction.text = "Pressed continuously %s" % button
        self.lblAction.show()

    def actionUp(self):
        # Hide the label showing which button is pressed.
        self.lblAction.hide()

    def view_up(self):
        self.view_offset[0] += 1

    def view_down(self):
        self.view_offset[0] -= 1

    def view_right(self):
        self.view_offset[1] -= 1

    def view_left(self):
        self.view_offset[1] += 1

    @staticmethod
    def smooth_button(
        value: float,           # current raw input: 1.0 if pressed, 0.0 if not
        previous: float,        # previous smoothed output
        rise_time: float=0.5,   # seconds to reach ~63% when pressed
        fall_time:float=0.1,   # seconds to decay when released
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
            fall_time=0.2
        """
        dt = globalClock.getDt()
        return low_pass_filter_first_order(value=value, previous=previous, dt=dt, rise_time=rise_time, fall_time=fall_time)


class Keyboard(InputSystem):
    def __init__(self, app: ShowBase, player):
        super().__init__(app=app, player=player)

        # Accept trigger event to fire lasers
        self.app.accept("space", self.player.ship.laser_cannon.fire)
        self.app.accept("space-repeat", self.player.ship.laser_cannon.fire)

        self.throttle = 0.0
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.yaw_rate_smoothed = 0.0
        self.pitch_rate_smoothed = 0.0
        self.roll_rate_smoothed = 0.0

        self.app.accept("z", self.count_pitch_down, [0.05])
        self.app.accept("s", self.count_pitch_up, [0.05])
        self.app.accept("e", self.count_yaw_down, [0.05])
        self.app.accept("a", self.count_yaw_up, [0.05])
        self.app.accept("q", self.count_roll_down, [0.05])
        self.app.accept("d", self.count_roll_up, [0.05])
        self.app.accept("arrow_down", self.count_throttle_down)
        self.app.accept("arrow_up", self.count_throttle_up)

        self.app.accept("z-repeat", self.count_pitch_down, [0.3])
        self.app.accept("s-repeat", self.count_pitch_up, [0.3])
        self.app.accept("e-repeat", self.count_yaw_down, [0.3])
        self.app.accept("a-repeat", self.count_yaw_up, [0.3])
        self.app.accept("q-repeat", self.count_roll_down, [0.3])
        self.app.accept("d-repeat", self.count_roll_up, [0.3])
        self.app.accept("arrow_down-repeat", self.count_throttle_down)
        self.app.accept("arrow_up-repeat", self.count_throttle_up)

    def count_pitch_down(self, value: float):
        self.pitch_rate -= value
    def count_pitch_up(self, value: float):
        self.pitch_rate += value
    def count_yaw_down(self, value: float):
        self.yaw_rate -= value
    def count_yaw_up(self, value: float):
        self.yaw_rate += value
    def count_roll_down(self, value: float):
        self.roll_rate -= value
    def count_roll_up(self, value: float):
        self.roll_rate += value
    def count_throttle_down(self):
        self.throttle -= 0.1
    def count_throttle_up(self):
        self.throttle += 0.1


    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, roll, pitch, yaw
        """
        dt = globalClock.getDt()
        # Get average command of yaw pitch roll since last frame
        self.yaw_rate /= dt
        self.pitch_rate /= dt
        self.roll_rate /= dt
        
        # Low pass filter for axes
        self.yaw_rate_smoothed = InputSystem.smooth_button(value = self.yaw_rate, previous=self.yaw_rate_smoothed)
        self.pitch_rate_smoothed = InputSystem.smooth_button(value = self.pitch_rate, previous=self.pitch_rate_smoothed)
        self.roll_rate_smoothed = InputSystem.smooth_button(value = self.roll_rate, previous=self.roll_rate_smoothed)

        # Bound results
        self.throttle = max(min(self.throttle, 1.0), 0.0)
        self.yaw_rate_smoothed = max(min(self.yaw_rate_smoothed, 1.0), -1.0)
        self.pitch_rate_smoothed = max(min(self.pitch_rate_smoothed, 1.0), -1.0)
        self.roll_rate_smoothed = max(min(self.roll_rate_smoothed, 1.0), -1.0)
        
        # Reset commands
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        return self.throttle, self.yaw_rate_smoothed, self.pitch_rate_smoothed, self.roll_rate_smoothed

class Joystick(InputSystem):
    def __init__(self, app: ShowBase, player):
        super().__init__(app=app, player=player)

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

        # Accept trigger event to fire lasers
        self.app.accept("stick-button1", self.player.ship.laser_cannon.fire)
        self.app.accept("stick-button1-repeat", self.player.ship.laser_cannon.fire)

        # Accept button events on the thumb hat
        # to change head orientation
        self.app.accept("stick-button19", self.view_down)
        self.app.accept("stick-button18", self.view_up)
        self.app.accept("stick-button17", self.view_right)
        self.app.accept("stick-button16", self.view_left)
        self.app.accept("stick-button19-repeat", self.view_down)
        self.app.accept("stick-button18-repeat", self.view_up)
        self.app.accept("stick-button17-repeat", self.view_right)
        self.app.accept("stick-button16-repeat", self.view_left)

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



    def get_inputs(self):
        """
        Reads the flightstick's axes values to inform the player object

        returns throttle, yaw_rate, pitch_rate, roll_rate
        """
        
        if not self.flightStick:
            return 0.0, 0.0, 0.0, 0.0
        
        throttle = 1 - self.flightStick.findAxis(InputDevice.Axis.throttle).value
        if abs(throttle) < THROTTLE_DEAD_ZONE:
            throttle = 0

        yaw_rate = self.flightStick.findAxis(InputDevice.Axis.yaw).value
        if abs(yaw_rate) < STICK_DEAD_ZONE:
            yaw_rate = 0
        else:
            yaw_rate = yaw_rate - np.sign(yaw_rate) * STICK_DEAD_ZONE

        pitch_rate = self.flightStick.findAxis(InputDevice.Axis.pitch).value
        if abs(pitch_rate) < STICK_DEAD_ZONE:
            pitch_rate= 0
        else:
            pitch_rate = pitch_rate - np.sign(pitch_rate) * STICK_DEAD_ZONE

        roll_rate = self.flightStick.findAxis(InputDevice.Axis.roll).value
        if abs(roll_rate) < STICK_DEAD_ZONE:
            roll_rate = 0
        else:
            roll_rate = roll_rate - np.sign(roll_rate) * STICK_DEAD_ZONE

        return throttle, yaw_rate, pitch_rate, roll_rate

    def poll_buttons_task(self, task):
        if not self.flightStick:
            return task.cont

        for i, button in enumerate(self.flightStick.buttons):
            is_pressed = button.pressed
            was_pressed = self.previous_button_states[i]

            if is_pressed and not was_pressed:
                self.app.messenger.send(f"stick-button{i+1}")
            elif not is_pressed and was_pressed:
                self.app.messenger.send(f"stick-button{i+1}-up")
            elif is_pressed and was_pressed:
                self.app.messenger.send(f"stick-button{i+1}-repeat")

            self.previous_button_states[i] = is_pressed

        return task.cont
    