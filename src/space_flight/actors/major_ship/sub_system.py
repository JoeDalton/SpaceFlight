from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import NodePath, Vec3

from space_flight.actors.destructibles import Destructible
from space_flight.fx import spark_fx
from space_flight.fx.damage_fx import DamageFX
from space_flight.game.collisions import attach_collision_box, attach_collision_sphere
from space_flight.weapons import (
    ION,
    ION_CAPACITY_HEALTH_FRACTION,
    ION_DAMAGE_FACTOR,
    ION_DISABLE_DURATION_S,
    ION_LOAD_DECAY_RATE_PS,
    PHYSICAL,
)

if TYPE_CHECKING:
    from space_flight.actors.bot import Bot
    from space_flight.actors.ship import Ship
    from space_flight.game.flight_state import FlightState

# A standalone subsystem (whose parent is the ship it is bolted to, e.g. a shield
# generator) smokes at full intensity for this long before it explodes, since it
# cannot tumble. Bot-controlled subsystems (turrets, tractor beams) are reaped by
# their Bot and die immediately.
SUBSYSTEM_DEATH_SMOKE_DURATION_S = 0.6


class SubSystem(Destructible):
    """
    A generic destructible subsystem bolted onto a (capital) ship.

    Subsystems are :class:`Destructible` objects in their own right: they own
    their health and their own collision geometry, and they explode when their
    health is depleted. Ion hits cannot harm them, but disable them for a while
    once they have taken enough (see :meth:`apply_damage`): subclasses check
    :attr:`is_disabled` to stop working, and may react in
    :meth:`on_disabled` / :meth:`on_enabled`. The into-only "subsystem" collider
    never initiates
    collisions (a subsystem is a rigid part of its ship), it is only hit. Lasers
    hitting it damage it, and a ship ramming it is handled by
    ship_into_subsystem, which pushes the :attr:`mounted_on` ship (the subsystem
    cannot move) while the subsystem takes the damage.

    The collider's owner python-tag is the subsystem itself; the collision
    handlers read its :attr:`mounted_on` (through
    :func:`~space_flight.game.collisions.owners_share_vehicle`) so a subsystem
    never collides with the ship it is mounted on.

    :param game: The game/flight state
    :param parent: The subsystem's owner. Usually the ship it is on, but for a
        turret it is the controlling Bot (see :attr:`mounted_on`).
    :param mounted_on: The ship this subsystem is bolted onto. Defaults to
        parent (correct when the parent *is* the ship, e.g. shield
        generators); a turret passes the ship explicitly since its parent is a Bot
    :param relative_position: Mounting position relative to the ship node
    :param hit_box_radius_m: Radius of the subsystem's spherical collider
    :param half_extents_m: Half-sizes (x, y, z, ship axes) of a box collider
        instead of the sphere; hit_box_radius_m is then the box's bounding radius
    :param health: Initial (and maximum) health of the subsystem
    :param explosion_scale: Size of the subsystem's death explosion
    :param name: Node and display name of the subsystem
    :param ion_capacity: Ion damage it takes (at once, or faster than it bleeds
        off) to be disabled; ION_CAPACITY_HEALTH_FRACTION of its health by
        default
    """

    #: Whether ion hits have knocked it out for now (see apply_damage)
    is_disabled = False

    def __init__(
        self,
        game: FlightState,
        parent: Ship | Bot,
        mounted_on: Ship | None = None,
        relative_position: np.ndarray = np.zeros(3),
        hit_box_radius_m: float = 5.0,
        health: float = 1000.0,
        explosion_scale: float = 10.0,
        name: str = "subsystem",
        half_extents_m: np.ndarray | None = None,
        ion_capacity: float | None = None,
    ):
        super().__init__(game=game)
        self.parent = parent
        self.mounted_on = mounted_on if mounted_on is not None else parent
        self.name = name
        self.team = self.mounted_on.team
        # Actor category, so target filters can single subsystems out.
        self.category = "sub_system"
        # A mounted subsystem is as manoeuverable as the ship it rides
        self.mobility = getattr(self.mounted_on, "mobility", 0.0)
        self.is_dead = False
        self.is_clean = False

        # Setup health
        self.max_health = health
        self.health = self.max_health

        # Ion load and disabling (see apply_damage)
        self.ion_capacity = (
            ION_CAPACITY_HEALTH_FRACTION * health
            if ion_capacity is None
            else ion_capacity
        )
        self.ion_load = 0.0
        self.disabled_until_s = 0.0
        self.ion_crackle = spark_fx.IonCrackle()

        # Create a dummy node mounted on the ship, at the mounting point
        self.node = NodePath(f"{name}_node")
        self.node.reparentTo(self.mounted_on.node)
        self.node.set_pos(*relative_position)
        self.position = np.array(self.node.getPos(self.game.root_node))

        # Into-only collision geometry (see class docstring): a sphere, or a box
        # (whose bounding radius stands for its size wherever a radius is read)
        if half_extents_m is not None:
            self.half_extents_m = np.asarray(half_extents_m, dtype=float)
            self.hit_box_radius_m = float(np.linalg.norm(self.half_extents_m))
            self.collision_np = attach_collision_box(
                game=self.game,
                name="subsystem",
                center=[0.0, 0.0, 0.0],
                half_extents=self.half_extents_m,
                collider_type="subsystem",
                parent_node=self.node,
                parent_object=self,
            )
        else:
            self.half_extents_m = None
            self.hit_box_radius_m = hit_box_radius_m
            self.collision_np = attach_collision_sphere(
                game=self.game,
                name="subsystem",
                radius=self.hit_box_radius_m,
                collider_type="subsystem",
                parent_node=self.node,
                parent_object=self,
            )

        # Set explosion size for the death animation
        self.explosion_scale = explosion_scale

        # Smoke/fire trail as the subsystem is worn down, and through its death
        # (see SUBSYSTEM_DEATH_SMOKE_DURATION_S)
        self.damage_fx = DamageFX(game=self.game, owner=self)
        self.add_task(method=self.damage_fx.update)
        if self.parent is self.mounted_on:
            self.death_duration_s = SUBSYSTEM_DEATH_SMOKE_DURATION_S

        # We are our own Destructible, so we monitor our own health each frame
        self.add_task(method=self.handle_health)
        self.add_task(method=self.update_ion)

        # Register as a targetable actor, so bots and the player can lock onto us
        self.game.interactions.add_actor(self)

    @property
    def speed(self) -> np.ndarray:
        """
        The subsystem's velocity: it is bolted to its ship, so it *is* the host
        ship's velocity, read live rather than mirrored.

        Keeps attackers' lead-pursuit solutions correct against a subsystem on a
        moving ship; the death explosion and a turret's shots also pick up the
        host's motion through it.

        :return: The host ship's velocity, or zeros once detached (cleaned)
        """
        if getattr(self, "mounted_on", None) is None:
            return np.zeros(3)
        return np.asarray(getattr(self.mounted_on, "speed", np.zeros(3)), dtype=float)

    @property
    def in_hyperspace(self) -> bool:
        """
        Whether the subsystem's ship is in a hyperspace transit: it then rides
        along, out of every interaction too.

        :return: The host ship's flag, or False once detached (cleaned)
        """
        if getattr(self, "mounted_on", None) is None:
            return False
        return getattr(self.mounted_on, "in_hyperspace", False)

    def _attach_placeholder_model(
        self,
        model_path: str,
        color: tuple[float, float, float],
        scale: tuple[float, ...],
        position: tuple[float, float, float] | None = None,
    ):
        """
        Visible geometry: a placeholder shape matching the collider, so the
        subsystem can be seen and targeted. Flat-shaded like the waypoint markers
        (see ui/player_waypoints.py) to be visible under any lighting. Sets
        :attr:`model`.

        TODO: swap for proper per-subsystem 3D models.

        :param model_path: The placeholder model
        :param color: Its flat RGB colour
        :param scale: Its scale (one factor, or one per axis)
        :param position: Its position on the subsystem node, if not the origin
        """
        self.model = self.game.app.loader.loadModel(model_path)
        self.model.setTextureOff(1)
        self.model.setColor(*color, 1.0)
        self.model.setScale(*scale)
        if position is not None:
            self.model.setPos(*position)
        self.model.reparentTo(self.node)
        self.model.setShaderOff()
        self.model.setLightOff()

    def take_hit(
        self,
        damage: float,
        normal_world_vector: Vec3 | np.ndarray,
        damage_type: str = PHYSICAL,
    ):
        """
        Takes damage from a hit.

        Subsystems are rigidly attached to their ship, so the impact normal is
        not used to jolt them (unlike ships).

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        :param damage_type: PHYSICAL or ION
        """
        self.apply_damage(damage=damage, damage_type=damage_type)

    def apply_damage(self, damage: float, damage_type: str):
        """
        Applies damage to the subsystem.

        :param damage: The amount of damage to apply
        :param damage_type: The type of damage to apply (PHYSICAL, ION)
        """
        if damage_type == PHYSICAL:
            self.health -= damage
        elif damage_type == ION:
            self._take_ion_load(damage * ION_DAMAGE_FACTOR)
        else:
            raise NotImplementedError

    def _take_ion_load(self, load: float):
        """
        Load the subsystem up with ion energy (it cannot harm its health): once
        the load reaches the ion capacity, the subsystem is disabled for
        ION_DISABLE_DURATION_S from now (on top of any time left), and the load
        starts over.

        :param load: The ion energy taken
        """
        self.ion_load += load
        if self.ion_load < self.ion_capacity:
            return
        self.ion_load = 0.0
        self.disabled_until_s = (
            self.game.game_time.get_current_time() + ION_DISABLE_DURATION_S
        )
        if not self.is_disabled:
            self.is_disabled = True
            self.on_disabled()

    def update_ion(self):
        """
        Per frame: bleed the ion load off, crackle while disabled, and bring the
        subsystem back online once its disabling is over.
        """
        dt = self.game.game_time.get_time_step()
        now = self.game.game_time.get_current_time()
        self.ion_load = max(
            self.ion_load - ION_LOAD_DECAY_RATE_PS * self.ion_capacity * dt, 0.0
        )
        if not self.is_disabled:
            return
        if now >= self.disabled_until_s:
            self.is_disabled = False
            self.on_enabled()
            return
        self.ion_crackle.update(
            game=self.game,
            position=self.position,
            radius_m=self.hit_box_radius_m,
            velocity=self.speed,
        )

    def on_disabled(self):
        """
        Hook: the subsystem was just disabled by ion hits. Subclasses stop what
        they were doing; nothing in the base.
        """

    def on_enabled(self):
        """
        Hook: the subsystem just came back online. Nothing in the base.
        """

    def handle_health(self):
        """
        Monitors the subsystem's health, clamping it to its maximum and refreshing
        its world position for the death explosion.

        Should the ship we are mounted on be gone, bring ourselves down so we are
        cleaned up.
        """
        if self.mounted_on is None or self.mounted_on.is_dead:
            self.health = 0.0
            return
        self.health = min(self.health, self.max_health)
        self.position = np.array(self.node.getPos(self.game.root_node))

    def get_health(self) -> float:
        """
        Finds the health of the subsystem.

        :return: The current health of the subsystem
        """
        return self.health

    @property
    def shield_level(self) -> float:
        """
        Subsystems carry no shield of their own.

        :return: 0.0
        """
        return 0.0

    def play_death(self):
        """
        Plays the subsystem's death animation: an explosion at its last location.
        """
        if self.game is None:
            return
        base_velocity = (
            self.mounted_on.speed if self.mounted_on is not None else np.zeros(3)
        )
        self.game.fire_smoke_pool.burst(
            position=self.position,
            scale=self.explosion_scale,
            base_velocity=base_velocity,
        )

    def clean(self):
        """
        Cleans references before deletion so the subsystem can be garbage collected.
        """
        if not self.is_clean:
            # Stop our per-frame tasks first, so nothing touches removed nodes
            self.clear_tasks()
            # Remove ourselves from the targetable actors
            with contextlib.suppress(KeyError, AttributeError):
                self.game.interactions.remove_actor(self)
            # Remove collision node
            self.collision_np.setPythonTag("owner", None)
            self.collision_np.remove_node()
            self.collision_np = None
            # Drop the damage/death trail (owns no scene nodes)
            if getattr(self, "damage_fx", None) is not None:
                self.damage_fx.clean()
                self.damage_fx = None
            # Remove visible geometry, if a subclass attached one
            if getattr(self, "model", None) is not None:
                self.model.remove_node()
                self.model = None
            # Remove node
            self.node.remove_node()
            self.node = None
            # Remove upward references
            self.is_dead = True
            self.parent = None
            self.mounted_on = None
            self.game = None
            self.is_clean = True
