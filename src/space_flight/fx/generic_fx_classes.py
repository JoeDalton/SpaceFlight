from pathlib import Path

import numpy as np
from direct.interval.IntervalGlobal import LerpFunc
from panda3d.core import LPoint3, LVector3, NodePath


class Effect(NodePath):
    """
    A generic class for effects
    """

    def __init__(self, game, parent_pool):
        NodePath.__init__(self, "explosion_smoke")
        self.game = game
        self.parent_pool = parent_pool
        self.reparentTo(game.app.render)

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
        self.my_max_range_m = self.initial_speed * life_time_s
        traj = LerpFunc(
            self.trajectory,
            duration=life_time_s,
            fromData=0.0,
            toData=1.0,
        )
        self.game.interval_manager.play_interval(traj)

    def trajectory(self, t):
        """
        Parabolic decrease of velocity magnitude
        down to 0.5 of initial speed

        :param t: Normalized time in the LerpFunc duration
        """

        position_multiplier = 0.8 * (t - (t**3) / 3)
        advance = position_multiplier * self.my_max_range_m
        current_pos = self.start_pos + LVector3(*advance)
        self.setPos(current_pos)


class EffectPool:
    def __init__(self, game, path: Path, effect_class: Effect, initialize_size=20):
        self.game = game
        self.texture_pool = self.laser_texture = self.game.app.asset_manager.assets[
            path
        ]
        self.free = []
        self.used = []
        self.effect_class = effect_class

        for _ in range(initialize_size):
            effect = effect_class(
                game=game, parent_pool=self, texture_pool=self.texture_pool
            )
            self.free.append(effect)

    def spawn(self, position: np.ndarray, scale: float, speed: np.ndarray):
        if self.free:
            effect = self.free.pop()
        else:
            # Grow pool if it is exhausted
            effect = self.effect_class(
                game=self.game, parent_pool=self, texture_pool=self.texture_pool
            )
        effect.play(position=position, scale=scale, speed=speed)
        self.used.append(effect)
        return effect

    def release(self, effect):
        if effect in self.used:
            self.used.remove(effect)
        self.free.append(effect)
