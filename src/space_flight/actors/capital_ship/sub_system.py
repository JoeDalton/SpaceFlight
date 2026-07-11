import logging

import numpy as np
from panda3d.core import NodePath

from space_flight.actors.destructibles import Destructible
from space_flight.game.collisions import attach_collision_sphere

LOGGER = logging.getLogger()


class SubSystem(Destructible):
    """
    A generic destructible subsystem bolted onto a (capital) ship.

    Subsystems are :class:`Destructible` objects in their own right: they own
    their health and their own collision geometry, and they explode when their
    health is depleted. The collider uses the ``"subsystem"`` name and type: like
    terrain it never initiates collisions (a subsystem is a rigid part of its
    ship), it is only hit. Lasers hitting it damage it, and a ship ramming it is
    handled by ``ship_into_subsystem``, which pushes the subsystem's *parent* ship
    (not the subsystem, which cannot move) while the subsystem takes the damage.

    The collider's ``owner`` python-tag is set to the subsystem itself, and
    :attr:`mounted_on` points at the parent ship. A subsystem therefore never
    collides with the ship it is mounted on: the collision handlers skip
    same-vehicle pairs through
    :func:`~space_flight.game.collisions.owners_share_vehicle`, which reads
    ``mounted_on``.

    :param game: The game/flight state
    :param parent: The subsystem's owner. Usually the ship it is on, but for a
        turret it is the controlling Bot (see :attr:`mounted_on`).
    :param mounted_on: The ship this subsystem is bolted onto. Defaults to
        ``parent`` (correct when the parent *is* the ship, e.g. shield
        generators); a turret passes the ship explicitly since its parent is a Bot
    :param relative_position: Mounting position relative to the ship node
    :param hit_box_radius_m: Radius of the subsystem's spherical collider
    :param health: Initial (and maximum) health of the subsystem
    :param explosion_scale: Size of the subsystem's death explosion
    :param name: Node and display name of the subsystem
    """

    def __init__(
        self,
        game,
        parent,
        mounted_on=None,
        relative_position: np.ndarray = np.zeros(3),
        hit_box_radius_m: float = 5.0,
        health: float = 1000.0,
        explosion_scale: float = 10.0,
        name: str = "subsystem",
    ):
        super().__init__(game=game)
        self.parent = parent
        # The ship this subsystem is bolted onto (its mount). Defaults to parent
        # when the parent is the ship (shield generators); a turret's parent is
        # its Bot, so the ship is passed explicitly. Read by the collision
        # handlers (owners_share_vehicle / ship_into_subsystem) to spare the
        # parent ship and route pushback to it, and used below for the mount node,
        # team, health and death.
        self.mounted_on = mounted_on if mounted_on is not None else parent
        self.name = name
        self.team = self.mounted_on.team
        # Actor category, so target filters can single subsystems out.
        self.category = "sub_system"
        self.is_dead = False
        self.is_clean = False

        # Setup health
        self.max_health = health
        self.health = self.max_health

        # Create a dummy node mounted on the ship, at the mounting point
        self.node = NodePath(f"{name}_node")
        self.node.reparentTo(self.mounted_on.node)
        self.node.set_pos(*relative_position)
        self.position = np.array(self.node.getPos(self.game.root_node))

        # Collision geometry.
        # A subsystem is a rigid, destructible chunk of its parent ship, hence the
        # into-only "subsystem" collider: lasers and ships hit it, but it never
        # pushes anything itself. The owner python-tag (set by
        # attach_collision_sphere) lets the handlers spare the parent ship (via
        # owners_share_vehicle) and route pushback to the parent.
        self.hit_box_radius_m = hit_box_radius_m
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="subsystem",
            radius=self.hit_box_radius_m,
            collider_type="subsystem",
            parent_node=self.node,
            parent_object=self,
        )

        # Set explosion size for the death animation
        self.explosion_scale = explosion_scale

        # We are our own Destructible, so we monitor our own health each frame
        self.add_task(method=self.handle_health)

        # Register as a targetable actor, so bots and the player can lock onto us
        self.game.interactions.add_actor(self)

    def take_hit(self, damage: float, normal_world_vector: np.ndarray):
        """
        Takes damage from a hit.

        Subsystems are rigidly attached to their ship, so the impact normal is
        not used to jolt them (unlike ships).

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        """
        self.apply_damage(damage=damage, damage_type="physical")

    def apply_damage(self, damage: float, damage_type: str):
        """
        Applies damage to the subsystem.

        :param damage: The amount of damage to apply
        :param damage_type: The type of damage to apply (physical, energy)
        """
        if damage_type == "physical":
            self.health -= damage
        else:
            raise NotImplementedError

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

    def play_death(self):
        """
        Plays the subsystem's death animation: an explosion at its last location.
        """
        if self.game is None:
            return
        base_velocity = (
            self.mounted_on.speed if self.mounted_on is not None else np.zeros(3)
        )
        self.game.explosion_fx_pool.spawn(
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
            try:
                self.game.interactions.remove_actor(self)
            except (KeyError, AttributeError):
                pass
            # Remove collision node
            self.collision_sphere_np.setPythonTag("owner", None)
            self.collision_sphere_np.remove_node()
            self.collision_sphere_np = None
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
