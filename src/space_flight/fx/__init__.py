from pathlib import Path

import numpy as np

from space_flight import DATAFILES_PATH
from space_flight.fx.explosions import ExplosionFire, ExplosionSmoke
from space_flight.fx.generic_fx_classes import EffectPool

# TODO : Load with asset manager ? Better management with a parent object ?


def load_explosion_effect_pools(game):
    tex_dir = Path(DATAFILES_PATH / "sprites/particles/black_smoke")
    game.smoke_pool = EffectPool(game=game, path=tex_dir, effect_class=ExplosionSmoke)
    tex_dir = Path(DATAFILES_PATH / "sprites/particles/explosion")
    game.fire_pool = EffectPool(game=game, path=tex_dir, effect_class=ExplosionFire)


def spawn_explosion(game, position: np.ndarray, scale: float, speed: np.ndarray):
    game.fire_pool.spawn(position=position, scale=scale, speed=speed)
    game.smoke_pool.spawn(position=position, scale=scale, speed=speed)


def clean_explosion_pools(game):
    game.smoke_pool.clean()
    game.fire_pool.clean()
    game.smoke_pool = None
    game.fire_pool = None
