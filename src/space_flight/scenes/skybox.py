import uuid

from space_flight import DATAFILES_PATH


class Skybox:
    def __init__(self, game, name: str = "purple"):
        self.game = game
        self.id = uuid.uuid4()

        skybox_path = DATAFILES_PATH / f"models/skyboxes/{name}.bam"

        self.node = self.game.root_node.attachNewNode("skybox_node")
        self.model = self.game.app.loader.loadModel(skybox_path)
        self.model.setShaderOff()
        self.model.setLightOff()

        self.model.setBin("background", 1)
        self.model.setDepthWrite(0)
        self.model.reparentTo(self.node)
        self.model.set_scale(50000)

        self.game.method_lists[self.id] = [self.move_skybox_task]

    def move_skybox_task(self):
        """
        Moves the skybox along with the player to make it appear to be at infinity
        """
        new_position = self.game.player.ship.position
        self.node.setPos(new_position[0], new_position[1], new_position[2])

    def clean(self):
        """
        Cleans the Skybox object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.node.removeNode()
        self.game = None
