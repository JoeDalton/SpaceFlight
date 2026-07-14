import numpy as np

from space_flight.game.collisions import attach_collision_sphere
from space_flight.weapons import Munition, Weapon

# Bombs are launched slowly along the belly (-Z); this base speed plus the ship's
# inherited velocity is the bomb's initial world velocity. Kept as a module global
# so the release solver (FighterNavigator.compute_release_condition) uses the exact
# same value the launcher does.
BOMB_SPEED_MPS = 75.0
# How far a bomb travels before expiring; sets its lifetime (range / speed).
BOMB_RANGE_M = 500.0
# Damage dealt on impact (heavy ordnance).
BOMB_DAMAGE = 4000.0
# Minimum time between two bomb drops (reload), so drops are spaced out rather than
# released on consecutive frames.
BASE_RELOAD_S = 0.5

# Placeholder visuals/collision: a small pink sphere.
BOMB_VISUAL_RADIUS_M = 0.5
BOMB_COLLISION_RADIUS_M = 0.5
BOMB_COLOR = (1.0, 0.4, 0.7, 1.0)


class BombLauncher(Weapon):
    """
    Launches bombs from a ship. The counterpart of :class:`~space_flight.actors.
    laser_cannon.LaserCannon` for the bomb weapon: it spawns a slow :class:`Bomb`
    dropped along the belly, rate-limited by a reload delay. Supply is tracked on
    the ship (Fighter.bomb_supply); this only spawns the projectile.
    """

    def __init__(self, game, parent, parent_node=None):
        super().__init__(game, parent, parent_node, fire_delay=BASE_RELOAD_S)

        self.range_m = BOMB_RANGE_M
        self.life_time_s = self.range_m / BOMB_SPEED_MPS
        self.power = BOMB_DAMAGE

    def launch(self) -> bool:
        """
        Drop a bomb: a slow projectile along the ship's belly (-Z) plus its
        inherited velocity (matching the navigator's release solver).

        :return: True if a bomb was released, False while the launcher is reloading
        """
        if not self._ready_to_fire():
            return False

        start_position = self.parent_node.get_pos(self.game.root_node)
        shot_speed = np.asarray(
            self.parent.speed, dtype=float
        ) - BOMB_SPEED_MPS * np.asarray(self.parent.up, dtype=float)

        self._spawn_munition(
            Bomb,
            start_position,
            shot_speed,
            self.power,
            self.life_time_s,
        )
        return True


class Bomb(Munition):
    """
    A bomb projectile: a slow, short-lived pink sphere with a small collision
    sphere. It inherits the whole projectile lifecycle from :class:`Munition` and
    only supplies its visual and collider, so it reuses the laser collision-damage
    handlers (via the shared origin_shippowerspeedshot interface).
    """

    def _build_visual(self, start_position):
        # Placeholder visual: a small pink sphere, flat-shaded.
        shot = self.game.app.loader.loadModel("models/misc/sphere")
        shot.reparent_to(self.game.root_node)
        shot.setPos(start_position)
        shot.set_scale(BOMB_VISUAL_RADIUS_M)
        shot.set_light_off()
        shot.set_color(*BOMB_COLOR)
        return shot

    def _attach_collider(self):
        # Small collision sphere (child of the visual, so removing the visual
        # removes the collider too).
        return attach_collision_sphere(
            game=self.game,
            name="bomb",
            radius=BOMB_COLLISION_RADIUS_M,
            collider_type="bomb",
            parent_node=self.shot,
            parent_object=self,
        )
