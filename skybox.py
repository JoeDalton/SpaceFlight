from direct.showbase.ShowBase import ShowBase

class Skybox:
    def __init__(self, app: ShowBase, name: str="purple"):
        self.app = app

        self.skybox = self.app.loader.loadModel(f"models/skyboxes/sky_{name}.bam")
        self.skybox.setBin('background', 1)
        self.skybox.setDepthWrite(0) 
        # self.skybox.reparentTo(self.app.render)
    #     # self.skybox.set_scale(500)
    #     # self.skybox.set_compass()
    #     # self.skybox.set_bin('background', 0)
    #     # self.skybox.set_depth_write(False)
    #     # self.skybox.set_light_off()
    #     # self.skybox.set_shader_off()
    #     self.app.taskMgr.add(self.move_skybox_task, "move_skybox_task")

    # def move_skybox_task(self, task):
    #     pos = self.app.camera.get_pos()
    #     self.skybox.setPos(pos[0], pos[1], pos[2])
    #     # self.skybox.setPos(self.app.camera, 0, 0, 0)
    #     return task.cont

