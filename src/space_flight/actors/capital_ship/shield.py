import logging

import numpy as np
from panda3d.core import TransparencyAttrib

from space_flight.actors.capital_ship.shield_geometry import make_capsule
from space_flight.actors.destructibles import Destructible
from space_flight.game.collisions import (
    CollisionLayers,
    attach_collision_sphere,
    attach_collision_tube,
)

LOGGER = logging.getLogger()

# Default look of the shield bubble: a faint, semi-transparent blue.
_SHIELD_COLOR = (0.4, 0.8, 1.0, 0.15)
# Fallback primitive dimensions when the config omits them.
_DEFAULT_SPHERE_RADIUS_M = 90.0
_DEFAULT_TUBE_RADIUS_M = 40.0
_DEFAULT_TUBE_POINT_A = [0.0, 0.0, -50.0]
_DEFAULT_TUBE_POINT_B = [0.0, 0.0, 50.0]


class Shield(Destructible):
    """
    A protective bubble projected by a :class:`ShieldGenerator`.

    The shield is a :class:`Destructible`, but its two failure modes are kept
    distinct:

    - *Destroyed*: its generator is destroyed. This is the only thing that ends
      the shield's life as a Destructible, so :meth:`get_health` tracks the
      generator, not the strength pool. The central death handling then plays its
      death and cleans it.
    - *Disabled*: its own health (the damage-absorbing strength pool) reaches
      zero. The shield merely drops -- it stops protecting and is hidden -- but it
      stays alive and regenerates back up while its generator lives.

    Its geometry is configurable and its visible bubble always coincides with its
    collision solid (see :meth:`_build_geometry`): a ``sphere`` or ``tube``
    primitive, or a shared 3D ``model``. The geometry is anchored on the *ship*
    node, so the bubble encloses the whole hull rather than sitting at the
    generator's mounting point. The collider is into-only and only lasers touch
    it (ships and sensors fly through); ``laser_into_shield`` blocks a laser
    coming from outside and lets one fired from inside pass, routing absorbed
    hits to :meth:`take_hit`.

    :param game: The game/flight state
    :param generator: The shield generator projecting this shield
    :param health: Initial (and maximum) shield strength
    :param regen_rate: Strength regenerated per second while the generator lives
    :param color: RGBA colour of the semi-transparent bubble
    :param shape: Primitive geometry spec, e.g. ``{"type": "sphere",
        "radius_m": 90}`` or ``{"type": "tube", "point_a": [...], "point_b":
        [...], "radius_m": 40}``. Ignored when ``model`` is given.
    :param model: Path to a 3D model providing both the visible mesh and its
        (baked) collision geometry. Overrides ``shape`` when set.
    """

    def __init__(
        self,
        game,
        generator,
        health: float = 4000.0,
        regen_rate: float = 0.0,
        color=None,
        shape: dict = None,
        model: str = None,
    ):
        super().__init__(game=game)
        self.generator = generator
        self.name = "shield"
        self.team = generator.team
        # The ship this shield belongs to (the generator is mounted on it). Lets
        # owners_share_vehicle spare the ship's own turrets from hitting the
        # bubble (see laser_into_shield).
        self.mounted_on = generator.parent
        self.is_dead = False
        self.is_clean = False

        # Strength pool: absorbs damage, and disables the shield when depleted
        self.max_health = health
        self.health = self.max_health
        self.regen_rate = regen_rate
        self.is_enabled = True

        color = tuple(color) if color is not None else _SHIELD_COLOR

        # Anchor node centred on the *ship* (generator.parent is the ship, not the
        # generator's offset node), holding both the visible bubble and the
        # collision solid so the two geometries coincide.
        self.node = generator.parent.node.attachNewNode("shield_node")
        self.node.setPos(0, 0, 0)

        self.visual = None
        self.collision_np = None
        self._build_geometry(shape=shape or {}, model=model, color=color)

        # Regenerate and refresh our state every frame (we are our own Destructible)
        self.add_task(method=self.update)

    def _build_geometry(self, shape: dict, model: str, color):
        """
        Build the visible bubble and its matching collision solid under
        :attr:`node`. A shared ``model`` takes precedence; otherwise a ``sphere``
        or ``tube`` primitive is built from ``shape``.

        :param shape: Primitive geometry spec (see the class docstring)
        :param model: Optional shared model path
        :param color: RGBA colour of the bubble
        """
        if model:
            self._build_from_model(model, color)
            return

        shape_type = shape.get("type", "sphere")
        if shape_type == "sphere":
            self._build_sphere(shape, color)
        elif shape_type == "tube":
            self._build_tube(shape, color)
        else:
            raise ValueError(f"Unknown shield shape type {shape_type!r}")

    def _style_visual(self, visual, color, strip_texture: bool):
        """
        Apply the common semi-transparent look and parent the visual to
        :attr:`node`.

        :param visual: The visible geometry node path
        :param color: RGBA colour
        :param strip_texture: Whether to drop a baked texture (for stock models)
        """
        if strip_texture:
            visual.setTextureOff(1)
        visual.setColor(*color)
        visual.setTransparency(TransparencyAttrib.MAlpha)
        # Two-sided so the bubble is visible from inside as well
        visual.setTwoSided(True)
        visual.setShaderOff()
        visual.setLightOff()
        # Do not write depth: the bubble is see-through, so it must not occlude
        # what is behind it. Without this, other transparent objects (e.g. clouds)
        # drawn after the shield fail the depth test against the shield and vanish.
        visual.setDepthWrite(False)
        visual.reparentTo(self.node)

    def _build_sphere(self, shape: dict, color):
        """
        Build a spherical shield: a stock unit sphere scaled to the radius, with a
        matching :class:`CollisionSphere` on the (unscaled) anchor node.

        :param shape: Sphere spec, reads ``radius_m``
        :param color: RGBA colour
        """
        radius_m = shape.get("radius_m", _DEFAULT_SPHERE_RADIUS_M)
        self.visual = self.game.app.loader.loadModel("models/misc/smiley")
        self.visual.setScale(radius_m)
        self._style_visual(self.visual, color, strip_texture=True)
        self.collision_np = attach_collision_sphere(
            game=self.game,
            name="shield",
            radius=radius_m,
            collider_type="shield",
            parent_node=self.node,
            parent_object=self,
        )

    def _build_tube(self, shape: dict, color):
        """
        Build a tubular (capsule) shield: a generated capsule mesh with a matching
        :class:`CollisionTube` sharing the same end centres and radius.

        :param shape: Tube spec, reads ``point_a``, ``point_b`` and ``radius_m``
        :param color: RGBA colour
        """
        point_a = shape.get("point_a", _DEFAULT_TUBE_POINT_A)
        point_b = shape.get("point_b", _DEFAULT_TUBE_POINT_B)
        radius_m = shape.get("radius_m", _DEFAULT_TUBE_RADIUS_M)
        self.visual = make_capsule(point_a=point_a, point_b=point_b, radius=radius_m)
        self._style_visual(self.visual, color, strip_texture=False)
        self.collision_np = attach_collision_tube(
            game=self.game,
            name="shield",
            point_a=point_a,
            point_b=point_b,
            radius=radius_m,
            collider_type="shield",
            parent_node=self.node,
            parent_object=self,
        )

    def _build_from_model(self, model: str, color):
        """
        Build the shield from a shared 3D model: the model's mesh is the visible
        bubble and its (baked) collision geometry is re-masked as a shield and
        tagged with this shield as owner. The model is expected to carry collision
        geometry matching its visible mesh.

        :param model: Path to the model
        :param color: RGBA colour
        """
        self.visual = self.game.app.loader.loadModel(model)
        self._style_visual(self.visual, color, strip_texture=False)

        from_mask, into_mask, _ = CollisionLayers.define_collision_masks("shield")
        collision_nodes = self.visual.findAllMatches("**/+CollisionNode")
        if collision_nodes.isEmpty():
            LOGGER.warning("Shield model %s carries no collision geometry", model)
        for collision_np in collision_nodes:
            collision_np.node().setFromCollideMask(from_mask)
            collision_np.node().setIntoCollideMask(into_mask)
            collision_np.setPythonTag("owner", self)

    def take_hit(self, damage: float, normal_world_vector: np.ndarray):
        """
        Take damage from a hit against the shield.

        The impact normal is not used to jolt the shield (it is rigidly centred
        on the ship); it is kept for interface parity with other destructibles.

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        """
        self.apply_damage(damage=damage, damage_type="physical")

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

    def update(self):
        """
        Regenerate the strength pool and refresh the shield's enabled state and
        visibility. Called every frame while the shield lives.
        """
        # A dead/gone generator means we are about to be cleaned; do nothing
        if self.generator is None or self.generator.is_dead:
            return
        # Regenerate while the generator lives
        if self.regen_rate > 0.0 and self.health < self.max_health:
            dt = self.game.game_time.get_time_step()
            self.health = min(self.max_health, self.health + self.regen_rate * dt)
        # A depleted shield is disabled (down); any positive strength brings it up
        self.is_enabled = self.health > 0.0
        self.set_visible(self.is_enabled)

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

        The shield only *dies* (and is cleaned) with its generator; depleting its
        strength pool merely disables it (see class docstring), so this does not
        return :attr:`health`.

        :return: A positive value while the generator lives, else zero
        """
        if self.generator is None or self.generator.is_dead:
            return 0.0
        return 1.0

    def play_death(self):
        """
        Play the shield's collapse animation.

        Nothing fancy for now: the bubble simply vanishes when it is cleaned.
        """
        # TODO: a shield-collapse effect (flash / ripple) would go here
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
            self.visual = None
            self.collision_np = None
            self.is_dead = True
            self.generator = None
            self.mounted_on = None
            self.game = None
            self.is_clean = True
