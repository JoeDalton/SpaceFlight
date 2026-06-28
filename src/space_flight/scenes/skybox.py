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
        # The ocean's reflection camera applies a z>=0 clip plane to cull
        # underwater geometry. The skybox is "at infinity" and must always fill
        # the reflected background, so exempt it from that clip plane (priority 1
        # overrides the reflection camera's initial state). Without this, the
        # reflection's near-horizon rays — which strike the skybox sphere below
        # z=0 — get clipped and fall back to the buffer's deep-blue clear colour,
        # producing a solid band along the horizon that widens with altitude.
        self.model.setClipPlaneOff(1)
        self.model.reparentTo(self.node)
        self.model.set_scale(50000)

        self.game.method_lists[self.id] = [self.move_skybox_task]

    def move_skybox_task(self):
        """
        Moves the skybox along with the player to make it appear to be at infinity
        """
        new_position = self.game.player.pawn.position
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
