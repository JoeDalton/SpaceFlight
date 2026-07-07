import logging

import numpy as np
import quaternion
import yaml
from panda3d.core import Quat

from space_flight import DATAFILES_PATH, FORWARD_BODY, RIGHT_BODY, UP_BODY
from space_flight.actors.capital_ship.sub_system import SubSystem
from space_flight.actors.capital_ship.targeting_system import TargetingSystem
from space_flight.actors.laser_cannon import LaserCannon
from space_flight.actors.turret_model import TurretModel
from space_flight.ai.auto_aim import AutoAim
from space_flight.utils import low_pass_filter_first_order, rotate_single_vector

LOGGER = logging.getLogger()


class Turret(SubSystem):
    """
    A turret subsystem: a ship-mounted, bot-controlled weapon that aims in yaw
    and pitch and fires laser cannons.

    A turret is a :class:`SubSystem`, so it is a destructible, targetable part of
    its ship (into-only "subsystem" collider, dies with the ship, absorbs ram
    damage while the ship takes the impulse). It is still driven by a Bot: the bot
    is its ``parent`` (controller, whose name the HUD/logs read) while
    ``mounted_on`` is the ship it sits on.

    Movement has 2 state variables (yaw, pitch), integrated with a basic Euler 1
    step; the rotation rates come directly from the bot's pilot.

    "Forward" is on an object's Y axis in panda3d. X is right, Z is up.

    :param game: The game/flight state
    :param parent: The controlling Bot
    :param turret_type: The turret model/config name
    :param mounted_on: The ship this turret is bolted onto
    :param base_position: Mounting position relative to the ship node
    :param base_orientation: Mounting orientation (quaternion) on the ship
    :param ini_yaw_deg: Initial yaw angle
    :param ini_pitch_deg: Initial pitch angle
    """

    def __init__(
        self,
        game,
        parent,
        turret_type: str,
        mounted_on,
        base_position: np.ndarray = np.zeros(3),
        base_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_yaw_deg: float = 0.0,
        ini_pitch_deg: float = 30.0,
    ):
        # Load configuration first: it feeds the SubSystem parameters below
        filepath = DATAFILES_PATH / f"models/turrets/{turret_type}/configuration.yaml"
        with open(filepath, "r") as f:
            conf = yaml.safe_load(f)

        super().__init__(
            game=game,
            parent=parent,
            mounted_on=mounted_on,
            relative_position=base_position,
            hit_box_radius_m=conf["hit_box_radius_m"],
            health=conf["health"],
            explosion_scale=conf["explosion_scale"],
            name="turret",
        )
        self.conf = conf

        # Orient the mounting base (SubSystem already positioned the node)
        self.node.set_quat(Quat(*base_orientation))
        self.position = np.array(self.node.getPos(self.game.root_node))

        # Agility and physical delay of the turret's aim
        self.physics_filter_time_s = conf["physics_filter_time_s"]
        self.max_pitch_rate_degps = conf["max_pitch_rate_degps"]
        self.max_yaw_rate_degps = conf["max_yaw_rate_degps"]

        # Kinematic/targeting attributes read by the turret AI. Directions are
        # filled in by move(); a turret has no linear velocity of its own.
        self.right = np.zeros(3)
        self.forward = np.zeros(3)
        self.up = np.zeros(3)
        self.speed = np.zeros(3)
        # Orientation frame whose forward (+Y) axis is the cannon's aim. Read by
        # AutoAim to fold the firing solution back into the turret's frame; kept
        # in sync with the cannon each frame in move().
        self.orientation = np.array(base_orientation, dtype=float)
        self.base_forward = np.zeros(3)
        self.base_right = np.zeros(3)
        self.base_up = np.zeros(3)
        self.target = None
        self.target_id = None
        self.target_idx = None
        self.formation = None

        # Aim state (yaw, pitch)
        self.state = np.array([ini_yaw_deg, ini_pitch_deg])
        self.state_derivative = np.zeros(2)

        # Render
        self.turret_model = TurretModel(
            game=self.game, parent_node=self.node, turret_type=turret_type
        )
        self.set_yaw = self.turret_model.set_yaw
        self.set_pitch = self.turret_model.set_pitch
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])

        # Cannons. A turret fires straight down its barrel by default; a living
        # targeting system on the ship grants auto-aim and a faster fire rate,
        # pulled each frame in move() (see _apply_targeting_support).
        self.laser_cannon = LaserCannon(
            game=self.game, parent=self, parent_node=self.turret_model.cannon_node
        )
        self.base_fire_delay = self.laser_cannon.fire_delay
        # Auto-aim is held ready but only exposed to the cannon (through
        # self.auto_aim) while a targeting system is alive. self.auto_aim is None
        # otherwise, which the cannon reads as "fire straight ahead". It is
        # retuned from the parameters of whichever targeting system is boosting
        # us; _targeting_source tracks that system so we only reconfigure on a
        # change.
        self._auto_aim = AutoAim(game=self.game, parent=self)
        self.auto_aim = None
        self._targeting_source = None

    def move(self, yaw_rate: float, pitch_rate: float):
        """
        Moves the turret given its turn rates.
        Runs a low pass filter on the turn rates beforehand to emulate delay in
        physical systems.

        :param yaw_rate: Yaw rate command in [-1, 1]
        :param pitch_rate: Pitch rate command in [-1, 1]
        """
        dt = self.game.game_time.get_time_step()

        # Apply low pass filter on rotation rates
        self.state_derivative = low_pass_filter_first_order(
            value=np.array(
                [
                    yaw_rate * self.max_yaw_rate_degps,
                    pitch_rate * self.max_pitch_rate_degps,
                ]
            ),
            previous=self.state_derivative,
            dt=dt,
            rise_time=self.physics_filter_time_s,
            fall_time=self.physics_filter_time_s,
        )

        # Compute new angles
        new_state = self.game.integrator.first_order_euler_step(
            state_derivative=self.state_derivative, state=self.state
        )
        # Clip angles to the turret's possibilities
        new_state[1] = min(
            self.conf["max_pitch_deg"], max(new_state[1], self.conf["min_pitch_deg"])
        )
        self.state = new_state

        # Set angles on the model
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])

        # Compute remarkable directions of the turret cannon
        cannon_quat = np.quaternion(
            *self.turret_model.cannon_node.getQuat(self.game.root_node)
        )
        self.forward = rotate_single_vector(cannon_quat, FORWARD_BODY)
        # Aim frame for the auto-aim firing solution (forward is the cannon's +Y)
        self.orientation = quaternion.as_float_array(cannon_quat)
        base_quat = np.quaternion(*self.node.getQuat(self.game.root_node))
        self.base_forward = rotate_single_vector(base_quat, FORWARD_BODY)
        self.base_right = rotate_single_vector(base_quat, RIGHT_BODY)
        self.base_up = rotate_single_vector(base_quat, UP_BODY)

        # Pull the current support from the ship's targeting system: auto-aim and
        # a faster fire rate while one is alive, unassisted fire otherwise.
        self._apply_targeting_support()

    def _active_targeting_system(self):
        """
        Finds a living targeting system on the ship this turret is mounted on.

        :return: The active :class:`TargetingSystem` boosting this turret, or
            ``None`` if its ship has none alive
        """
        for sub_system in getattr(self.mounted_on, "sub_systems", []):
            if isinstance(sub_system, TargetingSystem) and not sub_system.is_dead:
                return sub_system
        return None

    def _apply_targeting_support(self):
        """
        Applies (or removes) the boosts granted by the ship's targeting system.

        While a targeting system is alive the turret gains auto-aim (its shots
        lead the target) and a faster fire rate; with none alive it fires
        straight down the barrel at its base rate.
        """
        targeting_system = self._active_targeting_system()
        if targeting_system is None:
            # No fire control: fire straight ahead at the base rate.
            self.auto_aim = None
            self.laser_cannon.fire_delay = self.base_fire_delay
            self._targeting_source = None
        else:
            # Fire control online: retune the auto-aim from this system (only
            # when it just came online or changed), then lead the target and
            # fire faster.
            if targeting_system is not self._targeting_source:
                self._auto_aim.configure(**targeting_system.auto_aim_params)
                self._targeting_source = targeting_system
            self.auto_aim = self._auto_aim
            self.auto_aim.compute_acquisition()
            self.laser_cannon.fire_delay = (
                self.base_fire_delay / targeting_system.fire_rate_multiplier
            )

    def clean(self):
        """
        Cleans the turret's cannons, auto-aim and model, then the subsystem itself.
        """
        if not self.is_clean:
            self.laser_cannon.clean()
            self.laser_cannon = None
            self._auto_aim.clean()
            self._auto_aim = None
            self.auto_aim = None
            self.turret_model.clean()
            self.turret_model = None
            super().clean()
