import uuid

from space_flight import DATAFILES_PATH


class Skybox:
    def __init__(self, game, name: str = "purple"):
        self.game = game
        self.id = uuid.uuid4()

        self.skybox = self.game.root_node.attachNewNode("drydock_instance")
        skybox_path = DATAFILES_PATH / f"models/skyboxes/sky_{name}.bam"
        self.game.app.asset_manager.instantiate_3d_model_to_node(
            path=skybox_path,
            parent_node=self.skybox,
        )

        self.skybox.setBin("background", 1)
        self.skybox.setDepthWrite(0)
        self.skybox.reparentTo(self.game.root_node)
        self.skybox.set_scale(50000)
        self.game.actor_methods[self.id] = [self.move_skybox_task]

    def move_skybox_task(self):
        """
        Moves the skybox along with the player to make it appear to be at infinity
        """
        new_position = self.game.player.ship.position
        self.skybox.setPos(new_position[0], new_position[1], new_position[2])

    def clean(self):
        """
        Cleans the Skybox object
        """
        self.skybox.removeNode()
        self.game = None
