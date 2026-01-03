from direct.gui.OnscreenText import OnscreenText
from panda3d.core import CollisionHandlerEvent, CollisionTraverser


class CollisionSystem:
    def __init__(self, app):
        self.app = app
        self.traverser = CollisionTraverser()
        self.traverser.showCollisions(self.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
        self.app.taskMgr.add(self.collision_task, "collisionTask")

        self.app.accept("laser-into-ship", self.laser_into_ship)

        # Debug
        self.collision_info = OnscreenText(text="", fg=(1, 1, 1, 1), scale=0.15)
        self.collision_info.hide()

    def collision_task(self, task):
        self.traverser.traverse(self.app.render)
        return task.cont

    def laser_into_ship(self, entry):
        """
        Handle the case where a laser hits a ship : damage the ship
        and remove the laser.

        TODO: Ignore self hits... Needs UIDs ?
        TODO: Delete the laser and all its children. Needs UIDs ?
        TODO: Add a hit sprite

        :param entry: Panda3d's description of the collision
        """
        laser = entry.from_node_path.python_tags["owner"]
        ship = entry.into_node_path.python_tags["owner"]

        ship.count_hit(damage=laser.power)
        self.collision_info.text = f"{ship.health}"
        self.collision_info.show()
        self.app.doMethodLater(
            0.25, lambda t: self.collision_info.hide(), "Remove collision info"
        )
        # self.shell.removeNode()
        # self.taskMgr.remove("move_shell")
