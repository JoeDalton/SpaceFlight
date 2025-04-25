import numpy as np
import quaternion

from direct.showbase.ShowBase import ShowBase
from direct.task import Task
from panda3d.core import Quat
import random

random.seed(1)
np.random.seed(1)

class AsteroidField:
    def __init__(self, app: ShowBase, n_asteroids: int=40, field_size: float=200):
        self.app = app
        self.n_asteroids = n_asteroids
        self.instances = {"asteroids": [], "omega": []}
        
        asteroid_models = [
            self.app.loader.load_model("models/toutatis_asteroid/scene.gltf"),
            self.app.loader.load_model("models/54509_asteroid/scene.gltf"),
            self.app.loader.load_model("models/54509_asteroid/scene.gltf"),
        ]

        for ast_idx in range(self.n_asteroids):
            asteroid_model = random.choice(asteroid_models)
            instance = self.app.render.attachNewNode("asteroid_instance")
            asteroid_model.instanceTo(instance)

            # Set initial position
            ini_pos = np.random.rand(3) * field_size - 0.5 * field_size

            instance.set_pos(*ini_pos)
            # instance.show_bounds()

            # Set scale
            scale = np.ones(3) * (np.random.rand() * 5 + 1)
            instance.setScale(*scale)

            # Set initial orientation
            temp = np.random.rand(4)
            quat_array = temp / np.linalg.norm(temp) + 0.2
            instance.setQuat(Quat(*quat_array))

            # Set rotational rate
            omega = np.deg2rad(np.random.rand(3) * 20 - 5)

            self.instances["asteroids"].append(instance)
            self.instances["omega"].append(omega)

        self.app.taskMgr.add(self.move_asteriods_task, "move_asteriods_task")
        
    def move_asteriods_task(self, task):
        dt = self.app.clock.dt
        
        for ast_idx in range(self.n_asteroids):
            instance = self.instances["asteroids"][ast_idx]
            omega = self.instances["omega"][ast_idx]
            panda_quat = instance.getQuat()
            quat = np.quaternion(*panda_quat)
            quat_omega = np.quaternion(0, *omega)
            quat_dot = 0.5 * quat_omega * quat

            new_quat = quat + dt * quat_dot
            new_quat /= np.linalg.norm(quaternion.as_float_array(new_quat))
            instance.setQuat(Quat(new_quat.w, new_quat.x, new_quat.y, new_quat.z))

        return Task.cont
        