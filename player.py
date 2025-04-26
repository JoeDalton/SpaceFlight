import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Quat

from ship import SimpleShipPhysics
from cockpit_view import CockpitView
from input_system import Joystick


class Player:

    def __init__(self, app: ShowBase, ship_name: str):
        self.app = app
        self.ship = SimpleShipPhysics(app=self.app, ship_name=ship_name)
        self.model = CockpitView(app=self.app, ship_name=ship_name)
        self.input_system = Joystick(self.app)

    def initialize_move(self):
        """
        Initializes the player move task. Must be done after the
        integrator task init
        """
        self.app.taskMgr.add(self.move_player_task, f"move_player_task")

    def move_player_task(self, task):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        throttle, yaw, pitch, roll = self.input_system.get_inputs()
        self.ship.set_inputs(throttle=throttle, yaw=yaw, pitch=pitch, roll=roll)
        self.ship.move_ship()

        ship_pos = self.ship.state[0:3]
        ship_quat = self.ship.state[3:7]

        self.app.camera.setPos(*ship_pos)
        self.app.camera.setQuat(Quat(*ship_quat))
        self.app.skybox.skybox.setPos(*ship_pos)

        return task.cont
