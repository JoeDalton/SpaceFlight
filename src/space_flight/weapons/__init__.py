"""
Generic weapon / munition base classes.

Ship weapons (the :class:`~space_flight.weapons.laser_cannon.LaserCannon`, the
:class:`~space_flight.weapons.ordnance_launcher.OrdnanceLauncher`) share
:class:`Weapon`: the emitter references and a reload (rate) limit.

Laser shots are *munitions*: short-lived objects that carry damage + world
velocity, show a visual node, drag a child collider, coast in a straight line,
register in game.game_objects and self-clean at the end of their life.
:class:`Munition` is a template: subclasses fill in _build_visual and
_attach_collider (and optionally _clean_extra) and inherit the whole lifecycle.

Ordnance (bombs, rockets, missiles, flares) are flown pawns instead (see
:mod:`space_flight.actors.ordnance`), but expose the same interface to the
collision handlers: origin_ship / origin_ship_id / power / speed / color,
on_impact() and impact_position().
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

import numpy as np
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import LVector3, NodePath, Point3, TransparencyAttrib

from space_flight import DEBUG_DELETION

if TYPE_CHECKING:
    from space_flight.actors.capital_ship.turret import Turret
    from space_flight.actors.fighter import Fighter
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


def build_ordnance_sphere(
    game: FlightState,
    parent_node: NodePath,
    radius_m: float,
    color: tuple[float, float, float, float],
) -> NodePath:
    """
    Placeholder ordnance visual: a flat-shaded coloured sphere, semi-transparent
    when the colour's alpha is below 1.

    :param game: The game/flight state
    :param parent_node: The node to attach the sphere to
    :param radius_m: The sphere's radius
    :param color: Its RGBA colour
    :return: The sphere's node path
    """
    sphere = game.app.loader.loadModel("models/misc/sphere")
    sphere.reparent_to(parent_node)
    sphere.set_scale(radius_m)
    sphere.set_light_off()
    sphere.set_color(*color)
    if color[3] < 1.0:
        sphere.set_transparency(TransparencyAttrib.MAlpha)
        sphere.set_depth_write(False)
    return sphere


class Weapon:
    """
    Base class for ship weapons that spawn munitions.

    Holds the emitter (parent / parent_node), a shared reload gate so a
    weapon cannot fire faster than fire_delay allows, and the common
    munition-construction call. Subclasses implement the trigger itself
    (fire / launch) and pass the munition class they spawn.
    """

    def __init__(
        self,
        game: FlightState,
        parent: Fighter | Turret,
        parent_node: NodePath | None = None,
        fire_delay: float = 0.0,
        damage_multiplier: float = 1.0,
    ):
        """
        :param game: The game/flight state
        :param parent: The emitter pawn (a ship or a mounted subsystem)
        :param parent_node: Node the munitions are emitted from; defaults to the
            parent's node
        :param fire_delay: Minimum time between shots, in seconds (0 = unlimited)
        :param damage_multiplier: Scales the damage of every munition it emits
            (a gameplay setting)
        """
        self.parent = parent
        self.game = game
        self.parent_node = parent.node if parent_node is None else parent_node

        # Reload gate. last_fire_time starts "now" so a freshly built weapon
        # observes one full reload before its first shot.
        self.fire_delay = fire_delay
        self.last_fire_time = self.game.game_time.get_current_time()
        self.damage_multiplier = damage_multiplier

    def _ready_to_fire(self) -> bool:
        """
        Check-and-consume the reload gate.

        :return: True if fire_delay has elapsed since the last shot -- and, in
            that case, stamps the current time as the new last_fire_time so the
            caller can proceed to fire. False (without stamping) while reloading.
        """
        current_time = self.game.game_time.get_current_time()
        if current_time - self.last_fire_time < self.fire_delay:
            return False
        self.last_fire_time = current_time
        return True

    def restart_reload(self):
        """
        Start a full reload now, as if the weapon had just fired (e.g. when the
        pilot switches to it).
        """
        self.last_fire_time = self.game.game_time.get_current_time()

    def _spawn_munition(
        self,
        munition_class: type[Munition],
        start_position: Point3,
        speed: np.ndarray,
        power: float,
        life_time_s: float,
        **munition_kwargs: Any,
    ):
        """
        Construct a munition with the common emitter/damage parameters.

        :param munition_class: The :class:`Munition` subclass to spawn (passed by
            the caller so test doubles can patch it in the caller's module)
        :param start_position: World-space emission point
        :param speed: World-space velocity
        :param power: Damage dealt on impact, before the damage multiplier
        :param life_time_s: How long the munition lives
        :param munition_kwargs: Extra per-weapon visual parameters (e.g. the laser
            texture / light colour)
        """
        munition_class(
            game=self.game,
            origin_ship_id=self.parent.id,
            origin_ship=self.parent,
            power=power * self.damage_multiplier,
            life_time_s=life_time_s,
            speed=speed,
            start_position=start_position,
            **munition_kwargs,
        )

    def clean(self):
        """
        Drop the upward references so the weapon can be garbage-collected.
        """
        self.parent = None
        self.parent_node = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned %s", type(self).__name__)

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted %s", type(self).__name__)


class Munition:
    """
    Base class for weapon projectiles.

    Owns the whole projectile lifecycle -- identity, damage, emitter, world
    velocity, a straight-line coast for its lifetime, game.game_objects
    registration and a timed self-clean -- and exposes the interface the collision
    handlers read (origin_ship / origin_ship_id / power / speed /
    shot). Subclasses supply only the visual and the collider.
    """

    def __init__(
        self,
        game: FlightState,
        origin_ship_id: uuid.UUID,
        power: float,
        life_time_s: float,
        speed: np.ndarray,
        start_position: Point3,
        origin_ship: Fighter | Turret | None = None,
    ):
        """
        :param game: The game/flight state
        :param origin_ship_id: Id of the firing ship (spares it from its own fire)
        :param power: Damage dealt on impact
        :param life_time_s: How long the munition lives before self-cleaning
        :param speed: World-space velocity
        :param start_position: World-space emission point
        :param origin_ship: The emitter object itself; read by the damage handlers
            (via owners_share_vehicle) to spare the whole firing vehicle
        """
        self.game = game
        self.id = uuid.uuid4()
        self.power = power
        self.origin_ship_id = origin_ship_id
        self.origin_ship = origin_ship
        # World-space velocity, read by munition_into_shield to tell an inward
        # crossing (blocked) from an outward one (passes through).
        self.speed = np.asarray(speed, dtype=float)

        # Visual node (built by the subclass), placed and set coasting here.
        self.shot = self._build_visual(start_position)
        self.shot.set_pos(start_position)
        end_position = start_position + LVector3(*(self.speed * life_time_s))
        movement_interval = LerpPosInterval(self.shot, life_time_s, end_position)
        self.game.interval_manager.play_interval(movement_interval)

        # Collider (built by the subclass as a child of the visual, so removing the
        # visual removes the collider too).
        self.collider_np = self._attach_collider()

        # Register in temporary game objects and self-clean at end of life.
        self.game.game_objects[self.id] = self
        self.game.delayed_methods.do_method_later(
            delay_s=life_time_s,
            name=f"Clean{type(self).__name__}",
            method=self.clean,
        )

    def _build_visual(self, start_position: Point3) -> NodePath:
        """
        Build and return the visual node (reparented to the scene, oriented and
        textured), without setting its position -- the base places it. Subclasses
        may store extra render nodes (e.g. a light) on self for _clean_extra.
        """
        raise NotImplementedError

    def _attach_collider(self) -> NodePath:
        """
        Attach a collider as a child of self.shot and return its NodePath.
        """
        raise NotImplementedError

    def _clean_extra(self):
        """
        Subclass hook for tearing down extra render state (e.g. a light) before the
        shared teardown. Default: nothing.
        """

    def on_impact(self):
        """
        The munition hit something: remove its visual (and thus its collider). The
        timed clean still runs at the end of its life.
        """
        self.shot.removeNode()

    def impact_position(self) -> Point3:
        """
        :return: The munition's current position, in the game root's frame
        """
        return self.shot.getPos(self.game.root_node)

    def clean(self, remove_from_game_objects: bool = True):
        """
        Tear down the munition: extra render state, collider, visual node and the
        game.game_objects registration.

        :param remove_from_game_objects: Skip the registry pop during the final
            game cleanup, which iterates that registry itself.
        """
        self._clean_extra()
        try:
            self.collider_np.setPythonTag("owner", None)
        except AttributeError:
            pass
        self.collider_np = None
        try:
            self.shot.removeNode()
        except AttributeError:
            pass
        self.shot = None
        if remove_from_game_objects and self.game.game_objects is not None:
            try:
                self.game.game_objects.pop(self.id)
            except KeyError:
                pass
        self.game = None

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted %s", type(self).__name__)
