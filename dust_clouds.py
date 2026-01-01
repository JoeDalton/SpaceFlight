import random
from typing import List
from panda3d.core import (
    NodePath, CardMaker, TransparencyAttrib
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock
import numpy as np

class SpeedDust:
    def __init__(self, app: ShowBase, num_particles:int=300, spread:int=30, depth:float=100.0, colors: List=["white"]):
        # TODO: GPU-friendly loading of nodes (cf asteroids)
        self.app = app
        self.spread = spread
        self.depth = depth

        self.particles = []

        cm = CardMaker("particle")
        cm.setFrame(-0.02, 0.02, -0.02, 0.02)

        root = NodePath("speedDust")
        root.reparentTo(self.app.camera)
        root.setTransparency(TransparencyAttrib.MAlpha)
        root.setLightOff()

        self.colors = colors

        for _ in range(num_particles):
            particle = root.attachNewNode(cm.generate())
            particle.setBillboardPointEye()
            self._init_particle(particle)
            self.particles.append(particle)

        self.root = root
        
        self.app.taskMgr.add(self.update_task, "speedDustUpdate")

    def _init_particle(self, particle):
        x = random.uniform(-self.spread, self.spread)
        z = random.uniform(-self.spread, self.spread)
        y = random.uniform(0, self.depth)
        scaling = random.uniform(1.0, 4.0)
        color = random.choice(self.colors)
        particle.setPos(x, y, z)
        particle.setTexture(self.app.loader.loadTexture(f"models/dust/dust_{color}.png"))
        #particle.setColor(
        #    random.uniform(0.8, 1.0),
        #    random.uniform(0.8, 1.0),
        #    1.0, 
        #    1.0
        #)
        particle.setScale(scaling, scaling, scaling)

    def _reset_particle(self, particle):
        particle.setY(particle.getY() + self.depth)

    def update_task(self, task):
        dt = globalClock.getDt()
        speed = np.linalg.norm(self.app.player.ship.speed)
        #self.spread = max(5, 30 - speed * 0.1)
        for particle in self.particles:
            particle.setY(particle.getY() - speed * dt)
            if particle.getY() < 0:
                self._reset_particle(particle)
        return task.cont
