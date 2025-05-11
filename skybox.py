from direct.showbase.ShowBase import ShowBase

class Skybox:
    def __init__(self, app: ShowBase, name: str="purple"):
        self.app = app

        self.skybox = self.app.loader.loadModel(f"models/skyboxes/sky_{name}.bam")
        self.skybox.setBin('background', 1)
        self.skybox.setDepthWrite(0)
        self.skybox.reparentTo(self.app.render)
        self.skybox.set_scale(50000)
