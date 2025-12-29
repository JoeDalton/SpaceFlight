import numpy as np
import quaternion
from typing import List

from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock

from ship import Ship
from ship_model import ShipModel
from ai import AutoPilot

WAYPOINT_MEETING_TOLERANCE = 10

class Bot:

    def __init__(
            self,
            app: ShowBase,
            ship_name: str, 
            ini_position: np.ndarray = np.zeros(3),
            ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ):
        self.app = app

        self.ship = Ship(app=self.app, ship_name=ship_name, ini_position=ini_position, ini_orientation=ini_orientation)
        self.model = ShipModel(app=self.app, ship_name=ship_name, is_cockpit=False)
        self.autopilot = AutoPilot(ship = self.ship)

        # Anchor elements to self.ship.node
        self.model.anchor_model(self.ship.node)

    def initialize_move(self):
        """
        Initializes the player move task. Must be done after the
        integrator task init
        """
        self.app.taskMgr.add(self.move_bot_task, f"move_bot_task")

    def move_bot_task(self, task):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        target_direction, reference_distance_m = self.get_direction()
        throttle, yaw_rate, pitch_rate, roll_rate = self.autopilot.pilot(target_direction=target_direction, reference_distance_m=reference_distance_m)
        self.ship.move_ship(throttle=throttle, yaw_rate=yaw_rate, pitch_rate=pitch_rate, roll_rate=roll_rate)

        return task.cont
        
    def initialize_waypoints(self, waypoints: List[np.ndarray]):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: _description_
        """
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.distance_to_waypoint = 0.0


    def set_mode(self, mode:str):
        """
        Sets the bot mode
        """
        if mode in ["idle", "demo", "loop", "waypoints"]:
            self.mode = mode
        else:
            raise NotImplementedError(f"Bot mode {mode}")
        

    def get_direction(self):
        """
        Gives the direction vector to aim for

        TODO: nice logics (boids, loop, etc.)
        """
        if self.mode == "idle":
            return self.get_direction_idle()
        elif self.mode == "demo":
            return self.get_direction_demo()
        elif self.mode == "loop":
            return self.get_direction_loop()
        elif self.mode == "waypoints":
            return self.get_direction_waypoints()
        

    def get_direction_idle(self) -> np.ndarray:
        """
        Gives the direction vector to aim for
        The bot does nothing
        """
        return np.zeros(3), 0.0

    def get_direction_demo(self) -> np.ndarray:
        """
        Gives the direction vector to aim for
        The bot moves a bit around itself
        """
        if globalClock.getFrameTime() < 5.0:
            return np.array([0.0, 1.0, 0.0]), 0.0
        #elif globalClock.getFrameTime() < 15.0:
        #    return np.array([0.0, 0.0, 1.0])
        else:
            return np.array([1.0, 0.0, 0.0]), 0.0
        
    def get_direction_loop(self) -> np.ndarray:
        """
        _summary_

        :return: _description_
        """
        # If last waypoint has been met, return to the first one
        if self.next_waypoint_idx == len(self.waypoints):
            self.next_waypoint_idx = 0
        return self.get_direction_waypoints()

    def get_direction_waypoints(self) -> np.ndarray:
        """
        _summary_

        :return: _description_
        """
        # If last waypoint has been met, revert to idle state
        if self.next_waypoint_idx == len(self.waypoints):
            self.set_mode("idle")
            return self.get_direction()

        waypoint = self.waypoints[self.next_waypoint_idx]
        waypoint_direction = waypoint - self.ship.state[:3]
        self.distance_to_waypoint = np.linalg.norm(waypoint_direction)
        if self.distance_to_waypoint < WAYPOINT_MEETING_TOLERANCE:
            # Check if waypoint has been met. If yes, 
            # do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            direction = np.zeros(3)
        else:
            # Go to waypoint
            direction = waypoint_direction / self.distance_to_waypoint

        return direction, self.distance_to_waypoint