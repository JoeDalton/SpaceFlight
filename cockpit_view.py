import numpy as np

from direct.showbase.ShowBase import ShowBase
from panda3d.core import Quat, NodePath

from utils import rotate_single_vector


class CockpitView:
    def __init__(self, app: ShowBase, ship_name: str="a-wing"):
        self.app = app
        self.ship_name = ship_name
        
        if self.ship_name == "a-wing":
            self.model = self.app.loader.load_model("models/ships/a-wing/cockpit/scene.gltf")
            self.offset = np.array([0.0, 1.0, 0.2])
            self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) 
        else:
            raise NotImplementedError(ship_name)
        
    def anchor_model(self, node: NodePath):
        """
        Anchors the 3D model of the cockpit to the player node
        """
        self.model.reparent_to(node)
        # self.model.show_bounds()

        model_pos = -rotate_single_vector(
            self.orientation, self.offset
        )
        self.model.setPos(model_pos[0], model_pos[1], model_pos[2])
        self.model.setQuat(Quat(self.orientation.w, self.orientation.x, self.orientation.y, self.orientation.z))
 