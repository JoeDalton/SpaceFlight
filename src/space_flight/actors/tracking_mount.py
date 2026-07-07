import logging

import numpy as np
import quaternion
from panda3d.core import Quat

from space_flight import FORWARD_BODY, RIGHT_BODY, UP_BODY
from space_flight.actors.capital_ship.sub_system import SubSystem
from space_flight.actors.turret_model import TurretModel
from space_flight.ai import Personality
from space_flight.utils import low_pass_filter_first_order, rotate_single_vector

LOGGER = logging.getLogger()


class TrackingMount(SubSystem):
    """
    A ship-mounted subsystem that swivels in yaw and pitch to track a target.

    This is the generic base shared by the laser :class:`~space_flight.actors.
    turret.Turret` and the :class:`~space_flight.actors.tractor_beam.
    TractorBeamProjector`: everything about *aiming* lives here (mounting,
    yaw/pitch state, the swivelling model, the remarkable directions), while what
    the mount *does* once aimed is deferred to :meth:`_operate`, which subclasses
    override (fire cannons, grab a prey...).

    A tracking mount is a :class:`SubSystem` (destructible, targetable, dies with
    its ship) driven by a Bot: the bot is its ``parent`` (controller), while
    ``mounted_on`` is the ship it sits on. Its generic AI
    (:mod:`space_flight.ai.tracking_mount`) selects a prey and steers the barrel;
    the navigator publishes its lead solution onto :attr:`aim_direction` /
    :attr:`target_distance_m` for :meth:`_operate` to act upon.

    "Forward" is on an object's Y axis in panda3d. X is right, Z is up.

    :param game: The game/flight state
    :param parent: The controlling Bot
    :param mounted_on: The ship this mount is bolted onto
    :param conf: The mount's loaded configuration (hardware specs)
    :param model_type: The swivelling model to load (see :class:`TurretModel`)
    :param base_position: Mounting position relative to the ship node
    :param base_orientation: Mounting orientation (quaternion) on the ship
    :param ini_yaw_deg: Initial yaw angle
    :param ini_pitch_deg: Initial pitch angle
    :param personality: Behaviour parameters (shared with the mount's AI)
    :param name: Node and display name of the mount
    """

    def __init__(
        self,
        game,
        parent,
        mounted_on,
        conf: dict,
        model_type: str,
        base_position: np.ndarray = np.zeros(3),
        base_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_yaw_deg: float = 0.0,
        ini_pitch_deg: float = 30.0,
        personality: dict = Personality.TURRET_DEFAULT,
        name: str = "tracking_mount",
    ):
        super().__init__(
            game=game,
            parent=parent,
            mounted_on=mounted_on,
            relative_position=base_position,
            hit_box_radius_m=conf["hit_box_radius_m"],
            health=conf["health"],
            explosion_scale=conf["explosion_scale"],
            name=name,
        )
        self.conf = conf
        self.personality = personality

        # Orient the mounting base (SubSystem already positioned the node)
        self.node.set_quat(Quat(*base_orientation))
        self.position = np.array(self.node.getPos(self.game.root_node))

        # Agility and physical delay of the mount's aim
        self.physics_filter_time_s = conf["physics_filter_time_s"]
        self.max_pitch_rate_degps = conf["max_pitch_rate_degps"]
        self.max_yaw_rate_degps = conf["max_yaw_rate_degps"]

        # Kinematic/targeting attributes read by the AI. Directions are filled in
        # by move(); a mount has no linear velocity of its own.
        self.right = np.zeros(3)
        self.forward = np.zeros(3)
        self.up = np.zeros(3)
        # speed is a property: a mount rides its ship, so it reports the host's
        # velocity (see below).
        # Orientation frame whose forward (+Y) axis is the barrel/antenna aim.
        self.orientation = np.array(base_orientation, dtype=float)
        self.base_forward = np.zeros(3)
        self.base_right = np.zeros(3)
        self.base_up = np.zeros(3)
        self.target = None
        self.target_id = None
        self.target_idx = None
        self.formation = None
        # Aim solution published each frame by the navigator, consumed by
        # _operate: the lead direction to point at and the distance to the target.
        self.aim_direction = np.zeros(3)
        self.target_distance_m = np.inf

        # Aim state (yaw, pitch)
        self.state = np.array([ini_yaw_deg, ini_pitch_deg])
        self.state_derivative = np.zeros(2)

        # Render: the swivelling model whose cannon/antenna node we point.
        self.turret_model = TurretModel(
            game=self.game, parent_node=self.node, turret_type=model_type
        )
        self.set_yaw = self.turret_model.set_yaw
        self.set_pitch = self.turret_model.set_pitch
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])

    @property
    def speed(self):
        """
        The mount's velocity: it is bolted to a moving ship, so it *is* the host
        ship's velocity, read live rather than mirrored.

        This keeps kinematics-dependent effects matched to the ship without any
        per-frame bookkeeping: the death explosion carries the ship's velocity
        (the mount is a Bot *and* a subsystem, so it is the Bot's ``play_death``,
        reading ``pawn.speed``, that fires it), and a turret's shots inherit the
        ship's motion. It is consistent with the interaction velocities, so lead
        aim is unaffected.

        :return: The host ship's velocity, or zeros once detached (cleaned)
        """
        if getattr(self, "mounted_on", None) is None:
            return np.zeros(3)
        return np.asarray(getattr(self.mounted_on, "speed", np.zeros(3)), dtype=float)

    def move(self, yaw_rate: float, pitch_rate: float):
        """
        Moves the mount given its turn rates.

        Runs a low pass filter on the turn rates beforehand to emulate delay in
        physical systems, integrates the aim, refreshes the remarkable directions,
        then runs the subclass action via :meth:`_operate`.

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
        # Clip angles to the mount's possibilities
        new_state[1] = min(
            self.conf["max_pitch_deg"], max(new_state[1], self.conf["min_pitch_deg"])
        )
        self.state = new_state

        # Set angles on the model
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])

        # Compute remarkable directions of the mount's cannon/antenna
        cannon_quat = np.quaternion(
            *self.turret_model.cannon_node.getQuat(self.game.root_node)
        )
        self.forward = rotate_single_vector(cannon_quat, FORWARD_BODY)
        # Aim frame for the firing/grab solution (forward is the cannon's +Y)
        self.orientation = quaternion.as_float_array(cannon_quat)
        base_quat = np.quaternion(*self.node.getQuat(self.game.root_node))
        self.base_forward = rotate_single_vector(base_quat, FORWARD_BODY)
        self.base_right = rotate_single_vector(base_quat, RIGHT_BODY)
        self.base_up = rotate_single_vector(base_quat, UP_BODY)

        # Run the subclass-specific action now that the mount is aimed.
        self._operate()

    def _operate(self):
        """
        Hook for the mount's per-frame action once aimed.

        No-op in the base; subclasses fire cannons, grab a prey, etc.
        """
        pass

    def clean(self):
        """
        Cleans the swivelling model, then the subsystem itself.
        """
        if not self.is_clean:
            if self.turret_model is not None:
                self.turret_model.clean()
                self.turret_model = None
            super().clean()
