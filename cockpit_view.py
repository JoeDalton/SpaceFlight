import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import Quat



class CockpitView:
    def __init__(self, app: ShowBase, ship: str="a-wing"):
        self.app = app
        self.ship = ship
        
        if self.ship == "a-wing":
            self.model = app.loader.load_model("models/ships/a-wing/cockpit/scene.gltf")
            self.offset = np.array([0.0, 1.0, 0.2])
            self.orientation = np.quaternion(0.0, 0.0, 1.0, 0.0) * np.quaternion(0.0, 1.0, 0.0, 0.0) 
        
        self.model.reparent_to(self.app.render)
        # self.model.show_bounds()

        self.app.taskMgr.add(self.cockpit_position_update_task, "cockpit_position_update_task")
        
    def cockpit_position_update_task(self, task):
        pos = self.app.camera.get_pos()   # in world coordinates
        quat = self.app.camera.getQuat()   # in world coordinates

        camera_pos = np.array([*pos])
        camera_quat = np.quaternion(*quat)
        model_quat = camera_quat * self.orientation

        model_pos = camera_pos - quaternion.rotate_vectors(
            model_quat, self.offset
        )
        self.model.setPos(model_pos[0], model_pos[1], model_pos[2])
        self.model.setQuat(Quat(model_quat.w, model_quat.x, model_quat.y, model_quat.z))

        return Task.cont
        