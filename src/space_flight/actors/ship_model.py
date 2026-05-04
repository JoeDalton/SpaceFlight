import numpy as np
from panda3d.core import NodePath, Quat

from space_flight import DATAFILES_PATH


class ShipModel:
    def __init__(
        self, game, parent_node: NodePath, ship_type: str = "a-wing", is_cockpit=True
    ):
        self.game = game
        self.ship_type = ship_type
        # Instantiate already-loaded models to a new node
        self.model = self.game.root_node.attachNewNode("ship_model_instance")

        if self.ship_type == "a-wing":  # OK
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/a-wing/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.8, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(0.8)
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/a-wing/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(0.01)
        elif self.ship_type == "tie-interceptor":  # OK
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/tie_common/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.9, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH
                    / "models/ships/tie-interceptor/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(4.1)
        elif self.ship_type == "tie-bomber":  # OK
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/tie_common/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0, 0.9, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/tie-bomber/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([1.5, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(1.0)
        elif self.ship_type == "y-wing":  # OK
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/y-wing/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0, 0.7, -0.5])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/y-wing/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(0.115)
        elif self.ship_type == "x-wing":  # NOK cockpit
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/x-wing/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0, 0.9, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/x-wing/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = (
                    np.quaternion(0.0, 0.0, 0.0, 1.0)
                    * np.quaternion(0.0, 0.0, 1.0, 0.0)
                    * np.quaternion(np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0)
                )
                self.model.setScale(0.5)
        elif self.ship_type == "tie-fighter":  # NOK, model does not show
            if is_cockpit:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH / "models/ships/tie_common/cockpit/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.9, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.game.app.asset_manager.instantiate_3d_model_to_node(
                    path=DATAFILES_PATH
                    / "models/ships/tie-fighter/exterior/scene.gltf",
                    parent_node=self.model,
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(1000.0)
        else:
            raise NotImplementedError(ship_type)

        self.anchor_model(parent_node)

    def anchor_model(self, node: NodePath):
        """
        Anchors the 3D model of the cockpit to the ship node
        """
        self.model.reparent_to(node)
        # self.model.show_bounds()

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
