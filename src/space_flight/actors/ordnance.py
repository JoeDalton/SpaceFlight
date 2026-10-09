"""
Ordnance in flight: bombs, rockets, missiles and flares.

They all share the same code. An :class:`Ordnance` is a ship flying at a constant
speed (no engine, no aerodynamics), driven by an :class:`OrdnanceController`
for a limited life. The controller flies it straight, except for a guided
missile, which a navigator and a pilot steer toward its target -- piloted
exactly like a fighter, but without a tactician since it always engages the
target its launcher gave it (unless a flare decoys it).
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import NodePath, Point3, Vec3

from space_flight.actors.destructibles import Destructible
from space_flight.actors.ship import Ship
from space_flight.ai import Personality
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.missile.incoming_missile import IncomingMissile
from space_flight.ai.missile.missile_navigator import MissileNavigator
from space_flight.game.collisions import attach_collision_sphere
from space_flight.utils import magnitude, rotation_matrix_coefficients
from space_flight.weapons import build_ordnance_sphere

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState
    from space_flight.weapons.ordnance_launcher import OrdnanceLauncher

LOGGER = logging.getLogger()

# Ship parameters an ordnance does not use (or that only a missile sets, like its
# turn rates): neutral values making it an engine-less, drag-free body. Its
# motion is set by compute_derivatives instead.
ORDNANCE_SHIP_DEFAULTS = {
    "mass_kg": 1.0,
    "inputs_filter_time_s": 0.05,
    "max_thrust_n": 0.0,
    "brake_factor_nspm": 0.0,
    "max_pitch_rate_degps": 0.0,
    "max_yaw_rate_degps": 0.0,
    "max_roll_rate_degps": 0.0,
    "drag_coefficient": 0.0,
    "lift_coefficient_slope_pdeg": 0.0,
    "lateral_lift_coefficient_slope_pdeg": 0.0,
    "reference_surface_m2": 0.0,
    "health": 1.0,
}
# Flight commands (throttle, yaw, pitch, roll) of an unguided ordnance: no
# turning, and the throttle is unused at constant speed
COAST_COMMANDS = (0.0, 0.0, 0.0, 0.0)


class OrdnanceModel:
    """
    The placeholder render of an ordnance: a coloured sphere. Same interface as
    :class:`~space_flight.actors.ship_model.ShipModel`.
    """

    def __init__(
        self,
        game: FlightState,
        parent_node: NodePath,
        radius_m: float,
        color: tuple[float, float, float, float],
    ):
        self.game = game
        self.model = build_ordnance_sphere(
            game=game, parent_node=parent_node, radius_m=radius_m, color=color
        )

    def clean(self):
        """
        Cleans the OrdnanceModel object
        """
        self.model.removeNode()
        self.model = None
        self.game = None


class Ordnance(Ship):
    """
    An ordnance in flight. It keeps its launch speed for its whole life: its
    velocity is frozen in its body axes, so it flies straight unless it turns,
    which only a guided missile does (the velocity then turns with it).

    Toward the collision handlers it is a munition: it exposes origin_ship /
    origin_ship_id / power / speed / color, on_impact() and impact_position().
    """

    def __init__(
        self,
        game: FlightState,
        parent: OrdnanceController,
        ordnance_name: str,
        ordnance_conf: dict,
        origin_ship: Ship,
        ini_position: np.ndarray,
        ini_orientation: np.ndarray,
        ini_speed: np.ndarray,
        team: int = 0,
    ):
        """
        :param game: The game/flight state
        :param parent: The controller flying it
        :param ordnance_name: The ordnance name
        :param ordnance_conf: Its configuration (see OrdnanceLauncher)
        :param origin_ship: The ship that launched it, which it never hits
        :param ini_position: Its launch position
        :param ini_orientation: Its launch orientation (the launching ship's)
        :param ini_speed: Its launch velocity, kept for its whole life
        :param team: Its team (the launching ship's)
        """
        # Set before the Ship init, which already computes the first derivatives
        self._ordnance_conf = ordnance_conf
        self._launch_speed_mps = float(magnitude(ini_speed))
        r00, r01, r02, r10, r11, r12, r20, r21, r22 = rotation_matrix_coefficients(
            *ini_orientation
        )
        world_to_body = np.array(((r00, r10, r20), (r01, r11, r21), (r02, r12, r22)))
        self.velocity_body = world_to_body @ np.asarray(ini_speed, dtype=float)

        super().__init__(
            game=game,
            parent=parent,
            ship_type=ordnance_name,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            ini_speed=ini_speed,
            is_cockpit=False,
            team=team,
        )

        self.category = self.conf["type"]
        self.power = self.conf["damage"]
        self.damage_type = self.conf["damage_type"]
        # RGB tint of the player's cockpit flash when it hits them
        self.color = Vec3(*self.conf["color"][:3])
        self.origin_ship = origin_ship
        self.origin_ship_id = origin_ship.id

        # Flares only stop other ordnance, which hits them (see CollisionLayers)
        collider_type = "flare" if self.category == "flare" else "ordnance"
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name=collider_type,
            radius=self.conf["collision_radius_m"],
            collider_type=collider_type,
            parent_node=self.node,
            parent_object=self,
        )

    def _load_configuration(self, ship_type: str) -> dict:
        conf = dict(ORDNANCE_SHIP_DEFAULTS)
        conf.update(self._ordnance_conf)
        return conf

    def _compute_max_speed_mps(self) -> float:
        # Constant speed: the launch speed
        return self._launch_speed_mps

    def _build_damage_fx(self) -> None:
        # A spent ordnance simply disappears: no smoke or fire
        return None

    def _build_model(self, ship_type: str, is_cockpit: bool) -> OrdnanceModel:
        return OrdnanceModel(
            game=self.game,
            parent_node=self.node,
            radius_m=self.conf["visual_radius_m"],
            color=tuple(self.conf["color"]),
        )

    def _turn_rate_scale(self, throttle: float) -> float:
        # No engine, so the throttle does not limit the turn rates
        return 1.0

    def compute_derivatives(self):
        """
        Constant-speed flight: the velocity is the launch velocity, frozen in
        body axes, so it only changes direction when the ordnance turns (turn
        radius = speed / turn rate). No forces apply.
        """
        self.state_dot_previous = self.state_dot.copy()
        self._compute_attitude_derivative()
        vx, vy, vz = self.velocity_body
        speed = self.right * vx + self.forward * vy + self.up * vz
        # The integrated orientation drifts slightly off unit norm, which scales
        # the rotated velocity: hold the speed exactly
        speed_norm_mps = magnitude(speed)
        if speed_norm_mps > 0.0:
            speed *= self._launch_speed_mps / speed_norm_mps
        self.speed = speed
        self.state[7:10] = self.speed
        self.state_dot[0:3] = self.speed
        self.state_dot[7:10] = 0.0
        # Not pushed around by other actors (e.g. tractor beams)
        self.external_force_n = np.zeros(3)

    def on_impact(self):
        """
        The ordnance hit something: it is spent. Its collider stops reporting
        right away (other contacts of this frame are ignored) and its controller
        removes it at the next death handling.
        """
        if self.collision_sphere_np is not None:
            self.collision_sphere_np.setPythonTag("owner", None)
        self.health = 0.0

    def impact_position(self) -> Point3:
        """
        :return: The ordnance's current position, in the game root's frame
        """
        return Point3(*self.position)

    def apply_damage(self, damage: float, damage_type: str):
        """
        :param damage: The amount of damage to apply
        :param damage_type: the type of damage to apply (physical only for now)
        """
        if damage_type != "physical":
            raise NotImplementedError
        self.health -= damage

    def ship_handle_health(self):
        """
        Nothing to regenerate
        """


class OrdnanceController(Destructible):
    """
    Flies an ordnance for its limited life, then removes it -- as soon as it hits
    something, too. No explosion: it simply disappears.

    A guided missile with a target is steered by a :class:`MissileNavigator`
    (always engaging that target, unless a flare decoys it) and a
    :class:`FighterPilot`; every other
    ordnance, and a missile whose target is lost, flies straight on.

    While it homes on its target, a guided missile keeps the target's
    :class:`IncomingMissile` message up to date. A flare can decoy it: it then
    homes on the flare instead (see :meth:`offer_decoy`), silently.
    """

    def __init__(
        self,
        game: FlightState,
        launcher: OrdnanceLauncher,
        target_id: uuid.UUID | None = None,
    ):
        """
        :param game: The game/flight state
        :param launcher: The launcher firing it
        :param target_id: The target a missile pursues, None to fly straight
        """
        super().__init__(game=game)
        ship = launcher.parent
        self.name = f"{ship.parent.name}_{launcher.name}"
        self.record = False
        self.target_id = target_id
        self.life_time_s = launcher.conf["life_time_s"]
        self.launch_time_s = self.game.game_time.get_current_time()

        direction = launcher.launch_direction_vector()
        self.pawn = Ordnance(
            game=self.game,
            parent=self,
            ordnance_name=launcher.name,
            ordnance_conf=launcher.conf,
            origin_ship=ship,
            ini_position=ship.position + launcher.conf["launch_offset_m"] * direction,
            ini_orientation=np.array(ship.orientation, dtype=float),
            ini_speed=launcher.initial_velocity(),
            team=ship.team,
        )

        self.navigator = None
        self.pilot = None
        # The actor holding this missile's IncomingMissile message, if any
        self.warned_target = None
        # The flare this missile homes on instead of its target, once decoyed
        self.decoy_pawn = None
        if self.pawn.category == "missile" and target_id is not None:
            self.navigator = MissileNavigator(game=self.game, pawn=self.pawn)
            self.pilot = FighterPilot(
                game=self.game, pawn=self.pawn, personality=Personality.MISSILE_DEFAULT
            )
            # Piloted every frame: an ordnance is fast and short-lived
            self.pilot.sample_externally()

        self.add_task(method=self.move_ordnance_task)

    def move_ordnance_task(self):
        """
        Fly the ordnance (steering a guided missile), and spend it at the end
        of its life.
        """
        if self.is_dying or self.pawn.health <= 0.0:
            return
        elapsed_s = self.game.game_time.get_current_time() - self.launch_time_s
        if elapsed_s >= self.life_time_s:
            self.pawn.health = 0.0
            return

        commands = COAST_COMMANDS
        if self.navigator is not None:
            target = self._find_homing_target()
            if target is not None and self.decoy_pawn is None:
                self._warn(target)
            target_direction, desired_speed_mps = self.navigator.pursue(target)
            if np.any(target_direction):
                commands = self.pilot.pilot(
                    target_direction=target_direction,
                    desired_speed_mps=desired_speed_mps,
                )
            else:
                # Target lost: fly straight on from now on
                self._drop_guidance()
        throttle, yaw_rate, pitch_rate, roll_rate = commands
        self.pawn.move(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

    def _find_homing_target(self):
        """
        :return: The live actor the missile homes on: its decoy once decoyed,
            else its target. None once it is lost (dead or gone).
        """
        if self.decoy_pawn is None:
            return self.navigator.find_target(self.target_id)
        if self.decoy_pawn.is_dead or self.decoy_pawn.health <= 0.0:
            return None
        return self.decoy_pawn

    def _warn(self, target):
        """
        Send (or update) the "missile incoming" message to the target.

        :param target: The missile's live target
        """
        incoming_missiles = getattr(target, "incoming_missiles", None)
        if incoming_missiles is None:
            # Not a pawn (e.g. a subsystem): nobody to warn
            return
        incoming_missiles[self.id] = IncomingMissile.between(self, target)
        self.warned_target = target

    def _withdraw_warning(self):
        """Remove the "missile incoming" message from the target, if sent."""
        if self.warned_target is not None:
            self.warned_target.incoming_missiles.pop(self.id, None)
            self.warned_target = None

    def offer_decoy(self, flare: Ordnance) -> bool:
        """
        Offer a flare just dropped by the target to a guided missile. If the
        flare lures it (see _is_lured_by), the missile homes on the flare from
        now on (and flies straight on once the flare is spent), and its target is
        no longer warned.

        :param flare: The flare
        :return: True if the missile is now decoyed
        """
        if self.navigator is None or self.decoy_pawn is not None:
            return False
        if not self._is_lured_by(flare):
            return False
        self._withdraw_warning()
        self.decoy_pawn = flare
        LOGGER.info("%s decoyed by a flare", self.name)
        return True

    def _is_lured_by(self, flare: Ordnance) -> bool:
        """
        Whether a flare lures the missile: it must be close enough to the
        missile and within its seeker cone, and the missile then falls for it by
        chance (see MISSILE_DECOY_KEYS).

        :param flare: The flare
        :return: True if lured
        """
        conf = self.pawn.conf
        offset = np.asarray(flare.position, dtype=float) - self.pawn.position
        distance_m = magnitude(offset)
        if distance_m > conf["decoy_range_m"]:
            return False
        if distance_m > 0.0:
            cos_angle = np.dot(self.pawn.forward, offset) / distance_m
            if cos_angle < np.cos(np.deg2rad(conf["decoy_cone_angle_deg"])):
                return False
        return bool(np.random.random() < conf["decoy_chance"])

    def _drop_guidance(self):
        """Remove the navigator and pilot: the ordnance flies straight on."""
        self._withdraw_warning()
        if self.navigator is not None:
            self.navigator.clean()
            self.navigator = None
        if self.pilot is not None:
            self.pilot.clean()
            self.pilot = None
        self.target_id = None
        self.decoy_pawn = None

    def get_health(self) -> float:
        """
        :return: The ordnance's health: zero once spent
        """
        return self.pawn.health

    def play_death(self):
        """
        No explosion: a spent ordnance simply disappears.
        """

    def clean(self):
        """
        Remove every child
        """
        self._drop_guidance()
        self.pawn.clean()
        self.pawn = None
