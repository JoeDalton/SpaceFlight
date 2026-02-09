import logging
from typing import Tuple

from direct.gui.OnscreenText import OnscreenText
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
    def define_collision_masks(collider_type: str) -> Tuple[BitMask32]:
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
    def __init__(self, app):
        self.app = app
        self.traverser = CollisionTraverser()
        if DEBUG_COLLISION:
            self.traverser.showCollisions(self.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
        self.app.taskMgr.add(self.collision_task, "collider")

        self.app.accept("laser-into-ship", self.laser_into_destructible)
        self.app.accept("laser-into-terrain", self.laser_into_terrain)
        self.app.accept("ship-into-terrain", self.ship_into_terrain)
        self.app.accept("ship-into-ship", self.ship_into_ship)

        # Debug
        self.collision_info = OnscreenText(text="", fg=(1, 1, 1, 1), scale=0.15)
        self.collision_info.hide()

    def collision_task(self, task):
        self.traverser.traverse(self.app.render)
        return task.cont

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
        normal = entry.getSurfaceNormal(entry.getIntoNodePath())
        destructible.take_hit(damage=laser.power, normal_body_vector=normal)

        # Delete laser
        laser.shot.removeNode()

        # Apply hit effect depending on player or bot
        if destructible_id == self.app.player.ship.id:
            relative_hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            self.app.sfx.impact_hit_on_player(relative_hit_point=relative_hit_point)
        else:
            # TODO: Mute bots shooting on bots ?
            # hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            # TODO: Add a hit sprite
            self.app.sfx.distant_impact_hit(
                hit_pos=entry.into_node_path.parent.getPos(), impact_type="target"
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

        self.app.sfx.distant_impact_hit(
            hit_pos=entry.into_node_path.parent.getPos(), impact_type="terrain"
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
        TODO

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("ship into ship")


def attach_collision_sphere(
    app,
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

    # TODO: use this for ships/asteroids

    :param app: The panda3d app
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
        app.collision_system.traverser.addCollider(
            node_path, app.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_segment(
    app,
    name: str,
    collider_type: str,
    parent_node,
    parent_object,
    relative_start_position,
    relative_end_position,
) -> NodePath:
    """
    Attach a collision segment to an existing node.

    :param app: The panda3d app
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
        app.collision_system.traverser.addCollider(
            node_path, app.collision_system.handler
        )

    if DEBUG_COLLISION:
        node_path.show()
    return node_path
