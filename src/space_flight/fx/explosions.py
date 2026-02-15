import random
from typing import List

import numpy as np
from direct.interval.IntervalGlobal import Func, LerpFunc, Parallel, Sequence, Wait
from direct.showbase.ShowBase import ShowBase
from panda3d.core import CardMaker, TransparencyAttrib, Vec4

from space_flight.fx.generic_fx_classes import Effect, EffectPool

TRAJECTORY_LIFE_TIME_S = 5.0
FIRE_EXPANSION_TIME_S = 2.0
FIRE_FADE_DELAY_S = 0.5
SMOKE_EXPANSION_TIME_S = 4
SMOKE_DELAY_S = 0.5


class ExplosionSmoke(Effect):
    def __init__(
        self,
        app: ShowBase,
        parent_pool: EffectPool,
        texture_pool: List,
        n_layer: int = 12,
    ):
        Effect.__init__(self, app=app, parent_pool=parent_pool)

        self.layers = []

        for _ in range(n_layer):
            cm = CardMaker("smoke_layer")
            cm.setFrame(-1, 1, -1, 1)
            layer = self.attachNewNode(cm.generate())

            texture = random.choice(texture_pool)
            layer.setTexture(texture)
            layer.setTransparency(TransparencyAttrib.MAlpha)
            layer.setDepthWrite(False)
            layer.setBin("fixed", 1)
            layer.setBillboardPointEye()

            scale = random.uniform(0.5, 1.0)
            layer.setScale(scale)
            layer.setPos(
                random.uniform(-0.5, 0.5),
                random.uniform(-0.5, 0.5),
                random.uniform(-0.5, 0.5),
            )

            # Smoky gray with soft alpha
            layer.setColor(0.4, 0.4, 0.4, 0.3)

            self.layers.append(layer)

        # Fade out late
        self.appear_ival = self.colorScaleInterval(
            SMOKE_EXPANSION_TIME_S / 2,
            Vec4(1, 1, 1, 1),
            startColorScale=Vec4(1, 1, 1, 0),
        )

        # Expand slowly
        self.scale_ival = self.scaleInterval(
            SMOKE_EXPANSION_TIME_S, 10, startScale=3, blendType="easeOut"
        )

        # Fade out late
        self.fade_ival = self.colorScaleInterval(
            SMOKE_EXPANSION_TIME_S / 2,
            Vec4(1, 1, 1, 0),
            startColorScale=Vec4(1, 1, 1, 1),
        )
        # Hide before use
        self.hide()

    def play(self, position: np.ndarray, scale: float, speed: np.ndarray):
        self.setScale(scale)
        # self.setPos(*position)
        self.set_linear_decelerated_trajectory(
            life_time_s=TRAJECTORY_LIFE_TIME_S, position=position, speed=speed
        )
        sequence = Sequence(
            Wait(SMOKE_DELAY_S),
            Func(self.show),
            Parallel(
                self.scale_ival,
                Sequence(self.appear_ival, self.fade_ival),
            ),
            Func(self.release),
        )
        self.app.interval_manager.play_interval(sequence)


class ExplosionFire(Effect):
    """
    _summary_

    TODO add light source ?
    """

    def __init__(
        self,
        app: ShowBase,
        parent_pool: EffectPool,
        texture_pool: List,
        n_layer: int = 12,
    ):
        Effect.__init__(self, app=app, parent_pool=parent_pool)

        self.layers = []

        for _ in range(n_layer):
            cm = CardMaker("smoke_layer")
            cm.setFrame(-1, 1, -1, 1)
            layer = self.attachNewNode(cm.generate())

            texture = random.choice(texture_pool)
            layer.setTexture(texture)
            layer.setTransparency(TransparencyAttrib.MAlpha)
            layer.setDepthWrite(False)
            layer.setBin("fixed", 0)
            layer.setBillboardPointEye()

            scale = random.uniform(0.5, 1.0)
            layer.setScale(scale)
            layer.setPos(
                random.uniform(-0.5, 0.5),
                random.uniform(-0.5, 0.5),
                random.uniform(-0.5, 0.5),
            )

            layer.setColor(1, 0.6, 0.2, 0.7)

            self.layers.append(layer)

        self.scale_ival = LerpFunc(
            self.scale_curve, duration=FIRE_EXPANSION_TIME_S, fromData=0.0, toData=1.0
        )

        # Fade out late
        fade_time_s = FIRE_EXPANSION_TIME_S - FIRE_FADE_DELAY_S
        self.fade_ival = self.colorScaleInterval(
            fade_time_s, Vec4(1, 1, 1, 0), startColorScale=Vec4(1, 1, 1, 1)
        )

        # Don't rely on scene lighting since explosions emit their own light
        self.set_light_off()

        # Hide before use
        self.hide()

    def scale_curve(self, t):
        # Fast initial impulse, asymptotic slowdown
        eased = t / (t + 0.25)  # hyperbolic
        scale = 0.1 + eased * (5.0 - 0.1)
        self.setScale(scale)

    def play(self, position: np.ndarray, scale: float, speed: np.ndarray):
        self.setScale(scale)
        self.set_linear_decelerated_trajectory(
            life_time_s=TRAJECTORY_LIFE_TIME_S, position=position, speed=speed
        )
        sequence = Sequence(
            Func(self.show),
            Parallel(
                self.scale_ival,
                Sequence(Wait(FIRE_FADE_DELAY_S), self.fade_ival),
            ),
            Func(self.release),
        )
        self.app.interval_manager.play_interval(sequence)
