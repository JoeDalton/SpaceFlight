import logging
from typing import List

import numpy as np
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock

from space_flight import DEBUG_DELETION
from space_flight.ai import AutoPilot
from space_flight.destructibles import Destructible
from space_flight.ship import Ship
from space_flight.trihedron import Trihedron

LOGGER = logging.getLogger()
WAYPOINT_MEETING_TOLERANCE = 10


class Bot(Destructible):
    def __init__(
        self,
        app: ShowBase,
        name: str,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
    ):
        super().__init__(app=app)
        self.name = name
        self.ship = Ship(
            app=self.app,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=False,
        )
        self.set_mode("idle")
        self.autopilot = AutoPilot(ship=self.ship)
        self.app.player.add_target(target=self.ship, name=self.name)

        self.initialize_move()

    def initialize_move(self):
        """
        Initializes the player move task. Must be done after the
        integrator task init
        """
        self.add_task(method=self.move_bot_task, task_name="move_bot_task")

    def move_bot_task(self, task):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        target_direction, reference_distance_m = self.get_direction()
        throttle, yaw_rate, pitch_rate, roll_rate = self.autopilot.pilot(
            target_direction=target_direction, reference_distance_m=reference_distance_m
        )
        self.ship.move_ship(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

        return task.cont

    def initialize_waypoints(self, waypoints: List[np.ndarray]):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: _description_
        """
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.distance_to_waypoint = 0.0

    def set_mode(self, mode: str, mode_dict: dict = {}):
        """
        Sets the bot mode
        """
        # Set mode
        if mode in ["idle", "demo", "loop", "waypoints"]:
            self.mode = mode
        else:
            raise NotImplementedError(f"Bot mode {mode}")
        # Set mode parameters
        if mode in ["loop", "waypoints"]:
            self.initialize_waypoints(waypoints=mode_dict["waypoints"])

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
        # elif globalClock.getFrameTime() < 15.0:
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

    def get_health(self) -> float:
        """
        Find the health of the bot

        :return: The health of the bot
        """
        return self.ship.health

    def clean(self):
        """
        Remove every child
        """
        self.app.player.remove_target(target_to_remove=self.ship)
        self.autopilot.clean()
        self.autopilot = None
        self.ship.clean()
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaned bot {self.name}")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Deleted bot {self.name}")


def spawn_bot(
    app: ShowBase,
    name: str,
    ship_type: str,
    ini_position: np.ndarray = np.zeros(3),
    ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
    has_debug_trihedron: bool = False,
    mode: str = "idle",
    mode_dict: dict = {},
) -> Bot:
    bot = Bot(
        app=app,
        name=name,
        ship_type=ship_type,
        ini_position=ini_position,
        ini_orientation=ini_orientation,
    )
    bot.set_mode(mode, mode_dict=mode_dict)
    if has_debug_trihedron:
        Trihedron(app=app, parent=bot.ship.node, scale=1)

    # DEBUG
    bot.ship.health = 1.1
    bot.ship.shield = 0.0
    bot.ship.shield_regen_rate = 0.0
    return bot
