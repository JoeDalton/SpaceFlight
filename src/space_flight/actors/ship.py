from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml
from panda3d.core import NodePath, Quat, Vec3

from space_flight import (
    DATAFILES_PATH,
    DEBUG_DELETION,
    FLIGHT_MODEL,
    RECORD_GAME,
    RIGHT_BODY,
    THROTTLE_BOOST_VALUE,
    UP_BODY,
)
from space_flight.actors.pawn import Pawn
from space_flight.actors.ship_model import ShipModel
from space_flight.fx.damage_fx import DamageFX
from space_flight.utils import (
    cross3,
    low_pass_filter_first_order,
    magnitude,
    rotation_matrix_coefficients,
)

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()
RHO = 1  # A fictive "air" density" for atmospheric-like flight feeling
WEAPON_DAMAGE_TO_FORCE_FACTOR = 2.0
DAMAGE_FORCE_APPLICATION_DURATION_S = 0.1
ZERO_THRUST_POSITION = 0.05  # TODO move to input_system ? Should be tunable ?
# Death spin defaults, overridable per ship in configuration.yaml. The tumble rate
# ramps with sqrt(time since death) up to DEATH_MAX_TUMBLE_RATE_DEGPS, reached at
# DEATH_SPIN_DURATION_S. This ceiling is deliberately separate from the flight
# max_*_rate limits: it is written straight into self.pqr (bypassing the input
# clamp / actuator low-pass) so a dramatic tumble is possible.
DEATH_SPIN_DURATION_S = 2.5
DEATH_MAX_TUMBLE_RATE_DEGPS = 400.0
TUMBLE_RATE_FACTORS = np.array([0.2, 1.0, 0.2])
# Deepest play-rate cut of the player's interior engine at a full damage stutter
# (see Ship._engine_sputter_factor, driven by CockpitFX's shared stutter events).
ENGINE_SPUTTER_MAX_DEPTH = 0.6
# Reference scales normalising the placeholder mobility blend (see _compute_mobility)
MOBILITY_REFERENCE_SPEED_MPS = 200.0
MOBILITY_REFERENCE_TURN_RATE_RADPS = np.deg2rad(80.0)
# A speed above this multiple of the ship's own max is not physical (terminal
# velocity is max_speed_mps); it only happens when the explicit integrator
# diverges. Detected here and snapped back to terminal before it overflows.
DIVERGENCE_SPEED_FACTOR = 4.0
# Turn rate profile: fraction of the max turn rates available as a function of the
# throttle command. A parabola through (0, IDLE), (PEAK_THROTTLE, 1.0) and
# (1, FULL) up to full throttle, then linear down to BOOST_MAX_FRACTION at
# THROTTLE_BOOST_VALUE.
TURN_RATE_IDLE_FRACTION = 0.5
TURN_RATE_PEAK_THROTTLE = 0.6
TURN_RATE_FULL_THRUST_FRACTION = 0.7
TURN_RATE_BOOST_MAX_FRACTION = 0.1
_TURN_RATE_PARABOLA = np.polyfit(
    [0.0, TURN_RATE_PEAK_THROTTLE, 1.0],
    [TURN_RATE_IDLE_FRACTION, 1.0, TURN_RATE_FULL_THRUST_FRACTION],
    2,
)


def turn_rate_scale(throttle: float) -> float:
    """
    Fraction of the max turn rates available at a given throttle command.

    The fitted parabola peaks marginally above 1 (near throttle 0.56), so it is
    clipped to 1. Above full throttle (boost) the scale falls linearly.

    :param throttle: Throttle command, in [0, THROTTLE_BOOST_VALUE]
    :return: Scale in [TURN_RATE_BOOST_MAX_FRACTION, 1]
    """
    throttle = min(max(throttle, 0.0), THROTTLE_BOOST_VALUE)
    if throttle <= 1.0:
        return min(1.0, float(np.polyval(_TURN_RATE_PARABOLA, throttle)))
    boost_ratio = (throttle - 1.0) / (THROTTLE_BOOST_VALUE - 1.0)
    return TURN_RATE_FULL_THRUST_FRACTION + boost_ratio * (
        TURN_RATE_BOOST_MAX_FRACTION - TURN_RATE_FULL_THRUST_FRACTION
    )


class Ship(Pawn):
    """
    A Ship has 10 state variables
    - position (3)
    - orientation (4)
    - linear speed (3)

    The linear speed is integrated from the ship's acceleration, while the
    rotation rate is commanded directly (player input or AI).

    "Forward" is on an object's Y axis in panda3d, so thrust is in +Y
    X axis is to the right, Z axis is up
    """

    def __init__(
        self,
        game: FlightState,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        is_cockpit: bool = True,
        team: int = 0,
    ):
        super().__init__(game=game, parent=parent, team=team)

        # Load configuration
        self.conf = self._load_configuration(ship_type)
        # Set a low-pass filter time to emulate physical delay in
        # thrust and rotational rates
        self.inputs_filter_time_s = self.conf["inputs_filter_time_s"]
        self.mass_kg = self.conf["mass_kg"]
        self.max_thrust_n = self.conf["max_thrust_n"]
        self.brake_factor_nspm = self.conf["brake_factor_nspm"]
        self.max_pitch_rate_radps = np.deg2rad(self.conf["max_pitch_rate_degps"])
        self.max_yaw_rate_radps = np.deg2rad(self.conf["max_yaw_rate_degps"])
        self.max_roll_rate_radps = np.deg2rad(self.conf["max_roll_rate_degps"])
        self.additional_force_n = np.zeros(3)  # e.g. for gravity if applicable
        self.impact_force_n = np.zeros(3)  # e.g. for collisions and laser hits
        # Transient world-frame forces from other actors (e.g. a tractor beam),
        # see apply_external_force
        self.external_force_n = np.zeros(3)
        self.formation = None

        self.drag_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["drag_coefficient"]
        )
        self.lift_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["lift_coefficient_slope_pdeg"]
        )
        self.lateral_lift_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["lateral_lift_coefficient_slope_pdeg"]
        )
        self.lift_inefficiency = self.conf.get(
            "lift_inefficiency", 0.0
        )  # = 1/(pi * AR * e)
        self.max_speed_mps = self._compute_max_speed_mps()

        # Manoeuverability signal read by attackers' tacticians (see Pawn)
        self.mobility = self._compute_mobility()

        # Setup health
        self.max_health = self.conf["health"]
        self.health = self.max_health
        # Shield setup is ship-type dependent
        self.parent.add_task(method=self.ship_handle_health)

        # Death spin (see begin_tumble / tumble_step)
        self.death_spin_duration_s = self.conf.get(
            "death_spin_duration_s", DEATH_SPIN_DURATION_S
        )
        self.death_max_tumble_rate_radps = np.deg2rad(
            self.conf.get("death_max_tumble_rate_degps", DEATH_MAX_TUMBLE_RATE_DEGPS)
        )
        self._tumble_axis = np.array([0.0, 1.0, 0.0])

        # Create a dummy node to attach models
        self.node = NodePath("ship_node")
        self.node.reparentTo(self.game.root_node)
        self.node.set_pos(*ini_position)
        self.node.set_quat(Quat(*ini_orientation))

        # Setup state vector
        self.position = ini_position.copy()
        self.orientation = ini_orientation.copy()
        self.speed = ini_speed.copy()
        # Last known finite pose, used by the physics circuit-breaker to recover
        # from a numerical divergence without crashing the renderer.
        self._last_finite_position = self.position.copy()
        self._last_finite_orientation = self.orientation.copy()
        self.state = np.zeros(10)  # position (3), orientation (4), speed (3)
        self.state[:3] = ini_position
        self.state[3:7] = ini_orientation
        self.state[7:10] = ini_speed
        self.state_dot = np.zeros(10)
        self.state_dot_previous = np.zeros(10)
        self.pqr = np.zeros(3)
        self.scalar_thrust_n = 0

        # Prepare state corrections due to collisions
        self.velocity_correction = np.zeros(3)
        self.position_correction = np.zeros(3)

        # Prepare first integration step
        self.compute_derivatives()
        self.state_dot_previous = self.state_dot.copy()
        self.integrator_idx = self.game.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

        # Collision setup is ship-type dependent

        # Death animation is ship-type dependent

        # Create render
        self.model = self._build_model(ship_type=ship_type, is_cockpit=is_cockpit)

        # Damage / death smoke-and-fire trail
        self.damage_fx = self._build_damage_fx()
        if self.damage_fx is not None:
            self.parent.add_task(method=self.damage_fx.update)

        # Body-frame bounding box for AI that needs the target's extents (the
        # capital-ship orbit's oriented bounding box); the reader rotates it by the
        # ship's orientation at runtime.
        self.bounding_box_half_extents = self._compute_bounding_box_half_extents()

        # Initialize engine sound (optional: a ship type without one is silent)
        self.sound = None
        self.sound_pool = None
        if self.parent.name == "player":
            sound_file = DATAFILES_PATH / self.conf["interior_engine_sound"]
            self.sound_pool = self.game.app.asset_manager.get_asset(
                asset_type="sound",
                path=sound_file,
            )
            self.sound = self.sound_pool.get_sound()
            self.sound.setLoop(True)
            self.sound.setVolume(0.1)
        elif "exterior_engine_sound" in self.conf:
            sound_file = DATAFILES_PATH / self.conf["exterior_engine_sound"]
            self.sound_pool = self.game.app.asset_manager.get_asset(
                asset_type="3d_sound",
                path=sound_file,
            )
            self.sound = self.sound_pool.get_sound()
            self.sound.setLoop(True)
            self.sound.setVolume(10.0)
            # Follows the ship node, Doppler-shifted by the ship's velocity
            self.game.app.sfx.attach_sound(self.sound, self.node, velocity_source=self)

            # TODO Attach engine sound to a node located at the engine location

        # Play a bit later to avoid audio artifacts at startup
        if self.sound is not None:
            self.game.delayed_methods.do_method_later(
                delay_s=0.5,
                name="Play_engine_sound",
                method=self.sound.play,
            )

    def _load_configuration(self, ship_type: str) -> dict:
        """
        Load the ship type's configuration. Overridden by pawns configured
        elsewhere (e.g. ordnance).

        :param ship_type: The ship type, i.e. its configuration directory name
        :return: The configuration dictionary
        """
        filepath = DATAFILES_PATH / f"models/ships/{ship_type}/configuration.yaml"
        with open(filepath, "r") as f:
            return yaml.safe_load(f)

    def _compute_max_speed_mps(self) -> float:
        """
        The ship's top speed: its terminal velocity, where full thrust balances
        drag.

        :return: The top speed, in m/s
        """
        return np.sqrt(self.max_thrust_n / self.drag_factor)

    def _build_damage_fx(self) -> DamageFX | None:
        """
        Create the damage / death smoke-and-fire trail.

        :return: The trail, or None for a pawn that never smokes
        """
        return DamageFX(game=self.game, owner=self)

    def _build_model(self, ship_type: str, is_cockpit: bool) -> ShipModel:
        """
        Create the render model, anchored to the ship node.

        :param ship_type: The ship type
        :param is_cockpit: Whether to show the cockpit rather than the exterior
        :return: The model
        """
        return ShipModel(
            game=self.game,
            parent_node=self.node,
            ship_type=ship_type,
            is_cockpit=is_cockpit,
        )

    def _turn_rate_scale(self, throttle: float) -> float:
        """
        Fraction of the max turn rates available at a given throttle command
        (see turn_rate_scale).

        :param throttle: Throttle command
        :return: The scale applied to the turn rate commands
        """
        return turn_rate_scale(throttle)

    def _compute_mobility(self) -> float:
        """
        Blend the ship's kinematic limits into a manoeuverability score in [0, 1].

        PLACEHOLDER blend: normalise the top speed and the mean turn rate against
        reference scales and average them. Fighters land near 1, capital ships near
        0, which is all the tactician's PURSUIT-vs-STRAFE choice needs for now.

        :return: The mobility score, clamped to [0, 1]
        """
        speed_term = min(self.max_speed_mps / MOBILITY_REFERENCE_SPEED_MPS, 1.0)
        mean_turn_rate_radps = (
            self.max_pitch_rate_radps
            + self.max_yaw_rate_radps
            + self.max_roll_rate_radps
        ) / 3.0
        turn_term = min(mean_turn_rate_radps / MOBILITY_REFERENCE_TURN_RATE_RADPS, 1.0)
        return float(0.5 * speed_term + 0.5 * turn_term)

    def _compute_bounding_box_half_extents(self) -> np.ndarray:
        """
        Measure the render model's tight bounds in the ship's own body frame and
        return the half-extents (X right, Y forward, Z up), in metres. Falls back
        to hit_box_radius_m when the bounds are unavailable or degenerate.

        :return: The model-space bounding-box half-extents
        """
        fallback = float(self.conf.get("hit_box_radius_m", 10.0))
        try:
            bounds = self.model.model.getTightBounds(self.node)
        except Exception:
            bounds = None
        if not bounds:
            return np.array([fallback, fallback, fallback])
        min_point, max_point = bounds
        half_extents = 0.5 * np.array(
            [
                max_point[0] - min_point[0],
                max_point[1] - min_point[1],
                max_point[2] - min_point[2],
            ]
        )
        # Guard degenerate axes (e.g. a flat model) with the collision radius.
        return np.where(half_extents > 1e-3, half_extents, fallback)

    def set_inputs(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Sets the scalar thrust and rotational rates of the ship.

        The throttle is squared so the velocity is easier to modulate; below
        ZERO_THRUST_POSITION it brakes (airplane model) or cuts thrust (space).
        The turn rates are scaled by _turn_rate_scale(throttle).
        Both are low-pass filtered to emulate delay in physical systems.
        pqr is stored in Panda3D's pitch-roll-yaw order.

        :param throttle: Throttle command in [0, 1], above 1 for boost
        :param yaw_rate: Yaw rate command in [-1, 1] (fraction of the max rate)
        :param pitch_rate: Pitch rate command in [-1, 1]
        :param roll_rate: Roll rate command in [-1, 1]
        """
        dt = self.game.game_time.get_time_step()

        if throttle >= ZERO_THRUST_POSITION:
            # Thrust is positive
            scalar_thrust_n = (
                (throttle - ZERO_THRUST_POSITION) / (1 - ZERO_THRUST_POSITION)
            ) ** 2 * self.max_thrust_n
        else:
            if FLIGHT_MODEL == "airplane":
                # Ship is braking, propotionally to its forward speed
                brake_intensity = (
                    ZERO_THRUST_POSITION - throttle
                ) / ZERO_THRUST_POSITION
                forward_speed_mps = max(0.0, np.dot(self.speed, self.forward))
                scalar_thrust_n = (
                    -forward_speed_mps * self.brake_factor_nspm * brake_intensity
                )
            elif FLIGHT_MODEL == "space":
                scalar_thrust_n = 0
            else:
                raise Exception

        pqr = self._turn_rate_scale(throttle) * np.array(
            [
                pitch_rate * self.max_pitch_rate_radps,
                roll_rate * self.max_roll_rate_radps,
                yaw_rate * self.max_yaw_rate_radps,
            ]
        )

        [
            self.scalar_thrust_n,
            self.pqr[0],
            self.pqr[1],
            self.pqr[2],
        ] = low_pass_filter_first_order(
            value=np.array(
                [
                    scalar_thrust_n,
                    pqr[0],
                    pqr[1],
                    pqr[2],
                ]
            ),
            previous=np.array(
                [
                    self.scalar_thrust_n,
                    self.pqr[0],
                    self.pqr[1],
                    self.pqr[2],
                ]
            ),
            dt=dt,
            rise_time=self.inputs_filter_time_s,
            fall_time=self.inputs_filter_time_s,
        )

    def compute_derivatives(self):
        """
        This is the flight model for the ships

        Depends on the FLIGHT_MODEL global variable
        - "airplane": airplane-like flight with lift, drag, AoA, sideslip
        - "space": Thrust is all you have, if you dare !

        Rotation rates are assumed to be perfectly-controlled inputs. Consumes
        (zeroes) external_force_n.
        """

        # Save last derivative
        self.state_dot_previous = self.state_dot.copy()

        # Compute derivative of position
        self.state_dot[0:3] = self.speed
        # Compute derivative of orientation, and the body axes
        r00, r01, r02, r10, r11, r12, r20, r21, r22 = (
            self._compute_attitude_derivative()
        )

        # Compute derivative of speed with forces:
        # Thrust is aligned with ship direction
        self.thrust_n = self.scalar_thrust_n * self.forward

        if FLIGHT_MODEL == "airplane":
            speed_norm = magnitude(self.speed)
            speed_norm_squared = speed_norm**2
            if math.isnan(speed_norm) or (speed_norm <= 1e-4):
                # No lift or drag without speed
                self.drag_n = np.zeros(3)
                self.lift_n = np.zeros(3)
                self.lift_body_n = np.zeros(3)
            else:
                # Lift is perpendicular to ship side and airflow
                # and proportional to angle of attack
                # + And perpendicular to ship up and airflow
                # and proportional to side-slip angle
                # Airflow in body axes: -speed rotated world to body (transpose)
                sx, sy, sz = self.speed
                airflow_x = -(r00 * sx + r10 * sy + r20 * sz)
                airflow_y = -(r01 * sx + r11 * sy + r21 * sz)
                airflow_z = -(r02 * sx + r12 * sy + r22 * sz)
                airflow_direction_body = (
                    np.array((airflow_x, airflow_y, airflow_z)) / speed_norm
                )
                angle_of_attack_deg = -math.degrees(math.atan2(-airflow_z, -airflow_y))
                # Clamp before arcsin: the ratio is mathematically in [-1, 1]
                # (a velocity component over the speed norm) but float error can
                # push it just past ±1, making arcsin return NaN.
                side_slip_angle_deg = math.degrees(
                    math.asin(min(max(airflow_x / speed_norm, -1.0), 1.0))
                )
                # TODO RIGHT_BODY/UP_BODY are axis-aligned unit vectors, so
                # these two cross3 calls are just component permutations of
                # airflow_direction_body (e.g. cross3(a, RIGHT_BODY) == (0,
                # a[2], -a[1])) -- measured ~0.6% of total profiled game time,
                # so likely not worth the fragility of hardcoding it.
                self.lift_body_n = speed_norm_squared * (
                    self.lift_factor
                    * angle_of_attack_deg
                    * cross3(airflow_direction_body, RIGHT_BODY)
                    + self.lateral_lift_factor
                    * side_slip_angle_deg
                    * cross3(
                        UP_BODY,
                        airflow_direction_body,
                    )
                )
                # Turn lift in world coordinates
                lx, ly, lz = self.lift_body_n
                self.lift_n = np.array(
                    (
                        r00 * lx + r01 * ly + r02 * lz,
                        r10 * lx + r11 * ly + r12 * lz,
                        r20 * lx + r21 * ly + r22 * lz,
                    )
                )

                # Clip the lift to the max thrust to avoid simulation divergence
                lift_norm_n = magnitude(self.lift_n)
                if lift_norm_n > self.max_thrust_n:
                    self.lift_n /= lift_norm_n
                    self.lift_n *= self.max_thrust_n
                    lift_norm_n = self.max_thrust_n

                # Drag is opposed to speed: viscous+wave drag plus lift-induced
                # drag (quadratic in the post-clip lift magnitude)
                self.drag_n = (
                    -speed_norm
                    * self.speed
                    * (
                        self.drag_factor
                        + lift_norm_n**2 * self.lift_inefficiency / speed_norm_squared
                    )
                )

        elif FLIGHT_MODEL == "space":
            # Neither lift nor drag
            self.drag_n = np.zeros(3)
            self.lift_n = np.zeros(3)
            self.lift_body_n = np.zeros(3)
        else:
            raise NotImplementedError(f"Unknown flight model {FLIGHT_MODEL}")

        # Assemble thrust, lift, drag and accidental forces
        self.acceleration_mps2 = (
            self.thrust_n
            + self.drag_n
            + self.lift_n
            + self.additional_force_n
            + self.impact_force_n
            + self.external_force_n
        ) / self.mass_kg
        self.state_dot[7:10] = self.acceleration_mps2
        # Consume the external force: it is re-applied every frame for as long as
        # another actor (e.g. a tractor beam) keeps holding this ship, and drops
        # to zero on the first frame nothing applies it.
        self.external_force_n = np.zeros(3)

    def _compute_attitude_derivative(self) -> tuple[float, ...]:
        """
        Compute the derivative of the orientation from the body rates, and the
        ship's right, forward and up directions.

        :return: The body-to-world rotation matrix coefficients, row by row (its
            columns are the right, forward and up directions)
        """
        # q_dot = 0.5 * q * (0, pqr), the rates being in body axes (Hamilton
        # product written out in floats)
        w, x, y, z = self.orientation
        p, q, r = self.pqr
        self.state_dot[3:7] = (
            -0.5 * (x * p + y * q + z * r),
            0.5 * (w * p + y * r - z * q),
            0.5 * (w * q + z * p - x * r),
            0.5 * (w * r + x * q - y * p),
        )

        # Body-to-world rotation, built once for every vector rotated by the
        # caller
        coefficients = rotation_matrix_coefficients(w, x, y, z)
        r00, r01, r02, r10, r11, r12, r20, r21, r22 = coefficients
        self.right = np.array((r00, r10, r20))
        self.forward = np.array((r01, r11, r21))
        self.up = np.array((r02, r12, r22))
        return coefficients

    def move_ship_physics(self):
        """
        Gets the new ship's state, then prepare the next
        integration step.
        """
        # Record collision corrections
        if RECORD_GAME and self.parent.record:
            self.game.record.record(
                variable_name="player_position_correction_m",
                variable=self.position_correction.copy(),
            )
            self.game.record.record(
                variable_name="player_velocity_correction_mps",
                variable=self.velocity_correction.copy(),
            )

        # Get state
        self.state = self.game.integrator.get_state_variables(
            first_idx=self.integrator_idx,
            n_var=10,
        )
        # Apply position and velocity collision corrections
        self.state[:3] += self.position_correction
        self.state[7:10] += self.velocity_correction
        # Reset collision corrections
        self.position_correction = np.zeros(3)
        self.velocity_correction = np.zeros(3)

        # Record position, orientation and speed
        self.position = self.state[:3]
        self.orientation = self.state[3:7]
        self.speed = self.state[7:10]

        # Circuit-breaker against numerical divergence (stiff manoeuvres, collision
        # impulses): never let non-finite or runaway state reach the renderer, which
        # would assert on a NaN/inf node transform.
        self._sanitize_state()

        # Prepare next integration step
        self.compute_derivatives()
        self.integrator_idx = self.game.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

    def _sanitize_state(self):
        """
        Physics circuit-breaker: keep non-finite or runaway state out of the
        renderer.

        Numerically stiff manoeuvres or large collision impulses can, rarely, blow
        the integrated state up to inf/NaN, which then asserts in Panda3D when the
        node transform is set. Rather than crash, recover: a still-finite but
        runaway speed is clamped, and a non-finite state is reverted to the last
        known-good pose with zeroed velocity. Both cases are logged so the
        underlying divergence can be investigated.
        """
        if np.all(np.isfinite(self.state)):
            speed_norm = magnitude(self.speed)
            if speed_norm > DIVERGENCE_SPEED_FACTOR * self.max_speed_mps:
                LOGGER.warning(
                    "Ship %s speed %.3g m/s is diverging; snapping to terminal.",
                    getattr(self.parent, "name", "?"),
                    speed_norm,
                )
                # Snap the (diverging) speed back to the physical terminal speed,
                # keeping its direction, so the ship stays in the fight.
                self.speed = self.speed * (self.max_speed_mps / speed_norm)
                self.state[7:10] = self.speed
            # Record this pose as the last known-good one.
            self._last_finite_position = self.position.copy()
            self._last_finite_orientation = self.orientation.copy()
            return

        # Non-finite state: revert to the last good pose and stop.
        LOGGER.warning(
            "Non-finite state for ship %s; recovering to last finite pose.",
            getattr(self.parent, "name", "?"),
        )
        self.position = self._last_finite_position.copy()
        self.orientation = self._last_finite_orientation.copy()
        self.speed = np.zeros(3)
        self.state[:3] = self.position
        self.state[3:7] = self.orientation
        self.state[7:10] = self.speed

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship given throttle and turn rates (see :meth:`set_inputs`)

        :param throttle: Throttle command in [0, 1], above 1 for boost
        :param yaw_rate: Yaw rate command in [-1, 1]
        :param pitch_rate: Pitch rate command in [-1, 1]
        :param roll_rate: Roll rate command in [-1, 1]
        """
        # Register flight inputs
        self.set_inputs(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )
        # Apply physics and integrate movement
        self.move_ship_physics()

        # Update engine sound
        self.adjust_engine_pitch(throttle=throttle)

        # Update render
        self.node.setPos(*self.position)
        self.node.setQuat(Quat(*self.orientation))

    @property
    def is_dying(self) -> bool:
        """
        Whether the ship is playing out its death (spin-out then explosion).

        The death *lifecycle* is owned by the controlling object -- the Bot for a
        crewed pawn, the Player for the player's -- so the ship simply reflects
        its ``is_dying`` (read by the damage trail and the damage guard). Falls
        back to False once the ship has been detached from its parent (cleaned).

        :return: True while the controller has the ship in its dying phase
        """
        return getattr(self.parent, "is_dying", False)

    def begin_tumble(self):
        """
        Enter the death spin: cut the engines and pick a random body axis to
        tumble about.

        The controller has already flagged its own ``is_dying`` (which this
        ship's :attr:`is_dying` mirrors) before calling this. The ship keeps its
        collider and integrator slot (it is not cleaned yet), so it stays
        collidable and coasts on its last velocity + drag/gravity while it spins.
        :meth:`tumble_step` then drives the spin each frame.
        """
        self.scalar_thrust_n = 0.0
        axis = np.random.normal(size=3)
        norm = magnitude(axis)
        if norm > 1e-6:
            self._tumble_axis = axis / norm

    def tumble_step(self, elapsed_s: float):
        """
        Advance the death spin by one frame: an out-of-control tumble whose rate
        ramps up with the square root of the time since death.

        Drives the physics directly (dead engines, a commanded body-rate written
        straight into ``pqr`` to bypass the flight-input clamp/low-pass), integrates
        it, and writes the pose to the render node -- everything :meth:`move` does,
        minus the AI/flight inputs.

        :param elapsed_s: Seconds since the ship began dying
        """
        if self.death_spin_duration_s > 0.0:
            ramp = min(max(elapsed_s, 0.0) / self.death_spin_duration_s, 1.0)
        else:
            ramp = 1.0
        omega_radps = self.death_max_tumble_rate_radps * np.sqrt(ramp)
        omega_radps *= TUMBLE_RATE_FACTORS
        self.scalar_thrust_n = 0.0
        self.pqr = self._tumble_axis * omega_radps

        # Same physics + render update as move(), without set_inputs.
        self.move_ship_physics()
        self.node.setPos(*self.position)
        self.node.setQuat(Quat(*self.orientation))

    def take_hit(self, damage: float, normal_world_vector: Vec3 | np.ndarray):
        """
        Take damage from hits and jolt from the impact
        # TODO move force calculations to collisions.py
        # TODO allow energy (ion) damage when we add energy management

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        """
        self.apply_damage(damage=damage, damage_type="physical")

        # Apply momentum change
        hit_force_world_n = (
            -WEAPON_DAMAGE_TO_FORCE_FACTOR * damage * np.array([*normal_world_vector])
        )
        self.impact_force_n += hit_force_world_n
        # Remove this additional force later on
        self.game.delayed_methods.do_method_later(
            delay_s=DAMAGE_FORCE_APPLICATION_DURATION_S,
            name="remove_hit_force",
            method=self.remove_hit_force,
            extra_args=[hit_force_world_n],
        )

    def push(
        self,
        damage: float,
        velocity_correction: np.ndarray,
        position_correction: np.ndarray,
    ):
        """
        Push self due to collision with a solid object

        We don't use collision forces because they are too stiff.
        Instead, we use impulse and position correction

        The corrections are stored and applied (then reset) by the next
        :meth:`move_ship_physics`.

        :param damage: The damage to take
        :param velocity_correction: The velocity correction to apply
        :param position_correction: The position correction to apply
        """
        self.apply_damage(damage=damage, damage_type="physical")
        self.velocity_correction = velocity_correction
        self.position_correction = position_correction

    def adjust_engine_pitch(self, throttle: float):
        """
        Updates the pitch of the engine noise

        :param throttle: The throttle value of the ship [0, 1], above 1 for boost
        """
        if self.sound is None:
            return
        pitch_multiplier = 1 + 0.15 * min(throttle - 0.5, 0.8)
        pitch_multiplier *= self._engine_sputter_factor()
        self.sound.setPlayRate(pitch_multiplier)

    def _engine_sputter_factor(self) -> float:
        """
        A play-rate multiplier that cuts the player's interior engine in sync with
        the cockpit's random damage stutters (see
        :class:`~space_flight.fx.cockpit_fx.CockpitFX`): 1.0 when healthy or
        between events, dipping to ``1 - ENGINE_SPUTTER_MAX_DEPTH`` at a full jolt.

        Reads the same shared stutter envelope the camera jolt uses, so the engine
        cut and the cockpit shake land together. Only the player carries a
        ``cockpit_fx``, so bots (and headless) are unaffected.

        :return: A multiplier in (0, 1], applied on top of the throttle pitch
        """
        cockpit_fx = getattr(self.parent, "cockpit_fx", None)
        if cockpit_fx is None:
            return 1.0
        return 1.0 - ENGINE_SPUTTER_MAX_DEPTH * cockpit_fx.sputter_intensity()

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the ship
        Ship-type dependent

        :param damage: The amount of damage to apply
        :param damage_type: the type of damage to apply (physical, energy)
        """
        raise NotImplementedError

    def apply_external_force(self, force_world_n: np.ndarray):
        """
        Accumulate a transient world-frame force applied by another actor for the
        current frame (e.g. a tractor beam's drag and attraction).

        The force is consumed and cleared by :meth:`compute_derivatives`, so it
        must be re-applied each frame it should act; several sources add up.

        :param force_world_n: The force to apply this frame, in world coordinates
        """
        self.external_force_n = self.external_force_n + np.asarray(
            force_world_n, dtype=float
        )

    def remove_hit_force(self, hit_force_world_n: np.ndarray):
        """
        A method to remove a hit force from the impact forces
        once its application time has expired

        :param hit_force_world_n: The force to remove
        """
        self.impact_force_n -= hit_force_world_n

    def ship_handle_health(self):
        """
        Monitors the ships health and shield
        Ship-type dependent
        """
        raise NotImplementedError

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            super().clean()
            # Remove ship from its formation if applicable
            if self.formation is not None:
                self.formation.remove_ship(self.id)
                self.formation = None
            # Remove collision nodes
            self.collision_sphere_np.setPythonTag("owner", None)
            self.collision_sphere_np.remove_node()
            self.collision_sphere_np = None
            # Remove sound
            if self.sound is not None:
                self.sound_pool.release_sound(self.sound)
                self.game.app.sfx.audio3d.detachSound(self.sound)
                self.sound = None
            # Remove model
            self.model.clean()
            self.model = None
            # Drop the damage/death trail (owns no scene nodes; its per-frame task
            # is removed with the rest by clear_tasks)
            if self.damage_fx is not None:
                self.damage_fx.clean()
                self.damage_fx = None
            # Remove node
            self.node.remove_node()
            self.node = None
            # Remove upward references
            self.is_dead = True
            self.parent = None
            self.game = None
            self.is_clean = True

    def __del__(self):
        if DEBUG_DELETION:
            # TODO: apparently this never happens. There must be some references hidden
            # somewhere but I can't find them. Bot deletes fine, though. Children,
            # including panda3d objects are properly deleted, I believe, so this
            # should not have too much of a memory impact. It's still enraging, though..
            LOGGER.info(self.game.app.taskMgr.getAllTasks)
            LOGGER.info("Deleted ship")
