import numpy as np
import quaternion
import yaml

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Quat, NodePath

from utils import rotate_single_vector
from laser_cannon import LaserCannon

RHO = 1 # A fictive "air" density" for atmospheric-like flight feeling

class Ship:
    """
    A SimpleShip has 10 state variables
    - position (3)
    - orientation (4)
    - linear speed (3)

    The linear speed is integrated from the ship's acceleration.
    However, the rotation rate is given directly (from user input
    or PNJ behaviour)

    "Forward" is on an object's Y axis in panda3d, so thrust is in +Y
    """

    def __init__(
            self, 
            app: ShowBase, 
            ship_name: str, 
            ini_position: np.ndarray = np.zeros(3),
            ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
            lift_model: bool=False
    ):
        self.app = app

        # Load configuration
        filepath = f"models/ships/{ship_name}/configuration.yaml"
        with open(filepath, "r") as f:
            self.conf = yaml.safe_load(f)
        self.mass_kg = self.conf["mass_kg"]
        self.max_thrust_n = self.conf["max_thrust_n"]
        self.max_speed_mps = self.conf["max_speed_mps"]
        self.max_pitch_rate_radps = np.deg2rad(self.conf["max_pitch_rate_degps"])
        self.max_yaw_rate_radps = np.deg2rad(self.conf["max_yaw_rate_degps"])
        self.max_roll_rate_radps = np.deg2rad(self.conf["max_roll_rate_degps"])
        self.drag_factor = 0.5 * RHO * self.conf["reference_surface_m2"] * self.conf["drag_coefficient"]

        # Create a dummy node to attach models
        self.node = NodePath("player_node")
        self.node.reparentTo(self.app.render)

        # Setup state vector
        self.state = np.zeros(10) # position (3), orientation (4), speed (3)
        self.state[:3] = ini_position
        self.state[3:7] = ini_orientation
        self.state_dot = np.zeros(10)
        self.state_dot_previous = np.zeros(10)
        self.pqr = np.zeros(3)
        self.scalar_thrust = 0

        # Assign physics
        if not lift_model:
            self.compute_derivatives = self.compute_derivatives_simple_physics
            self.move_ship = self.move_ship_simple_physics
        else:
            # TODO: more "realistic" flight model
            raise NotImplementedError

        # Prepare first integration step
        self.compute_derivatives()
        self.state_dot_previous = self.state_dot.copy()
        self.integrator_idx = self.app.integrator.set_state_variables(
            partial_x = self.state,
            partial_x_dot = self.state_dot,
            partial_x_dot_previous = self.state_dot_previous,
        ) 

        # Initialize cannons
        self.laser_cannon = LaserCannon(app=self.app, parent_ship=self)


    def set_inputs(self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float):
        """
        Sets the scalar thrust and rotational rates of the ship

        Panda3d seems to use the pitch-roll-yaw convention
        """
        self.scalar_thrust = throttle * self.max_thrust_n
        self.pqr = np.array(
            [
                pitch_rate * self.max_pitch_rate_radps,
                roll_rate * self.max_roll_rate_radps,
                yaw_rate * self.max_yaw_rate_radps,
            ]
        )

    def compute_derivatives_simple_physics(self):
        """
        This is the flight model for the ships

        Since there is no lift model, the velocity is always aligned
        with the nose of the ship

        A SimpleShip has 10 state variables
        - position (3)
        - orientation (4)
        - linear speed (3)
        """
        # Save last derivative
        self.state_dot_previous = self.state_dot.copy()

        # Compute derivative of position
        speed = self.state[7:10]
        self.state_dot[0:3] = speed
        # Compute derivative of orientation
        quat = np.quaternion(*self.state[3:7])
        quat_pqr = np.quaternion(0, *self.pqr)
        # Formula for pqr in body axes
        quat_dot = 0.5 * quat * quat_pqr
        self.state_dot[3:7] = quaternion.as_float_array(quat_dot)

        # Compute derivative of speed:
        # Drag is opposed to speed, thrust is aligned to ship direction
        speed_norm = np.linalg.norm(speed)
        drag = - self.drag_factor * speed_norm * speed
        thrust_body = np.array([0.0, self.scalar_thrust, 0.0])
        thrust = rotate_single_vector(
            quat, thrust_body
        )
        acceleration = (thrust + drag) / self.mass_kg
        self.state_dot[7:10] = acceleration

    def move_ship_simple_physics(self):
        """
        Gets the new ship's state, then prepare the next
        integration step.
        
        Since there is no lift model, the velocity is always aligned
        with the nose of the ship
        """
        # Get state
        self.state = self.app.integrator.get_state_variables(
            first_idx = self.integrator_idx,
            n_var = 10,
        )
        # Clip speed norm
        speed = self.state[7:10]
        speed_norm = np.linalg.norm(speed)
        if speed_norm > self.max_speed_mps:
            speed_norm = self.max_speed_mps
        
        # Normalize ship orientation
        self.orientation = self.state[3:7].copy()
        self.orientation /= np.linalg.norm(self.orientation)
        self.state[3:7] = self.orientation.copy()
        # Reorient speed in ship direction
        quat = np.quaternion(*self.orientation)
        speed_body = np.array([0.0, speed_norm, 0.0])
        self.speed = rotate_single_vector(
            quat, speed_body
        )
        self.state[7:10] = self.speed.copy()

        # Prepare next integration step
        self.compute_derivatives_simple_physics()
        self.integrator_idx = self.app.integrator.set_state_variables(
            partial_x = self.state,
            partial_x_dot = self.state_dot,
            partial_x_dot_previous = self.state_dot_previous,
        )
    