from pathlib import Path

import numpy as np
from direct.interval.IntervalGlobal import LerpFunc
from panda3d.core import LPoint3, LVector3, NodePath


class Effect(NodePath):
    """
    A generic class for effects
    """

    def __init__(self, app, parent_pool):
        NodePath.__init__(self, "explosion_smoke")
        self.app = app
        self.parent_pool = parent_pool
        self.reparentTo(app.render)

    def play(self):
        raise NotImplementedError

    def release(self):
        self.hide()
        self.parent_pool.release(effect=self)

    def set_linear_decelerated_trajectory(
        self, life_time_s: float, position: np.ndarray, speed: np.ndarray
    ):
        self.start_pos = LPoint3(*position)
        self.initial_speed = speed
        self.life_time_s = life_time_s
        self.my_max_range_m = self.initial_speed * self.life_time_s

        LerpFunc(
            self.trajectory,
            duration=self.life_time_s,
            fromData=0.0,
            toData=1.0,
        )

    def trajectory(self, t):
        """
        Parabolic decrease of velocity magnitude
        down to 0.5 of initial speed

        # TODO does not seem to work.

        :param t: _description_
        """
        t_reduced = t / self.life_time_s
        position_multiplier = t_reduced  # - (t_reduced**3)/6
        current_pos = self.start_pos + position_multiplier * LVector3(*self.my_range_m)
        # self.setPos(current_pos)
        print(current_pos)
        self.set_pos(self.start_pos)


class EffectPool:
    def __init__(
        self, app, texture_directory: Path, effect_class: Effect, initialize_size=20
    ):
        self.app = app
        self.build_texture_pool(texture_directory)
        self.free = []
        self.used = []
        self.effect_class = effect_class

        for _ in range(initialize_size):
            effect = effect_class(
                app=app, parent_pool=self, texture_pool=self.texture_pool
            )
            self.free.append(effect)

    def spawn(self, position: np.ndarray, scale: float, speed: np.ndarray):
        if self.free:
            effect = self.free.pop()
        else:
            # Grow pool if it is exhausted
            effect = self.effect_class(
                app=self.app, parent_pool=self, texture_pool=self.texture_pool
            )
        effect.play(position=position, scale=scale, speed=speed)
        self.used.append(effect)
        return effect

    def release(self, effect):
        if effect in self.used:
            self.used.remove(effect)
        self.free.append(effect)

    def build_texture_pool(self, texture_directory: Path):
        pattern = "*.png"
        texture_files = list(texture_directory.glob(pattern))
        self.texture_pool = []
        for file in texture_files:
            self.texture_pool.append(self.app.loader.loadTexture(file))
