import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import Quat



class CockpitView:
    def __init__(self, app: ShowBase, ship_name: str="a-wing"):
        self.app = app
        self.ship_name = ship_name
        
        if self.ship_name == "a-wing":
            self.model = app.loader.load_model("models/ships/a-wing/cockpit/scene.gltf")
            self.offset = np.array([0.0, 1.0, 0.2])
            self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) 
        else:
            raise NotImplementedError(ship_name)
        
        self.model.reparent_to(self.app.camera)
        # self.model.show_bounds()

        model_pos = - quaternion.rotate_vectors(
            self.orientation, self.offset
        )
        self.model.setPos(model_pos[0], model_pos[1], model_pos[2])
        self.model.setQuat(Quat(self.orientation.w, self.orientation.x, self.orientation.y, self.orientation.z))
 