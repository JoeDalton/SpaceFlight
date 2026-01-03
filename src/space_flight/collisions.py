from panda3d.core import (
    CollisionHandlerEvent,
    CollisionTraverser,
)

class CollisionSystem:
    def __init__(self, app):
        self.app = app
        self.traverser = CollisionTraverser()
        self.traverser.showCollisions(self.app.render)
        self.handler = CollisionHandlerEvent()
        self.handler.addInPattern("%fn-into-%in")
        self.app.taskMgr.add(self.collision_task, "collisionTask")

        self.app.accept("laser-into-ship", self.laser_into_ship)

    def collision_task(self, task):
        self.traverser.traverse(self.app.render)
        return task.cont
    
    def laser_into_ship(self, entry):
        print(entry)
        print("Hit!")
        # self.shell.removeNode()
        # self.taskMgr.remove("move_shell")