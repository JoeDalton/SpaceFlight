import logging

import numpy as np
from panda3d.core import (
    BitMask32,
    CollisionHandlerEvent,
    CollisionNode,
    CollisionPlane,
    CollisionSegment,
    CollisionSphere,
    CollisionTraverser,
    CollisionTube,
    NodePath,
    Plane,
    Vec3,
)

from space_flight import DEBUG_COLLISION

SOLID_COLLISION_ELASTICITY = 0.3  # 0 = inelastic, 1 = elastic
POSITION_CORRECTION_RATIO = 0.1
PENETRATION_TOLERANCE_M = 0.1
COLLISION_DAMAGE_FACTOR = 0.05  # TODO configurable with difficulty

LOGGER = logging.getLogger()


class CollisionLayers:
    LASER = BitMask32.bit(0)
    SENSOR = BitMask32.bit(0)
    SHIELD = BitMask32.bit(1)
    DESTRUCTIBLE = BitMask32.bit(2)
    ENVIRONMENT = BitMask32.bit(3)

    # Lasers hit environment, destructibles and shields
    # Nothing hits them
    LASER_FROM = DESTRUCTIBLE | ENVIRONMENT | SHIELD
    LASER_INTO = BitMask32.allOff()

    # Same for sensors
    SENSOR_FROM = DESTRUCTIBLE | ENVIRONMENT
    SENSOR_INTO = BitMask32.allOff()

    # Destructibles hit environment and other destructibles.
    # They are only hit by lasers, sensors and other destructibles
    DESTRUCTIBLE_FROM = DESTRUCTIBLE | ENVIRONMENT
    DESTRUCTIBLE_INTO = LASER | SENSOR | DESTRUCTIBLE

    # Terrain cannot hit anything
    # It is hit by lasers, sensors and destructibles
    TERRAIN_FROM = BitMask32.allOff()
    TERRAIN_INTO = LASER | SENSOR | DESTRUCTIBLE

    # Subsystems are chunks bolted onto a ship (shield generators, turrets...).
    # Like terrain they never initiate collisions (they are rigid parts of their
    # parent ship), they are only hit. They carry their own name so that ship
    # collisions push the *parent* ship rather than the subsystem itself.
    SUBSYSTEM_FROM = BitMask32.allOff()
    SUBSYSTEM_INTO = LASER | SENSOR | DESTRUCTIBLE

    # A shield bubble is a barrier only lasers interact with: ships, sensors and
    # other destructibles fly straight through it (their from-masks lack SHIELD),
    # and it never initiates collisions itself. Whether a laser is blocked or
    # passes is decided in laser_into_shield by the crossing direction.
    SHIELD_FROM = BitMask32.allOff()
    SHIELD_INTO = SHIELD

    @staticmethod
    def define_collision_masks(collider_type: str) -> tuple[BitMask32]:
        """
        Defines the from and into values of collider given its type

        :param collider_type: The type of collider
        :return: Its from and into mask bits, and whether to add said collider to
            the collision handler
        """
        add_to_collision_handler = True
        if collider_type == "laser":
            from_mask_bit = CollisionLayers.LASER_FROM
            into_mask_bit = CollisionLayers.LASER_INTO
        elif collider_type == "sensor":
            from_mask_bit = CollisionLayers.SENSOR_FROM
            into_mask_bit = CollisionLayers.SENSOR_INTO
        elif collider_type == "destructible":
            from_mask_bit = CollisionLayers.DESTRUCTIBLE_FROM
            into_mask_bit = CollisionLayers.DESTRUCTIBLE_INTO
        elif collider_type == "terrain":
            from_mask_bit = CollisionLayers.TERRAIN_FROM
            into_mask_bit = CollisionLayers.TERRAIN_INTO
            add_to_collision_handler = False
        elif collider_type == "subsystem":
            from_mask_bit = CollisionLayers.SUBSYSTEM_FROM
            into_mask_bit = CollisionLayers.SUBSYSTEM_INTO
            add_to_collision_handler = False
        elif collider_type == "shield":
            from_mask_bit = CollisionLayers.SHIELD_FROM
            into_mask_bit = CollisionLayers.SHIELD_INTO
            add_to_collision_handler = False
        else:
            raise ValueError(f"Unknown collider type {collider_type}")
        return from_mask_bit, into_mask_bit, add_to_collision_handler


def owners_share_vehicle(owner_a, owner_b) -> bool:
    """
    Whether two collision owners belong to the same vehicle and, therefore,
    should not collide with one another.

    This is the "owner" mechanic that spares a ship from colliding with the
    subsystems (shield generators, ship-mounted turrets, etc.) bolted onto it.
    A mountable exposes ``mounted_on``: the ship it is attached to (``None`` when
    it stands alone). Reading the ``owner`` python-tags off a collision entry,
    two owners share a vehicle when:

    - both owners are the same object,
    - one is mounted on the other (its ``mounted_on`` is the other owner),
    - both are mounted on the same ship (siblings, e.g. two subsystems).

    :param owner_a: The owner python-tag of one collider
    :param owner_b: The owner python-tag of the other collider
    :return: True if both owners belong to the same vehicle
    """
    if owner_a is None or owner_b is None:
        return False
    if owner_a is owner_b:
        return True
    host_a = getattr(owner_a, "mounted_on", None)
    host_b = getattr(owner_b, "mounted_on", None)
    # One collider is bolted onto the other
    if host_a is owner_b or host_b is owner_a:
        return True
    # Both colliders are bolted onto the same ship (siblings)
    if host_a is not None and host_a is host_b:
        return True
    return False


class CollisionSystem:
    def __init__(self, game):
        self.game = game
        self.traverser = CollisionTraverser()
        if DEBUG_COLLISION:
            self.traverser.showCollisions(self.game.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
        self.handler.addAgainPattern("%fn-again-%in")

        # Weapon hit = one time events
        self.game.app.accept("laser-into-ship", self.laser_into_destructible)
        self.game.app.accept("laser-into-terrain", self.laser_into_terrain)
        self.game.app.accept("laser-into-turret", self.laser_into_destructible)
        self.game.app.accept("laser-into-subsystem", self.laser_into_destructible)
        self.game.app.accept("laser-into-shield", self.laser_into_shield)
        # Collision physics = detected at each frame
        self.game.app.accept("ship-into-ship", self.ship_into_ship)
        self.game.app.accept("ship-again-ship", self.ship_again_ship)
        self.game.app.accept("ship-into-terrain", self.ship_into_terrain)
        self.game.app.accept("ship-again-terrain", self.ship_again_terrain)
        self.game.app.accept("ship-into-turret", self.ship_into_massive_actor)
        self.game.app.accept("ship-again-turret", self.ship_again_massive_actor)
        self.game.app.accept("ship-into-subsystem", self.ship_into_subsystem)
        self.game.app.accept("ship-again-subsystem", self.ship_again_subsystem)
        # Collision sensors = detected at each frame
        self.game.app.accept("sensor-into-ship", self.sensor_into_obstacle)
        self.game.app.accept("sensor-again-ship", self.sensor_into_obstacle)
        self.game.app.accept("sensor-into-terrain", self.sensor_into_obstacle)
        self.game.app.accept("sensor-again-terrain", self.sensor_into_obstacle)
        self.game.app.accept("sensor-into-turret", self.sensor_into_obstacle)
        self.game.app.accept("sensor-again-turret", self.sensor_into_obstacle)
        self.game.app.accept("sensor-into-subsystem", self.sensor_into_obstacle)
        self.game.app.accept("sensor-again-subsystem", self.sensor_into_obstacle)

    def update_collisions(self):
        """
        Computes collisions via panda3d internal methods
        it triggers the "%fn-into-%in" events
        """
        self.traverser.traverse(self.game.app.render)

    def laser_into_destructible(self, entry):
        """
        Handles the case where a laser hits a destructible object:
        Damages the destructible object and remove the laser.

        :param entry: Panda3d's description of the collision
        """
        laser = entry.from_node_path.python_tags["owner"]
        destructible = entry.into_node_path.python_tags["owner"]

        if laser is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "laser juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return
        if destructible is None:
            if DEBUG_COLLISION:
                LOGGER.info("destructible being removed while it hits. Ignoring.")
            return

        # Check if the laser as encountered its own emitter => no "real" collision
        try:
            destructible_id = destructible.id
        except AttributeError:
            destructible_id = ""
        if laser.origin_ship_id == destructible_id:
            return
        # A laser never hits the vehicle it was fired from: not the emitter's
        # ship, nor a sibling subsystem (so a ship-mounted turret cannot shoot its
        # own hull, generators or other turrets).
        if owners_share_vehicle(laser.origin_ship, destructible):
            return

        if DEBUG_COLLISION:
            LOGGER.info("laser into destructible")

        # Apply damage to the destructible object
        normal = entry.getSurfaceNormal(self.game.root_node)
        # Normalize the normal vector because it can have a non-unit length if a parent
        # object was scaled. It's dumb, but it is what it is...
        if not normal.almostEqual(Vec3(0, 0, 0)):
            normal.normalize()
        destructible.take_hit(damage=laser.power, normal_world_vector=normal)

        # Delete laser
        laser.shot.removeNode()

        # Apply hit effect depending on player or bot
        if destructible_id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            self.game.player.play_impact_sound(
                relative_hit_point=relative_hit_point, kind="laser"
            )
        else:
            # TODO: Mute bots shooting on bots ?
            # hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            # TODO: Add a hit sprite
            self.game.app.sfx.distant_impact_hit(
                game=self.game,
                player_ship_pos=self.game.player.pawn.position,
                hit_pos=entry.into_node_path.parent.getPos(),
                impact_type="target",
            )

    def laser_into_terrain(self, entry):
        """
        Handles the case where a laser hits a terrain object:
        Removes the laser.

        TODO: Add a hit sprite

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("laser into terrain")
        laser = entry.from_node_path.python_tags["owner"]

        if laser is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "laser juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return

        self.game.app.sfx.distant_impact_hit(
            game=self.game,
            player_ship_pos=self.game.player.pawn.position,
            hit_pos=entry.into_node_path.parent.getPos(),
            impact_type="terrain",
        )

        # Delete laser
        laser.shot.removeNode()

    def laser_into_shield(self, entry):
        """
        Handle a laser crossing a shield bubble.

        A laser fired from *outside* the shield impacts it (and is absorbed); a
        laser fired from *inside* passes straight through, so a ship sheltering
        in its own bubble can still shoot out. The two are told apart by the sign
        of the laser's velocity dotted with the shield's outward surface normal:

        - crossing inward (dot < 0) -> the laser came from outside -> blocked,
        - anything else (dot >= 0): a laser exiting, a grazing contact, or the
          degenerate zero normal panda3d returns for a segment that started
          inside the solid -> it passes through.

        See trials/shield_normal_test.py for the experiment behind this rule.

        :param entry: Panda3d's description of the collision
        """
        laser = entry.from_node_path.python_tags["owner"]
        shield = entry.into_node_path.python_tags["owner"]

        if laser is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "laser juuuuust out of range and being removed while it hits. "
                    "Ignoring."
                )
            return
        if shield is None:
            if DEBUG_COLLISION:
                LOGGER.info("shield being removed while it is hit. Ignoring.")
            return

        # A turret sitting inside its ship's bubble must not hit that bubble: the
        # crossing-direction rule below already lets a shot fired from inside pass,
        # but skip the emitter's own vehicle outright to be unambiguous.
        if owners_share_vehicle(laser.origin_ship, shield):
            return

        # A downed (disabled) shield stops nothing
        if not shield.is_enabled:
            return

        # Block only lasers crossing inward (see docstring)
        normal = entry.getSurfaceNormal(self.game.root_node)
        # Normalize: a scaled parent can give a non-unit normal.
        if not normal.almostEqual(Vec3(0, 0, 0)):
            normal.normalize()
        if np.dot(laser.speed, normal) >= 0.0:
            return  # exiting or originating inside => pass through

        if DEBUG_COLLISION:
            LOGGER.info("laser into shield")

        # The shield absorbs the hit. Pass the world-space impact point so the
        # bubble can flash where the laser struck.
        hit_point = entry.getSurfacePoint(self.game.root_node)
        shield.take_hit(
            damage=laser.power,
            normal_world_vector=normal,
            hit_world_point=hit_point,
        )

        # Delete laser
        laser.shot.removeNode()

        # Impact feedback
        self.game.app.sfx.distant_impact_hit(
            game=self.game,
            player_ship_pos=self.game.player.pawn.position,
            hit_pos=entry.into_node_path.parent.getPos(),
            impact_type="target",
        )

    def ship_into_terrain(self, entry):
        """
        Handles the case where a ship hits immobile terrain.
        If ship_from is the player, plays a crash sfx
        In any case, calls ship_into_terrain_pushback

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        terrain_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. " "Ignoring.")
            return
        if terrain_into is None:
            if DEBUG_COLLISION:
                LOGGER.info("terrain_into being removed while it hits. " "Ignoring.")
            return

        if DEBUG_COLLISION:
            LOGGER.info("ship into terrain")
            LOGGER.info(f"ship from : {ship_from.id}")

        self.ship_into_terrain_pushback(entry)

        # Play SFX for player only
        if ship_from.id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getFromNodePath())
            self.game.app.sfx.player_crash(
                game=self.game, relative_hit_point=relative_hit_point, in_terrain=True
            )

    def ship_again_terrain(self, entry):
        """
        Handles the case where a ship hits immobile terrain, and it already has
        at the last frame : calls ship_into_terrain_pushback

        :param entry: Panda3d's description of the collision
        """
        self.ship_into_terrain_pushback(entry)

    def ship_into_terrain_pushback(self, entry):
        """
        Handle the case where a ship hits immobile terrain.
        We don't use collision forces because they are too stiff.
        Instead, we use impulse correction

        TODO use new collision spheres the real size of the ships ? Maybe not necessary
        if we use auto-aim and can reduce the hitboxes

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        terrain_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if terrain_into is None:
            return

        # Get impact parameters
        normal = entry.getSurfaceNormal(self.game.root_node)
        # Normalize the normal vector because it can have a non-unit length if a parent
        # object was scaled. It's dumb, but it is what it is...
        if not normal.almostEqual(Vec3(0, 0, 0)):
            normal.normalize()
        normal_relative_velocity = np.dot(normal, ship_from.speed)

        # Compute impulse correction
        # Push back if objects are still approaching
        if normal_relative_velocity < 0:
            velocity_correction = np.array(
                -normal * (1 + SOLID_COLLISION_ELASTICITY) * normal_relative_velocity
            )
        else:
            velocity_correction = np.zeros(3)
        # Position correction is too complicated to compute with arbitrary mesh
        # => Rely only on elastic impact to push back

        # Apply damage to the ship
        damage = COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2
        ship_from.push(
            damage=damage,
            velocity_correction=velocity_correction,
            position_correction=np.zeros(3),
        )

    def ship_into_ship(self, entry):
        """
        Handle the case where a ship hits another ship for the first time
        If ship_from is the player, play a crash sfx
        In any case, call ship_into_ship_pushback

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        ship_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. " "Ignoring.")
            return
        if ship_into is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_into being removed while it hits. " "Ignoring.")
            return

        # A ship never collides with its own subsystems (nor they with each
        # other): the owner mechanic spares same-vehicle colliders.
        if owners_share_vehicle(ship_from, ship_into):
            return

        if DEBUG_COLLISION:
            LOGGER.info("ship into ship")
            LOGGER.info(f"ship into : {ship_into.id}")
            LOGGER.info(f"ship from : {ship_from.id}")

        # Play SFX for player only
        if ship_from.id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getFromNodePath())
            self.game.app.sfx.player_crash(
                game=self.game, relative_hit_point=relative_hit_point, in_terrain=False
            )
        self.ship_into_ship_pushback(entry)

    def ship_again_ship(self, entry):
        """
        Handle the case where a ship hits another ship, and it already has
        at the last frame : call ship_into_ship_pushback

        :param entry: Panda3d's description of the collision
        """
        self.ship_into_ship_pushback(entry)

    def ship_into_ship_pushback(self, entry):
        """
        Handle the case where a ship hits another ship:
        The collisions is registered on both sides.
        So: hit only the "into" node. The other side of the collision
        will receive its damage when the inverse collision is handled.

        We don't use collision forces because they are too stiff.
        Instead, we use impulse and position correction

        TODO use new collision spheres the real size of the ships ? Maybe not necessary
        if we use auto-aim and can reduce the hitboxes

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        ship_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if ship_into is None:
            return

        # Get impact parameters
        # Normal and penetration depth from ship positions directly (assumed spherical)
        relative_position = ship_from.position - ship_into.position
        distance_m = np.linalg.norm(relative_position)
        if distance_m < 1e-4:
            # Objects are so close that we are better off waiting for a more favorable
            # situation
            return
        normal = relative_position / distance_m
        penetration_depth_m = max(  # Sometimes small numerical errors cause < 0
            -(distance_m - ship_from.hit_box_radius_m - ship_into.hit_box_radius_m), 0.0
        )
        relative_velocity = ship_from.speed - ship_into.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)
        mass_from_kg = ship_from.mass_kg
        mass_into_kg = ship_into.mass_kg
        denominator = 1 + mass_into_kg / mass_from_kg
        # Compute impulse correction
        # Push back if objects are still approaching
        if normal_relative_velocity < 0:
            velocity_correction = (  # correction impulse / self mass
                normal
                * (1 + SOLID_COLLISION_ELASTICITY)
                * normal_relative_velocity
                / denominator
            )
        else:
            velocity_correction = np.zeros(3)
        # Compute position correction.
        # Not a big correction in most cases, but limits penetration.
        position_correction = (
            -normal
            * POSITION_CORRECTION_RATIO
            * max(penetration_depth_m - PENETRATION_TOLERANCE_M, 0)
            / denominator
        )

        # Apply damage to the destructible objects
        damage = COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2

        ship_into.push(
            damage=damage,
            velocity_correction=velocity_correction,
            position_correction=position_correction,
        )

    def ship_into_massive_actor(self, entry):
        """
        Handle the case where a ship hits a massive actor for the first time
        If ship_from is the player, play a crash sfx
        In any case, call ship_into_massive_actor_pushback

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        massive_actor_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. " "Ignoring.")
            return
        if massive_actor_into is None:
            if DEBUG_COLLISION:
                LOGGER.info(
                    "massive_actor_into being removed while it hits. " "Ignoring."
                )
            return

        if DEBUG_COLLISION:
            LOGGER.info("ship into massive actor")
            LOGGER.info(f"Massive actor into : {massive_actor_into.id}")
            LOGGER.info(f"ship from : {ship_from.id}")

        # Play SFX for player only
        if ship_from.id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getFromNodePath())
            self.game.app.sfx.player_crash(
                game=self.game, relative_hit_point=relative_hit_point, in_terrain=False
            )
        self.ship_into_massive_actor_pushback(entry)

    def ship_again_massive_actor(self, entry):
        """
        Handle the case where a ship hits a massive actor, and it already has
        at the last frame : call ship_into_massive_actor_pushback

        :param entry: Panda3d's description of the collision
        """
        self.ship_into_massive_actor_pushback(entry)

    def ship_into_massive_actor_pushback(self, entry):
        """
        Handle the case where a ship hits massive actor.
        We don't use collision forces because they are too stiff.
        Instead, we use impulse correction

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        massive_actor_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            return
        if massive_actor_into is None:
            return

        # Get impact parameters
        normal = entry.getSurfaceNormal(self.game.root_node)
        # Normalize the normal vector because it can have a non-unit length if a parent
        # object was scaled. It's dumb, but it is what it is...
        if not normal.almostEqual(Vec3(0, 0, 0)):
            normal.normalize()
        relative_velocity = ship_from.speed - massive_actor_into.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)

        # Compute impulse correction
        # Push back if objects are still approaching
        if normal_relative_velocity < 0:
            velocity_correction = np.array(
                -normal * (1 + SOLID_COLLISION_ELASTICITY) * normal_relative_velocity
            )
        else:
            velocity_correction = np.zeros(3)
        # Position correction is too complicated to compute with arbitrary mesh
        # => Rely only on elastic impact to push back

        # Apply damage to the ship
        damage = COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2
        ship_from.push(
            damage=damage,
            velocity_correction=velocity_correction,
            position_correction=np.zeros(3),
        )
        # Apply damage to the massive actor
        massive_actor_into.apply_damage(damage=damage, damage_type="physical")

    def ship_into_subsystem(self, entry):
        """
        Handle a ship hitting a subsystem for the first time.
        Play a crash sfx if the incoming ship is the player, then push back.

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        subsystem_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. Ignoring.")
            return
        if subsystem_into is None:
            if DEBUG_COLLISION:
                LOGGER.info("subsystem_into being removed while it hits. Ignoring.")
            return

        # A ship never collides with its own subsystems
        if owners_share_vehicle(ship_from, subsystem_into):
            return

        # Play SFX for player only
        if ship_from.id == self.game.player.pawn.id:
            relative_hit_point = entry.getSurfacePoint(entry.getFromNodePath())
            self.game.app.sfx.player_crash(
                game=self.game, relative_hit_point=relative_hit_point, in_terrain=False
            )
        self.ship_into_subsystem_pushback(entry)

    def ship_again_subsystem(self, entry):
        """
        Handle a ship still touching a subsystem from a previous frame:
        call ship_into_subsystem_pushback.

        :param entry: Panda3d's description of the collision
        """
        self.ship_into_subsystem_pushback(entry)

    def ship_into_subsystem_pushback(self, entry):
        """
        Resolve a ship hitting a subsystem bolted onto another ship.

        The subsystem is rigid, so it is never pushed: the momentum exchange
        happens between the incoming ship and the subsystem's *parent* ship, whose
        speed and mass the subsystem stands in for. Both are pushed apart, split by
        mass, so a heavy parent barely moves while the incoming ship takes the
        recoil. The collision damage, however, is dealt to the subsystem itself,
        never to its parent ship.

        :param entry: Panda3d's description of the collision
        """
        ship_from = entry.from_node_path.python_tags["owner"]
        subsystem_into = entry.into_node_path.python_tags["owner"]

        # Handle pathologic cases
        if ship_from is None or subsystem_into is None:
            return
        if owners_share_vehicle(ship_from, subsystem_into):
            return

        # The ship the subsystem is bolted onto: it carries the kinematics
        host = subsystem_into.mounted_on
        if host is None:
            return

        # Impact normal from the actual geometry (robust to the subsystem's own
        # position lagging its moving hull). It points out of the subsystem,
        # i.e. roughly towards the incoming ship.
        normal = entry.getSurfaceNormal(self.game.root_node)
        # Normalize: a scaled parent can give a non-unit normal.
        if not normal.almostEqual(Vec3(0, 0, 0)):
            normal.normalize()

        # The subsystem is rigid, so its kinematics are its host ship's
        relative_velocity = ship_from.speed - host.speed
        normal_relative_velocity = np.dot(normal, relative_velocity)
        mass_from_kg = ship_from.mass_kg
        mass_host_kg = host.mass_kg

        # Push apart only if still approaching. Impulse is split by mass (a heavy
        # host barely moves; the incoming ship takes most of the recoil).
        if normal_relative_velocity < 0:
            impulse = (1 + SOLID_COLLISION_ELASTICITY) * normal_relative_velocity
            # -normal pushes the incoming ship away; +normal recoils the host.
            ship_velocity_correction = np.array(
                -normal * impulse / (1 + mass_from_kg / mass_host_kg)
            )
            host_velocity_correction = np.array(
                normal * impulse / (1 + mass_host_kg / mass_from_kg)
            )
        else:
            ship_velocity_correction = np.zeros(3)
            host_velocity_correction = np.zeros(3)

        damage = COLLISION_DAMAGE_FACTOR * normal_relative_velocity**2

        # Push the incoming ship back (and damage it)...
        ship_from.push(
            damage=damage,
            velocity_correction=ship_velocity_correction,
            position_correction=np.zeros(3),
        )
        # ...and recoil the host ship it rammed, but deal it no damage: the
        # subsystem absorbs the hit instead.
        host.push(
            damage=0.0,
            velocity_correction=host_velocity_correction,
            position_correction=np.zeros(3),
        )
        # The subsystem itself takes the collision damage
        subsystem_into.apply_damage(damage=damage, damage_type="physical")

    def sensor_into_obstacle(self, entry):
        """
        Handles the case where a sensor hits an obstacle
        Register the hit in the sensor

        :param entry: Panda3d's description of the collision
        """
        # Identify sensor and obstacle
        sensor = entry.from_node_path.python_tags["owner"]
        obstacle = entry.into_node_path.python_tags["owner"]
        if sensor is None:
            if DEBUG_COLLISION:
                LOGGER.info("Sensor is being removed while it hits")
            return

        if obstacle is None:
            if DEBUG_COLLISION:
                LOGGER.info("Obstacle is being removed while it is hit by a sensor")
            return
        try:
            if sensor.ship.id == obstacle.id:
                return  # It's the sensor's parent => Ignore collision
            # A subsystem mounted on the sensor's own ship is not an obstacle
            if owners_share_vehicle(sensor.ship, obstacle):
                return
        except AttributeError:
            pass  # When the obstacle does not have an id, it's not the sensor parent

        if DEBUG_COLLISION:
            LOGGER.info(f"sensor into obstacle: {obstacle} with id: {obstacle.id}")

        # Register collision in sensor
        normal = entry.getSurfaceNormal(self.game.root_node)
        hit_point = entry.getSurfacePoint(self.game.root_node)
        sensor.obstacles.append({"normal": normal, "hit_point": hit_point})

    def clean(self):
        """
        Cleans the CollisionSystem object
        """
        # Clean traverser
        self.traverser.clearColliders()
        self.traverser = None
        # Clean handler
        self.handler.clearInPatterns()
        self.handler.clearOutPatterns()
        self.game.app.ignore("laser-into-ship")
        self.game.app.ignore("laser-into-terrain")
        self.game.app.ignore("laser-into-subsystem")
        self.game.app.ignore("laser-into-shield")
        self.game.app.ignore("ship-into-terrain")
        self.game.app.ignore("ship-into-ship")
        self.game.app.ignore("ship-into-subsystem")
        self.game.app.ignore("ship-again-subsystem")
        self.game.app.ignore("sensor-into-terrain")
        self.game.app.ignore("sensor-again-terrain")
        self.game.app.ignore("sensor-into-ship")
        self.game.app.ignore("sensor-again-ship")
        self.game.app.ignore("sensor-into-subsystem")
        self.game.app.ignore("sensor-again-subsystem")
        self.handler = None
        self.game = None


def attach_collision_sphere(
    game,
    name: str,
    radius: float,
    collider_type: str,
    parent_node,
    parent_object,
    relative_position=[0, 0, 0],
) -> NodePath:
    """
    Attach a collision sphere to an existing node.
    This does not work well with lasers and low FPS. Could work for missiles, though ?

    :param game: The game stage
    :param name: The name of the collision sphere
    :param radius: Its radius
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_position: Its position relative to the origin of its parent node
    :return: The node path to the collision sphere
    """
    (
        from_mask_bit,
        into_mask_bit,
        add_to_collision_handler,
    ) = CollisionLayers.define_collision_masks(collider_type=collider_type)

    cnode = CollisionNode(name)
    cnode.addSolid(
        CollisionSphere(
            relative_position[0], relative_position[1], relative_position[2], radius
        )
    )
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and objct
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collosion handler
    if add_to_collision_handler:
        game.collision_system.traverser.addCollider(
            node_path, game.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_tube(
    game,
    name: str,
    point_a,
    point_b,
    radius: float,
    collider_type: str,
    parent_node,
    parent_object,
) -> NodePath:
    """
    Attach a collision tube (a capsule: a cylinder capped by two hemispheres) to
    an existing node. ``point_a`` and ``point_b`` are the centres of the two end
    hemispheres, in the parent node's frame.

    :param game: The game stage
    :param name: The name of the collision tube
    :param point_a: Centre of the first end hemisphere (x, y, z)
    :param point_b: Centre of the second end hemisphere (x, y, z)
    :param radius: The tube radius
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision tube
    """
    (
        from_mask_bit,
        into_mask_bit,
        add_to_collision_handler,
    ) = CollisionLayers.define_collision_masks(collider_type=collider_type)

    cnode = CollisionNode(name)
    cnode.addSolid(
        CollisionTube(
            point_a[0],
            point_a[1],
            point_a[2],
            point_b[0],
            point_b[1],
            point_b[2],
            radius,
        )
    )
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and object
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collision handler
    if add_to_collision_handler:
        game.collision_system.traverser.addCollider(
            node_path, game.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_segment(
    game,
    name: str,
    collider_type: str,
    parent_node,
    parent_object,
    relative_start_position,
    relative_end_position,
) -> NodePath:
    """
    Attach a collision segment to an existing node. Great for lasers

    :param game: The game stage
    :param name: The name of the collision segment
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_start_position: Its relative start position
    :param relative_end_position: Its relative end position
    :return: The node path to the collision segment
    """
    (
        from_mask_bit,
        into_mask_bit,
        add_to_collision_handler,
    ) = CollisionLayers.define_collision_masks(collider_type=collider_type)

    cnode = CollisionNode(name)
    cnode.addSolid(CollisionSegment(relative_start_position, relative_end_position))
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and objct
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collosion handler
    if add_to_collision_handler:
        game.collision_system.traverser.addCollider(
            node_path, game.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_plane(
    game,
    name: str,
    collider_type: str,
    parent_node,
    parent_object,
) -> NodePath:
    """
    Attach a collision plane to an existing node facing this node's z-up

    :param game: The game stage
    :param name: The name of the collision plane
    :param collider_type: The nature of the collider, defines from and into bitmasks
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :return: The node path to the collision plane
    """
    (
        from_mask_bit,
        into_mask_bit,
        add_to_collision_handler,
    ) = CollisionLayers.define_collision_masks(collider_type=collider_type)

    # Define a plane: normal + point
    plane = Plane(Vec3(0, 0, 1), Vec3(0, 0, 0))  # Z-up plane at Z=0

    cnode = CollisionNode(name)
    cnode.addSolid(CollisionPlane(plane))
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and objct
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collosion handler
    if add_to_collision_handler:
        game.collision_system.traverser.addCollider(
            node_path, game.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path
