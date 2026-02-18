import random
import uuid
from typing import List

import numpy as np
from panda3d.core import CardMaker, NodePath, TransparencyAttrib

from space_flight import DATAFILES_PATH

MIN_DUST_ALPHA = 0.2


class SpeedDustCloud:
    def __init__(
        self,
        game,
        num_particles: int = 300,
        spread: int = 30,
        depth: float = 100.0,
        colors: List = ["white"],
    ):
        # TODO: GPU-friendly loading of nodes (cf asteroids)
        self.game = game
        self.spread = spread
        self.depth = depth
        self.id = uuid.uuid4()

        self.particles = []

        cm = CardMaker("particle")
        cm.setFrame(-0.02, 0.02, -0.02, 0.02)

        root = NodePath("speedDust")
        root.reparentTo(self.game.app.camera)
        root.setTransparency(TransparencyAttrib.MAlpha)
        root.setLightOff()

        self.colors = colors

        for _ in range(num_particles):
            particle = root.attachNewNode(cm.generate())
            particle.setBillboardPointEye()
            self._init_particle(particle)
            self.particles.append(particle)

        self.root = root
        self.max_speed = self.game.player.ship.max_speed_mps

        self.game.actor_methods[self.id] = [self.dust_update]

    def _init_particle(self, particle):
        x = random.uniform(-self.spread, self.spread)
        z = random.uniform(-self.spread, self.spread)
        y = random.uniform(0, self.depth)
        scaling = random.uniform(1.0, 4.0)
        color = random.choice(self.colors)
        particle.setPos(x, y, z)
        particle.setTexture(
            self.game.app.loader.loadTexture(
                DATAFILES_PATH / f"sprites/dust/dust_{color}.png"
            )
        )
        particle.setScale(scaling, scaling, scaling)

    def _reset_particle(self, particle):
        particle.setY(particle.getY() + self.depth)

    def dust_update(self):
        dt = self.game.game_time.get_time_step()
        speed = np.linalg.norm(self.game.player.ship.speed)
        alpha = MIN_DUST_ALPHA + speed * (1.0 - MIN_DUST_ALPHA) / self.max_speed
        self.root.setAlphaScale(alpha)
        for particle in self.particles:
            particle.setY(particle.getY() - speed * dt)
            if particle.getY() < 0:
                self._reset_particle(particle)
