from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH


class Skybox:
    def __init__(self, app: ShowBase, name: str = "purple"):
        self.app = app

        self.skybox = self.app.loader.loadModel(
            DATAFILES_PATH / f"models/skyboxes/sky_{name}.bam"
        )
        self.skybox.setBin("background", 1)
        self.skybox.setDepthWrite(0)
        self.skybox.reparentTo(self.app.render)
        self.skybox.set_scale(50000)
        self.app.taskMgr.add(self.move_skybox_task, "move_skybox_task")

    def move_skybox_task(self, task):
        new_position = self.app.player.ship.position
        self.skybox.setPos(new_position[0], new_position[1], new_position[2])
        return task.cont
