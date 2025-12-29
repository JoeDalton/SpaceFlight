import numpy as np

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Quat, NodePath


class ShipModel:
    def __init__(self, app: ShowBase, ship_name: str="a-wing", is_cockpit=True):
        self.app = app
        self.ship_name = ship_name
        
        if self.ship_name == "a-wing":
            if is_cockpit:
                self.model = self.app.loader.load_model("models/ships/a-wing/cockpit/scene.gltf")
                self.offset = np.array([0.0, 0.8, -0.2])
                # self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) # Windows ?
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(np.sqrt(2)/2, -np.sqrt(2)/2, 0.0, 0.0) # Linux ?
            else:
                raise NotImplementedError
        elif self.ship_name == "tie-fighter":
            if is_cockpit:
                self.model = self.app.loader.load_model("models/ships/tie-fighter/cockpit/scene.gltf")
                self.offset = np.array([0.0, 0.9, -0.2])
                # self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) # Windows ?
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(np.sqrt(2)/2, -np.sqrt(2)/2, 0.0, 0.0) # Linux ?
            else:
                self.model = self.app.loader.load_model("models/star_wars_tie_interceptor/scene.gltf")
                self.offset = np.array([0.0, 0.0, 0.0])
                # self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) # Windows ?
                self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(np.sqrt(2)/2, -np.sqrt(2)/2, 0.0, 0.0) # Linux ?
            
        else:
            raise NotImplementedError(ship_name)
        
    def anchor_model(self, node: NodePath):
        """
        Anchors the 3D model of the cockpit to the player node
        """
        self.model.reparent_to(node)
        # self.model.show_bounds()

        self.model.setPos(*self.offset)
        self.model.setQuat(Quat(self.orientation.w, self.orientation.x, self.orientation.y, self.orientation.z))
 