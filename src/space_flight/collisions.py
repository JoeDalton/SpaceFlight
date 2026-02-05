import logging

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    CollisionHandlerEvent,
    CollisionNode,
    CollisionSegment,
    CollisionSphere,
    CollisionTraverser,
    NodePath,
)

from space_flight import DEBUG_COLLISION

LOGGER = logging.getLogger()


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

        TODO: Add a hit sprite

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
        destructible.count_hit(damage=laser.power)

        # Delete laser
        laser.shot.removeNode()

        # Apply hit effect depending on player or bot
        if destructible_id == self.app.player.ship.id:
            pass  # TODO
        else:
            # TODO: Option to mute bots shooting on bots ?
            # hit_point = entry.getSurfacePoint(entry.getIntoNodePath())
            # normal = entry.getSurfaceNormal(entry.getIntoNodePath())
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
        TODO Never happens. Why ?

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("ship into terrain")

    def ship_into_ship(self, entry):
        """
        TODO Never happens. Why ?

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("ship into ship")


def attach_collision_sphere(
    app,
    name: str,
    radius: float,
    from_mask_bit,
    into_mask_bit,
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
    :param from_mask_bit: Its from_mask_bit
    :param into_mask_bit: Its into_mask_bit
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_position: Its position relative to the origin of its parent node
    :return: The node path to the collision sphere
    """
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
    app.collision_system.traverser.addCollider(node_path, app.collision_system.handler)

    if DEBUG_COLLISION:
        node_path.show()
    return node_path


def attach_collision_segment(
    app,
    name: str,
    from_mask_bit,
    into_mask_bit,
    parent_node,
    parent_object,
    relative_start_position,
    relative_end_position,
) -> NodePath:
    """
    Attach a collision segment to an existing node.

    :param app: The panda3d app
    :param name: The name of the collision sphere
    :param from_mask_bit: Its from_mask_bit
    :param into_mask_bit: Its into_mask_bit
    :param parent_node: Its parent_node
    :param parent_object: Its parent_object
    :param relative_position: Its position relative to the origin of its parent node
    :return: The node path to the collision sphere
    """
    cnode = CollisionNode(name)
    cnode.addSolid(CollisionSegment(relative_start_position, relative_end_position))
    # Define masks
    cnode.setFromCollideMask(from_mask_bit)
    cnode.setIntoCollideMask(into_mask_bit)
    # Attach to parent node and objct
    node_path = parent_node.attachNewNode(cnode)
    node_path.setPythonTag("owner", parent_object)
    # Register in collosion handler
    app.collision_system.traverser.addCollider(node_path, app.collision_system.handler)

    if DEBUG_COLLISION:
        node_path.show()
    return node_path
