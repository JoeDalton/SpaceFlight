import logging

import numpy as np

from space_flight.actors.capital_ship.shield_model import ShieldModel
from space_flight.actors.destructibles import Destructible
from space_flight.game.collisions import (
    CollisionLayers,
    attach_collision_sphere,
    attach_collision_tube,
)
from space_flight.utils.state_machine import Cooldown, StateMachine

LOGGER = logging.getLogger()

# Regeneration cooldown after the last absorbed hit, in seconds. Doubled while
# the shield is down (collapsed), so a broken shield takes longer to reform.
_REGEN_COOLDOWN_S = 10.0
_DOWN_COOLDOWN_MULT = 2.0

# Durations of the fluid death (retract) and appearance (materialise) animations.
_DEATH_DURATION_S = 1.6
_APPEAR_DURATION_S = 1.6

# Shield lifecycle states.
_UP = "up"  # functional: blocks lasers, regenerates
_DYING = "dying"  # death (retract) animation playing; not functional
_DOWN = "down"  # collapsed: hidden, not functional, waiting to regen
_APPEARING = "appearing"  # materialise animation playing; not functional


class Shield(Destructible):
    """
    A protective bubble projected by a *group* of :class:`ShieldGenerator`\\ s.

    One shield is shared by all of a capital ship's shield generators. Its perks
    scale **pro rata** with the surviving generators: with ``initial`` generators
    and ``alive`` still standing, the fraction ``alive / initial`` multiplies both
    the maximum strength and the regeneration rate (so its current strength is
    clamped down as generators are destroyed). When the last generator -- or the
    ship itself -- is destroyed, the shield dies for good.

    This class is the shield's *game logic* -- strength, collision, lifecycle and
    the death/appearance state machine. Everything *visual* (the bubble mesh and
    its animated shader) lives in :class:`ShieldModel`, which this drives each
    frame; the two coincide because the collider is built from the same resolved
    dimensions the model exposes.

    The shield is a :class:`Destructible`, but its two failure modes are kept
    distinct:

    - *Destroyed*: every generator (or the ship it is mounted on) is destroyed.
      This is the only thing that ends the shield's life as a Destructible. The
      shield first plays its fluid *death* animation and only then reports zero
      to :meth:`get_health`, so the central death handling delays cleanup until
      the collapse has finished.
    - *Disabled*: its own strength pool reaches zero (worn down by hits, on top of
      any pro-rata reduction). The shield collapses (death animation) and stays
      *down* -- not protecting, hidden -- but alive. Once its regeneration cooldown
      elapses it strengthens again and *reappears* (the death animation played in
      reverse), coming back online.

    While either animation plays the shield is **not functional** (it blocks no
    lasers and is skipped in ``laser_into_shield`` via :attr:`is_enabled`).

    :param game: The game/flight state
    :param ship: The ship this shield is mounted on and protects
    :param generators: The shield generators projecting this shield. The shield's
        perks scale with how many of them are still alive.
    :param health: Full-strength (all generators alive) maximum strength
    :param regen_rate: Full-strength regeneration per second (after the cooldown)
    :param color: RGBA of the bubble -- RGB is the full-health tint, A the
        calm-interior opacity
    :param shape: Primitive geometry spec, e.g. ``{"type": "sphere",
        "radius_m": 90}`` or ``{"type": "tube", "point_a": [...], "point_b":
        [...], "radius_m": 40}``. Ignored when ``model`` is given.
    :param model: Path to a 3D model providing both the visible mesh and its
        (baked) collision geometry. Overrides ``shape`` when set.
    """

    def __init__(
        self,
        game,
        ship,
        generators,
        health: float = 4000.0,
        regen_rate: float = 0.0,
        color=None,
        shape: dict = None,
        model: str = None,
    ):
        super().__init__(game=game)
        self.name = "shield"
        # The ship this shield belongs to, and the generators projecting it.
        self.mounted_on = ship
        self.team = ship.team
        self.generators = list(generators)
        # How many generators projected the shield at full strength. Never zero,
        # so the pro-rata fraction is always well-defined.
        self.initial_generator_count = max(1, len(self.generators))
        self.is_dead = False
        self.is_clean = False

        # Strength pool. The *base* values are the full-strength perks; the
        # effective max_health / regen_rate are scaled each frame by the fraction
        # of generators still alive (see update).
        self.base_max_health = health
        self.base_regen_rate = regen_rate
        self.max_health = health
        self.health = self.max_health
        self.regen_rate = regen_rate
        self.is_enabled = True

        # --- Animation / lifecycle state ---
        self.state_sm = StateMachine(
            initial_state=_UP, clock=self.game.game_time.get_current_time
        )
        # uDeath in [0, 1]: 0 fully materialised (alive), 1 fully drained (gone).
        # Kept as an explicit float (not derived from time-in-state) so it stays
        # continuous when a death animation is interrupted by an appearance.
        self._u = 0.0
        # True once every generator/the ship is destroyed: we keep get_health
        # positive until the death animation finishes, then report zero.
        self._final_death = False
        # Regeneration waits a cooldown past the last absorbed hit (doubled while
        # the shield is down); ready before any hit is taken.
        self.regen_cooldown = Cooldown(
            duration_s=_REGEN_COOLDOWN_S,
            clock=self.game.game_time.get_current_time,
        )

        # Anchor node centred on the ship, holding both the visible bubble and the
        # collision solid so the two geometries coincide.
        self.node = ship.node.attachNewNode("shield_node")
        self.node.setPos(0, 0, 0)

        # The visible bubble + shader (all presentation lives here).
        self.model = ShieldModel(
            loader=game.app.loader,
            parent=self.node,
            color=color,
            shape=shape,
            model=model,
        )
        # Collision solid coinciding with the visible bubble.
        self.collision_np = None
        self._build_collision(model=model)

        # Regenerate and refresh our state every frame (we are our own Destructible)
        self.add_task(method=self.update)

    @property
    def state(self) -> str:
        """The shield lifecycle state (up / dying / down / appearing)."""
        return self.state_sm.state

    def _build_collision(self, model: str):
        """
        Attach the shield's collision solid, coinciding with the visible bubble.

        The dimensions come from :attr:`model` (resolved once when it built the
        mesh), so the collider always matches the visuals. A shared 3D ``model``
        carries its own (baked) collision geometry, which is re-masked as a shield
        collider and tagged with this shield as owner.

        :param model: The shared-model path (only used for the log message)
        """
        shape_type = self.model.shape_type
        if shape_type == "model":
            from_mask, into_mask, _ = CollisionLayers.define_collision_masks("shield")
            collision_nodes = self.model.visual.findAllMatches("**/+CollisionNode")
            if collision_nodes.isEmpty():
                LOGGER.warning("Shield model %s carries no collision geometry", model)
            for collision_np in collision_nodes:
                collision_np.node().setFromCollideMask(from_mask)
                collision_np.node().setIntoCollideMask(into_mask)
                collision_np.setPythonTag("owner", self)
        elif shape_type == "sphere":
            self.collision_np = attach_collision_sphere(
                game=self.game,
                name="shield",
                radius=self.model.radius_m,
                collider_type="shield",
                parent_node=self.node,
                parent_object=self,
            )
        elif shape_type == "tube":
            self.collision_np = attach_collision_tube(
                game=self.game,
                name="shield",
                point_a=self.model.point_a,
                point_b=self.model.point_b,
                radius=self.model.radius_m,
                collider_type="shield",
                parent_node=self.node,
                parent_object=self,
            )

    # ------------------------------------------------------------------
    # Damage
    # ------------------------------------------------------------------
    def take_hit(
        self, damage: float, normal_world_vector: np.ndarray, hit_world_point=None
    ):
        """
        Take damage from a laser hit against the shield and flash the impact.

        The impact normal is not used to jolt the shield (it is rigidly centred
        on the ship); it is kept for interface parity with other destructibles.

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        :param hit_world_point: The impact point in world coordinates, used to
            place the shader's impact flash (optional)
        """
        now = self.game.game_time.get_current_time()
        self.regen_cooldown.trigger()
        self.apply_damage(damage=damage, damage_type="physical")
        if hit_world_point is not None:
            self.model.add_impact(hit_world_point, self.game.root_node, now)

    def apply_damage(self, damage: float, damage_type: str):
        """
        Absorb damage into the shield's strength pool.

        :param damage: The amount of damage to apply
        :param damage_type: The type of damage to apply (physical, energy)
        """
        if damage_type == "physical":
            self.health -= damage
        else:
            raise NotImplementedError

    # ------------------------------------------------------------------
    # Lifecycle / animation
    # ------------------------------------------------------------------
    def _alive_generator_count(self) -> int:
        """Number of projecting generators still standing (not destroyed)."""
        count = 0
        for g in self.generators:
            if (
                g is not None
                and not getattr(g, "is_dead", False)
                and getattr(g, "health", 0.0) > 0.0
            ):
                count += 1
        return count

    def _owner_doomed(self) -> bool:
        """
        Whether the shield's life is over: the ship it protects is gone/about to
        be cleaned, or every generator has been destroyed. Detected the same frame
        the relevant health hits zero -- before the central death handling removes
        the ship node -- so we can reparent in time to play the death animation.
        """
        ship = self.mounted_on
        if (
            ship is None
            or getattr(ship, "is_dead", False)
            or getattr(ship, "health", 1.0) <= 0.0
        ):
            return True
        return self._alive_generator_count() == 0

    def _begin_death(self):
        """Start the fluid retraction (shield collapsing while still alive)."""
        self.model.place_sinks()
        # _u continues from its current value (0 when up)
        self.state_sm.request(_DYING, force=True)

    def _begin_appear(self):
        """Start the appearance animation (death played in reverse)."""
        self.model.place_sinks()
        self._u = 1.0
        self.state_sm.request(_APPEARING, force=True)

    def _begin_final_death(self):
        """
        Begin the terminal death: the generators/ship are gone, so after the
        retraction plays we report zero health and get cleaned. If the ship (our
        mount) is the one dying, reparent to the world root first -- preserving the
        world transform -- so the shield node survives the ship node's removal and
        can finish its animation.
        """
        self._final_death = True
        ship = self.mounted_on
        ship_doomed = (
            ship is None
            or getattr(ship, "is_dead", False)
            or getattr(ship, "health", 1.0) <= 0.0
        )
        if ship_doomed and self.node is not None and not self.node.isEmpty():
            self.node.wrtReparentTo(self.game.root_node)
        # Collapse from wherever we are now; only (re)seed sinks if not already
        # mid-animation, to avoid a discontinuity.
        if self.state == _UP:
            self.model.place_sinks()
        self.state_sm.request(_DYING, force=True)

    def update(self):
        """
        Advance the shield each frame: scale its perks to the surviving
        generators, run any death/appearance animation, handle depletion and
        cooldown-gated regeneration, refresh functional state and visibility, and
        drive the visual model's per-frame uniforms.
        """
        if self.node is None or self.model is None or self.model.visual is None:
            return
        dt = self.game.game_time.get_time_step()
        now = self.game.game_time.get_current_time()

        # Owner destroyed -> begin the terminal death (delays our own cleanup
        # until the retraction finishes; see get_health).
        if not self._final_death and self._owner_doomed():
            self._begin_final_death()

        # Advance whichever animation is playing.
        if self.state == _DYING:
            self._u = min(1.0, self._u + dt / _DEATH_DURATION_S)
            if self._u >= 1.0:
                self.state_sm.request(_DOWN, force=True)
        elif self.state == _APPEARING:
            self._u = max(0.0, self._u - dt / _APPEAR_DURATION_S)
            if self._u <= 0.0:
                self.state_sm.request(_UP, force=True)

        if not self._final_death:
            # Pro-rata perks: scale the maximum strength and regeneration by the
            # fraction of generators still alive, and clamp the current strength
            # down to the (possibly reduced) maximum.
            fraction = self._alive_generator_count() / self.initial_generator_count
            self.max_health = self.base_max_health * fraction
            self.regen_rate = self.base_regen_rate * fraction
            if self.health > self.max_health:
                self.health = self.max_health

            # Depleted while up -> collapse, then stay down until it regenerates.
            if self.state == _UP and self.health <= 0.0:
                self.health = 0.0
                self._begin_death()
            # Regenerate, but only after a cooldown since the last hit (doubled
            # while the shield is down).
            if self.regen_rate > 0.0 and self.health < self.max_health:
                multiplier = _DOWN_COOLDOWN_MULT if self.state != _UP else 1.0
                if self.regen_cooldown.ready(multiplier=multiplier):
                    self.health = min(
                        self.max_health, self.health + self.regen_rate * dt
                    )
            # Regeneration has brought it back -> materialise and come online.
            if self.state == _DOWN and self.health > 0.0:
                self._begin_appear()

        # Functional only when fully up; hidden only when fully collapsed.
        self.is_enabled = self.state == _UP
        self.set_visible(self.state != _DOWN)

        # Pushing per-frame shader uniforms is a pure rendering concern: no
        # camera and nothing to render headless.
        if self.game.headless:
            return
        health_frac = self.health / self.max_health if self.max_health > 0.0 else 0.0
        self.model.render(
            now=now,
            camera_pos=self.game.app.camera.getPos(self.game.root_node),
            health_frac=health_frac,
            death=self._u,
        )

    def set_visible(self, visible: bool):
        """
        Show or hide the shield bubble. Hiding does not disable the collider; a
        downed shield is instead ignored in ``laser_into_shield`` via
        :attr:`is_enabled`.

        :param visible: Whether the bubble should be rendered
        """
        if self.node is None:
            return
        if visible:
            self.node.show()
        else:
            self.node.hide()

    def get_health(self) -> float:
        """
        Report the shield's life to the death handler.

        The shield only *dies* (and is cleaned) when all its generators or its
        ship are destroyed, and even then not until its death animation has
        finished: while the terminal retraction plays this returns a positive
        value, delaying cleanup. Depleting the strength pool merely disables the
        shield, so that does not end its life here.

        :return: A positive value while the shield should live, else zero
        """
        if self._final_death and self.state == _DOWN:
            return 0.0
        return 1.0

    def get_shield_level(self) -> float:
        """
        The shield's current defensive strength, for the fleet AI's fighting-shape
        estimate.

        This is simply the current strength pool, which already reflects the
        pro-rata reduction from destroyed generators (its maximum, and hence this
        value, is scaled by the surviving fraction) and reads zero while the
        shield is down.

        :return: The shield's current strength (never negative)
        """
        return max(0.0, self.health)

    def play_death(self):
        """
        Play the shield's collapse.

        The fluid retraction is animated in :meth:`update` before this point (it
        is what delayed cleanup via :meth:`get_health`), so nothing more is needed
        here -- the bubble has already drained away.
        """
        pass

    def clean(self):
        """
        Clean references before deletion so the shield can be garbage collected.
        """
        if not self.is_clean:
            # Stop our per-frame tasks first, so nothing touches removed nodes
            self.clear_tasks()
            if self.node is not None:
                # Drop the owner ref on every shield collider (sphere/tube on the
                # anchor, or the model's baked collision nodes) so nothing dangles
                for collision_np in self.node.findAllMatches("**/+CollisionNode"):
                    collision_np.setPythonTag("owner", None)
                self.node.removeNode()
                self.node = None
            if self.model is not None:
                self.model.clean()
                self.model = None
            self.collision_np = None
            self.generators = []
            self.is_dead = True
            self.mounted_on = None
            self.game = None
            self.is_clean = True
