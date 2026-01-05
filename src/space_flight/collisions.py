from direct.gui.OnscreenText import OnscreenText
from panda3d.core import CollisionHandlerEvent, CollisionTraverser

from space_flight import DEBUG_COLLISION


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

        # Debug
        self.collision_info = OnscreenText(text="", fg=(1, 1, 1, 1), scale=0.15)
        self.collision_info.hide()

    def collision_task(self, task):
        self.traverser.traverse(self.app.render)
        return task.cont

    def laser_into_destructible(self, entry):
        """
        Handle the case where a laser hits a dstructable object:
        Damage the destructable object and remove the laser.

        TODO: Ignore self hits... Needs UIDs ?
        TODO: Delete the laser and all its children. Needs UIDs ?
        TODO: Add a hit sprite

        :param entry: Panda3d's description of the collision
        """
        laser = entry.from_node_path.python_tags["owner"]
        destructible = entry.into_node_path.python_tags["owner"]

        # Apply damage to the destructible object
        destructible.count_hit(damage=laser.power)

        # Delete laser
        laser.shot.removeNode()
