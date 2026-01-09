import numpy as np
from direct.showbase.ShowBase import ShowBase
from panda3d.core import NodePath, Quat

from space_flight import DATAFILES_PATH


class ShipModel:
    def __init__(self, app: ShowBase, ship_type: str = "a-wing", is_cockpit=True):
        self.app = app
        self.ship_type = ship_type

        if self.ship_type == "a-wing":
            if is_cockpit:
                self.model = self.app.loader.load_model(
                    DATAFILES_PATH / "models/ships/a-wing/cockpit/scene.gltf"
                )
                self.offset = np.array([0.0, 0.8, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                raise NotImplementedError
        elif self.ship_type == "tie-fighter":
            if is_cockpit:
                self.model = self.app.loader.load_model(
                    DATAFILES_PATH / "models/ships/tie-fighter/cockpit/scene.gltf"
                )
                self.offset = np.array([0.0, 0.9, -0.2])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
            else:
                self.model = self.app.loader.load_model(
                    DATAFILES_PATH / "models/star_wars_tie_interceptor/scene.gltf"
                )
                self.offset = np.array([0.0, 0.0, 0.0])
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(
                    np.sqrt(2) / 2, -np.sqrt(2) / 2, 0.0, 0.0
                )
                self.model.setScale(5.0, 5.0, 5.0)

        else:
            raise NotImplementedError(ship_type)

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
