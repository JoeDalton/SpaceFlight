from pathlib import Path

import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight import DATAFILES_PATH
from space_flight.fx.explosions import ExplosionFire, ExplosionSmoke
from space_flight.fx.generic_fx_classes import EffectPool


def load_explosion_effect_pools(app: ShowBase):
    tex_dir = Path(DATAFILES_PATH / "sprites/smokeParticleAssets/Black smoke")
    app.smoke_pool = EffectPool(
        app=app, texture_directory=tex_dir, effect_class=ExplosionSmoke
    )
    tex_dir = Path(DATAFILES_PATH / "sprites/smokeParticleAssets/Explosion")
    app.fire_pool = EffectPool(
        app=app, texture_directory=tex_dir, effect_class=ExplosionFire
    )


def spawn_explosion(
    app: ShowBase, position: np.ndarray, scale: float, speed: np.ndarray
):
    app.fire_pool.spawn(position=position, scale=scale, speed=speed)
    app.smoke_pool.spawn(position=position, scale=scale, speed=speed)
