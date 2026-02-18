from pathlib import Path

import numpy as np

from space_flight import DATAFILES_PATH
from space_flight.fx.explosions import ExplosionFire, ExplosionSmoke
from space_flight.fx.generic_fx_classes import EffectPool


def load_explosion_effect_pools(game):
    tex_dir = Path(DATAFILES_PATH / "sprites/smokeParticleAssets/Black smoke")
    game.smoke_pool = EffectPool(
        game=game, texture_directory=tex_dir, effect_class=ExplosionSmoke
    )
    tex_dir = Path(DATAFILES_PATH / "sprites/smokeParticleAssets/Explosion")
    game.fire_pool = EffectPool(
        game=game, texture_directory=tex_dir, effect_class=ExplosionFire
    )


def spawn_explosion(game, position: np.ndarray, scale: float, speed: np.ndarray):
    game.fire_pool.spawn(position=position, scale=scale, speed=speed)
    game.smoke_pool.spawn(position=position, scale=scale, speed=speed)
