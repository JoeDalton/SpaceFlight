import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Quat, NodePath

from ship import Ship
from ship_model import ShipModel
from input_system import input_system_factory
from rear_view_mirror import RearViewMirror

CAMERA_ANGLE_INCREMENT = 2.0

class Player:

    def __init__(
            self,
            app: ShowBase,
            ship_name: str, 
            ini_position: np.ndarray = np.zeros(3),
            ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ):
        self.app = app

        self.ship = Ship(app=self.app, ship_name=ship_name, ini_position=ini_position, ini_orientation=ini_orientation)
        self.model = ShipModel(app=self.app, ship_name=ship_name, is_cockpit=True)
        self.input_system = input_system_factory(app=self.app, player=self)
        self.rear_view_mirror = RearViewMirror(app=self.app, player_node=self.ship.node)

        # Anchor elements to self.ship.node
        self.model.anchor_model(self.ship.node)
        self.app.camera.reparentTo(self.ship.node)

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
        throttle, yaw_rate, pitch_rate, roll_rate = self.input_system.get_inputs()
        self.ship.move_ship(throttle=throttle, yaw_rate=yaw_rate, pitch_rate=pitch_rate, roll_rate=roll_rate)

        # Update camera angle relative to node
        self.app.camera.setP(self.input_system.view_offset[0] * CAMERA_ANGLE_INCREMENT)
        self.app.camera.setH(self.input_system.view_offset[1] * CAMERA_ANGLE_INCREMENT)

        return task.cont
