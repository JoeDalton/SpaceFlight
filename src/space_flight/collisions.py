import logging

import numpy as np
from panda3d.core import (
    BitMask32,
    CollisionHandlerEvent,
    CollisionNode,
    CollisionSegment,
    CollisionSphere,
    CollisionTraverser,
    NodePath,
)

from space_flight import DEBUG_COLLISION

SOLID_COLLISION_RESTITUTION = 0.3  # 0 = inelastic, 1 = elastic
POSITION_CORRECTION_RATIO = 0.1
PENETRATION_TOLERANCE_M = 0.1
COLLISION_DAMAGE_FACTOR = 0.0001  # TODO configurable with difficulty

LOGGER = logging.getLogger()


class CollisionLayers:
    LASER = BitMask32.bit(0)
    SENSOR = BitMask32.bit(0)
    DESTRUCTIBLE = BitMask32.bit(2)
    ENVIRONMENT = BitMask32.bit(3)

    # Lasers hit environment and destructibles
    # Nothing hits them
    LASER_FROM = DESTRUCTIBLE | ENVIRONMENT
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
        else:
            raise ValueError(f"Unknown collider type {collider_type}")
        return from_mask_bit, into_mask_bit, add_to_collision_handler


class CollisionSystem:
    def __init__(self, game):
        self.game = game
        self.traverser = CollisionTraverser()
        if DEBUG_COLLISION:
            self.traverser.showCollisions(self.game.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")

        self.game.app.accept("laser-into-ship", self.laser_into_destructible)
        self.game.app.accept("laser-into-terrain", self.laser_into_terrain)
        self.game.app.accept("ship-into-terrain", self.ship_into_terrain)
        self.game.app.accept("ship-into-ship", self.ship_into_ship)

    def update_collisions(self):
        """
        Compute collisions via panda3d internal methods
        it triggers the "%fn-into-%in" events
        """
        self.traverser.traverse(self.game.app.render)

    def laser_into_destructible(self, entry):
        """
        Handle the case where a laser hits a destructible object:
        Damage the destructible object and remove the laser.

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

        if DEBUG_COLLISION:
            LOGGER.info("laser into destructible")

        # Apply damage to the destructible object
        normal = entry.getSurfaceNormal(self.game.root_node)
        destructible.take_hit(damage=laser.power, normal_world_vector=normal)

        # Delete laser
        laser.shot.removeNode()

        # Apply hit effect depending on player or bot
        if destructible_id == self.game.player.ship.id:
            relative_hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            self.game.player.play_impact_sound(
                relative_hit_point=relative_hit_point, kind="laser"
            )
        else:
            # TODO: Mute bots shooting on bots ?
            # hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            # TODO: Add a hit sprite
            self.game.app.sfx.distant_impact_hit(
                player_ship_pos=self.game.player.ship.position,
                hit_pos=entry.into_node_path.parent.getPos(),
                impact_type="target",
            )

    def laser_into_terrain(self, entry):
        """
        Handle the case where a laser hits a terrain object:
        Remove the laser.

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
            player_ship_pos=self.game.player.ship.position,
            hit_pos=entry.into_node_path.parent.getPos(),
            impact_type="terrain",
        )

        # Delete laser
        laser.shot.removeNode()

    def ship_into_terrain(self, entry):
        """
        TODO

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("ship into terrain")

    def ship_into_ship(self, entry):
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

        if ship_from is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_from being removed while it hits. " "Ignoring.")
            return
        if ship_into is None:
            if DEBUG_COLLISION:
                LOGGER.info("ship_into being removed while it hits. " "Ignoring.")
            return

        if DEBUG_COLLISION:
            LOGGER.info("ship into ship")
            LOGGER.info(f"ship into : {ship_into.id}")
            LOGGER.info(f"ship from : {ship_from.id}")

        # Get impact parameters
        # Normal and penetration depth from ship positions directly (assumed spherical)
        relative_position = ship_from.position - ship_into.position
        distance_m = np.linalg.norm(relative_position)
        if distance_m < 1e-4:
            # Objects are so close that we are better off waiting for a more favorable
            # situation
            return
        normal = relative_position / distance_m
        penetration_depth_m = -(
            distance_m - ship_from.hit_radius_m - ship_into.hit_radius_m
        )
        assert penetration_depth_m >= 0
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
                * (1 + SOLID_COLLISION_RESTITUTION)
                * normal_relative_velocity
                / denominator
            )
        # Compute position correction.
        # Not a big correction in most cases, but limits penetration.
        position_correction = (
            normal
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

        # TODO SFX
        # # Apply hit effect depending on player or bot
        # if ship_from.id == self.game.player.ship.id:
        #     relative_hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
        #     self.game.app.sfx.ship_collision_on_player(
        #         game=self.game, relative_hit_point=relative_hit_point
        #     )
        # else:
        #     # TODO: Mute bots shooting on bots ?
        #     # hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
        #     # TODO: Add a hit sprite
        #     self.game.app.sfx.distant_impact_hit(
        #         player_ship_pos=self.game.player.ship.position,
        #         hit_pos=entry.into_node_path.parent.getPos(),
        #         impact_type="target",
        #     )

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
        self.game.app.ignore("ship-into-terrain")
        self.game.app.ignore("ship-into-ship")
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
    :param name: The name of the collision sphere
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
