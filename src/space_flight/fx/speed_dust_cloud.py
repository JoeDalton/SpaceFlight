import random
import uuid
from typing import List

import numpy as np
from panda3d.core import CardMaker, NodePath, TransparencyAttrib

from space_flight import DATAFILES_PATH

MIN_DUST_ALPHA = 0.2
MAX_DUST_ALPHA = 0.8


class SpeedDustCloud:
    """
    A class to make a cloud of dust around the player
    to get them a feeling of their ship's speed

    Dust particles are sprites zooming past the player's ship
    """

    def __init__(
        self,
        game,
        num_particles: int = 100,
        spread: float = 30,
        depth: float = 100.0,
        colors: List = ["white"],
        *,
        defer_build: bool = False,
    ):
        # TODO: GPU-friendly loading of nodes (cf asteroids) or shader
        self.game = game
        self.spread = spread
        self.depth = depth
        self.id = uuid.uuid4()
        self.num_particles = num_particles

        self.particles = []

        self._cm = CardMaker("particle")
        self._cm.setFrame(-0.02, 0.02, -0.02, 0.02)

        # Create a dummy node at the player's ship location to attach the dust
        self.root = NodePath("speedDust")
        self.root.reparentTo(self.game.player.pawn.node)
        self.root.setTransparency(TransparencyAttrib.MAlpha)
        # Make that dust independent from scene lighting
        self.root.setLightOff()

        # Get the dust's colors
        self.colors = colors

        # Build now unless the caller wants to drive build() incrementally.
        if not defer_build:
            for _ in self.build():
                pass

    def build(self, chunk: int = 25):
        """
        Create the dust particles a chunk at a time, yielding after each chunk,
        then register the per-frame update once they all exist. Use with
        ``defer_build=True`` to spread the node creation across frames::

            self.speed_dust = SpeedDustCloud(game, defer_build=True, ...)
            yield from self.speed_dust.build()

        :param chunk: number of particles to create between yields
        """
        for i in range(self.num_particles):
            particle = self.root.attachNewNode(self._cm.generate())
            particle.setBillboardPointEye()
            self.init_particle(particle)
            self.particles.append(particle)
            if (i + 1) % chunk == 0:
                yield

        self.max_speed = self.game.player.pawn.max_speed_mps

        # Add the update task to the game's methods
        self.game.method_lists[self.id] = [self.dust_update]

    def init_particle(self, particle):
        """
        Initializes a particle with random color, scale and position

        :param particle: A panda3d card object to hold the particle
        """
        x = random.uniform(-self.spread, self.spread)
        z = random.uniform(-self.spread, self.spread)
        y = random.uniform(0, self.depth)
        scaling = random.uniform(0.5, 2.0)
        color = random.choice(self.colors)
        particle.setPos(x, y, z)
        particle.setTexture(
            self.game.app.asset_manager.get_asset(
                asset_type="texture",
                path=DATAFILES_PATH / f"sprites/dust/dust_{color}.png",
            ).get_texture()
        )
        particle.setScale(scaling, scaling, scaling)

    def reset_particle(self, particle):
        """
        Resets a particle upstream of the player, at a random transversal location

        :param particle: A panda3d card object to hold the particle
        """
        x = random.uniform(-self.spread, self.spread)
        z = random.uniform(-self.spread, self.spread)
        y = particle.getY() + self.depth
        particle.setPos(x, y, z)

    def dust_update(self):
        """
        Updates the position of all particles and resets them if need be.
        The dust's opacity increases with player speed to reinforce the feeling
        """
        dt = self.game.game_time.get_time_step()
        speed = np.linalg.norm(self.game.player.pawn.speed)
        alpha = (
            MIN_DUST_ALPHA + speed * (MAX_DUST_ALPHA - MIN_DUST_ALPHA) / self.max_speed
        )
        self.root.setAlphaScale(alpha)
        for particle in self.particles:
            particle.setY(particle.getY() - speed * dt)
            if particle.getY() < 0:
                self.reset_particle(particle)

    def clean(self):
        """
        Cleans the SpeedDustCloud object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.game = None
        for particle in self.particles:
            particle.removeNode()
        self.particles = None
        self.root.removeNode()
        self.root = None
