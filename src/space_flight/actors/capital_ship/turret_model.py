import numpy as np
from panda3d.core import NodePath, Quat

from space_flight import DATAFILES_PATH


class TurretModel:
    def __init__(self, game, parent_node: NodePath, turret_type: str = "test"):
        self.game = game
        self.turret_type = turret_type
        # Instantiate already-loaded models to a new node
        self.model = self.game.root_node.attachNewNode("turret_model_instance")

        if self.turret_type == "test":
            self.game.app.asset_manager.instantiate_3d_model_to_node(
                path=DATAFILES_PATH / "models/turrets/test/turret.glb",
                parent_node=self.model,
            )
            self.offset = np.array([0.0, 0.0, 0.0])
            self.orientation = np.quaternion(1.0, 0.0, 0.0, 0.0)
            self.model.setScale(1)
            # Find the proper nodes to manipulate in the model
            self.yaw_node = self.model.find("**/heading_axis")
            self.pitch_node = self.model.find("**/cannon_axis")
            # Assign movement functions
            self.set_yaw = self.yaw_node.setH
            self.set_pitch = self.pitch_node.setP
            self.cannon_node = self.pitch_node
        else:
            raise NotImplementedError(turret_type)

        self.anchor_model(parent_node)

    def anchor_model(self, node: NodePath):
        """
        Anchors the 3D model of the cockpit to the ship node
        """
        self.model.reparent_to(node)
        self.model.setPos(*self.offset)
        self.model.setQuat(
            Quat(
                self.orientation.w,
                self.orientation.x,
                self.orientation.y,
                self.orientation.z,
            )
        )

    def clean(self):
        """
        Cleans the ShipModel object
        """
        self.model.removeNode()
        self.model = None
        self.game = None
