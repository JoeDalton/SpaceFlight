import logging

from direct.gui.OnscreenText import OnscreenText
from panda3d.core import CollisionHandlerEvent, CollisionTraverser

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
        Handle the case where a laser hits a destructable object:
        Damage the destructable object and remove the laser.

        TODO: Ignore self hits... Needs UIDs ?
        TODO: Add a hit sprite

        :param entry: Panda3d's description of the collision
        """
        if DEBUG_COLLISION:
            LOGGER.info("ship into destructible")
        laser = entry.from_node_path.python_tags["owner"]
        destructible = entry.into_node_path.python_tags["owner"]

        # Apply damage to the destructible object
        destructible.count_hit(damage=laser.power)

        # Delete laser
        laser.shot.removeNode()

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
