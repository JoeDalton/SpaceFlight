from typing import Callable

import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight.ship import Ship
from space_flight.ui.input_system import input_system_factory
from space_flight.ui.rear_view_mirror import RearViewMirror

CAMERA_ANGLE_INCREMENT = 2.0


class Player:
    def __init__(
        self,
        app: ShowBase,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
    ):
        self.app = app
        self.name = "player"
        self.tasks = []
        self.ship = Ship(
            app=self.app,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=True,
        )
        self.input_system = input_system_factory(app=self.app, player=self)
        self.rear_view_mirror = RearViewMirror(app=self.app, player_node=self.ship.node)

        # Anchor camera to player ship node
        self.app.camera.reparentTo(self.ship.node)

        # Initialize targetting list
        self.available_targets = [{None: ""}]

        # Initialize movement task
        self.initialize_move()

    def initialize_move(self):
        """
        Initializes the player move task. Must be done after the
        integrator task init
        """
        self.app.taskMgr.add(self.move_player_task, "move_player_task")

    def move_player_task(self, task):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        throttle, yaw_rate, pitch_rate, roll_rate = self.input_system.get_inputs()
        self.ship.move_ship(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

        # Update camera angle relative to node
        self.app.camera.setP(self.input_system.view_offset[0] * CAMERA_ANGLE_INCREMENT)
        self.app.camera.setH(self.input_system.view_offset[1] * CAMERA_ANGLE_INCREMENT)

        return task.cont

    def add_task(self, method: Callable, task_name: str):
        """
        Add a task linked to this object

        :param method: the method to be called by the task
        :param task_name: The name of the task
        """
        self.tasks.append(self.app.taskMgr.add(method, task_name))

    def add_target(self, target, name: str):
        self.available_targets.append({target: name})

    def remove_target(self, target_to_remove):
        for target_idx in range(len(self.available_targets)):
            target_dict = self.available_targets[target_idx]
            target, _ = list(target_dict.items())[0]
            if target == target_to_remove:
                idx_to_remove = target_idx
                break
        self.available_targets.pop(idx_to_remove)
