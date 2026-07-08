"""
Shield presentation: the visible bubble mesh + its animated GLSL shader.

This module owns everything *visual* about a shield, kept separate from the
game-logic :class:`~space_flight.actors.capital_ship.shield.Shield` (health,
collision, lifecycle). It bundles two things:

- :func:`make_capsule` -- the procedural capsule mesh used by ``tube`` shields
  (there is no stock capsule model), whose surface matches a ``CollisionTube``.
- :class:`ShieldModel` -- the visible bubble: it builds the geometry
  (``sphere`` / ``tube`` primitive or a shared ``model``), applies
  ``datafiles/shaders/shield.{vert,frag}``, and drives its uniforms for the
  living look (morphing energy field, fresnel rim, health-driven tint), the
  impact flashes, and the fluid death/appearance retraction.

:class:`ShieldModel` deliberately depends only on a Panda3D ``loader`` and a
parent ``NodePath`` -- not on the game -- so the presentation can be reasoned
about (and reused) in isolation. All per-frame state it needs (time, camera
position, health fraction, death progress) is passed in by the owning Shield.
"""

import logging
import random

import numpy as np
from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexReader,
    GeomVertexWriter,
    LVecBase4f,
    NodePath,
    PTA_LVecBase4f,
    Shader,
    TransparencyAttrib,
    Vec3,
)

from space_flight import DATAFILES_PATH

LOGGER = logging.getLogger()

# --- Default look of the shield bubble --------------------------------------
# RGB is the *full-health* tint; alpha is the calm-interior opacity (uBaseAlpha).
# The mid/low tints are blended in as health drops (blue -> violet -> pink).
_SHIELD_COLOR = (0.30, 0.70, 1.0, 0.06)
_SHIELD_COLOR_MID = (0.75, 0.50, 1.0)  # tint at half health
_SHIELD_COLOR_LOW = (0.875, 0.45, 0.70)  # tint at zero health

# Surface-field density, in pattern cycles across the bubble's radius. Higher =
# finer texture; tuned so the field still reads at capital-ship scale/distance.
_PATTERN_CYCLES = 10.0
_WARP = 1.5  # domain-warp strength (how much the field morphs)
_SPEED = 0.25  # field animation speed (low = slow morph)
_PULSE_SPEED = 1.4  # gentle "breathing" rate
_PULSE_DEPTH = 0.20  # breathing depth (0 = steady)
_FRESNEL_POWER = 3.0  # rim tightness
_FRESNEL_GAIN = 0.75  # rim brightness
_INTERIOR_GLOW = 0.12  # interior base brightness (flat term)
_PATTERN_GAIN = 0.55  # interior brightness driven by the field
_PATTERN_ALPHA = 0.12  # how much the field firms up the opacity
_IMPACT_WHITEN = 0.45  # white-hotness of an impact flash

# Impact-flash scales: radius as a fraction of the bubble radius, decay in 1/s.
_IMPACT_RADIUS_FRAC = 0.22
_IMPACT_DECAY = 3.5

# Fluid death/appearance look knobs. The *_FRAC ones scale with the radius.
_DEATH_EDGE_FRAC = 0.05  # coverage-boundary softness
_DEATH_WOBBLE_FRAC = 3.0  # boundary roughness amplitude (low-freq lumpy drops)
_DEATH_BEAD_FRAC = 0.05  # meniscus width
_DEATH_WHITEN = 0.35  # meniscus whiteness
_COVER_MARGIN = 1.08  # coverage-radius margin at death start
_DEATH_FADE_START = 0.80  # uDeath at which the last remnants start to fade

# Fallback primitive dimensions when the config omits them.
_DEFAULT_SPHERE_RADIUS_M = 90.0
_DEFAULT_TUBE_RADIUS_M = 40.0
_DEFAULT_TUBE_POINT_A = [0.0, 0.0, -50.0]
_DEFAULT_TUBE_POINT_B = [0.0, 0.0, 50.0]

# GPU-buffer sizes (must match shield.frag's MAX_IMPACTS / MAX_SINKS).
_MAX_IMPACTS = 16
_MAX_SINKS = 12
_NUM_SINKS = 6  # retraction/emergence points used per animation
_IMPACT_LIFE_S = 2.0  # seconds an impact flash lingers
# Cap on how many surface vertices we keep for sink placement / calibration.
_MAX_SURFACE_SAMPLES = 1500

# The shield shader is shared by every bubble; load it once, lazily.
_SHIELD_SHADER = None


def _shield_shader():
    """Load (once) and return the shared shield GLSL shader."""
    global _SHIELD_SHADER
    if _SHIELD_SHADER is None:
        _SHIELD_SHADER = Shader.load(
            Shader.SL_GLSL,
            vertex=DATAFILES_PATH / "shaders/shield.vert",
            fragment=DATAFILES_PATH / "shaders/shield.frag",
        )
    return _SHIELD_SHADER


def make_capsule(
    point_a,
    point_b,
    radius: float,
    num_segments: int = 24,
    num_rings: int = 8,
) -> NodePath:
    """
    Build a capsule mesh matching a ``CollisionTube``.

    The capsule is a cylinder between ``point_a`` and ``point_b`` capped by a
    hemisphere of ``radius`` at each end, i.e. the exact surface of the tube whose
    hemisphere centres are ``point_a`` and ``point_b``.

    :param point_a: Centre of the first end hemisphere (x, y, z)
    :param point_b: Centre of the second end hemisphere (x, y, z)
    :param radius: The capsule radius
    :param num_segments: Longitudinal subdivisions (around the axis)
    :param num_rings: Latitude subdivisions per hemisphere
    :return: A NodePath holding the generated capsule geometry
    """
    a = np.asarray(point_a, dtype=float)
    b = np.asarray(point_b, dtype=float)
    axis = b - a
    length = np.linalg.norm(axis)
    axis_dir = axis / length if length > 1e-9 else np.array([0.0, 0.0, 1.0])

    # Two unit vectors perpendicular to the axis, to sweep each ring around it
    reference = (
        np.array([1.0, 0.0, 0.0])
        if abs(axis_dir[0]) < 0.9
        else np.array([0.0, 1.0, 0.0])
    )
    u = np.cross(axis_dir, reference)
    u /= np.linalg.norm(u)
    v = np.cross(axis_dir, u)

    vdata = GeomVertexData("capsule", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vertex_writer = GeomVertexWriter(vdata, "vertex")
    normal_writer = GeomVertexWriter(vdata, "normal")

    # Latitude rings run from the bottom pole (phi = -pi/2) to the top pole
    # (phi = +pi/2). The lower half belongs to the hemisphere centred at a, the
    # upper half to the one centred at b; the jump of centre at the equator is
    # exactly the cylinder body.
    total_latitude = 2 * num_rings
    rings = []
    index = 0
    for i in range(total_latitude + 1):
        phi = -np.pi / 2.0 + np.pi * (i / total_latitude)
        center = a if phi <= 0.0 else b
        ring = []
        for j in range(num_segments + 1):
            theta = 2.0 * np.pi * (j / num_segments)
            radial = np.cos(theta) * u + np.sin(theta) * v
            outward = np.cos(phi) * radial + np.sin(phi) * axis_dir
            position = center + radius * outward
            vertex_writer.addData3(*position)
            normal_writer.addData3(*outward)
            ring.append(index)
            index += 1
        rings.append(ring)

    triangles = GeomTriangles(Geom.UHStatic)
    for i in range(total_latitude):
        lower = rings[i]
        upper = rings[i + 1]
        for j in range(num_segments):
            triangles.addVertices(lower[j], upper[j], lower[j + 1])
            triangles.addVertices(lower[j + 1], upper[j], upper[j + 1])

    geom = Geom(vdata)
    geom.addPrimitive(triangles)
    node = GeomNode("capsule")
    node.addGeom(geom)
    return NodePath(node)


class ShieldModel:
    """
    The visible shield bubble and its animated shader.

    Builds the bubble geometry -- a ``sphere`` or ``tube`` primitive, or a shared
    3D ``model`` -- under ``parent``, applies the shield shader, and exposes a
    small API the owning Shield drives each frame:

    - :meth:`render` pushes the per-frame uniforms (time, camera, health tint,
      death progress) and the live impact flashes.
    - :meth:`add_impact` records a laser hit so the surface flashes there.
    - :meth:`place_sinks` seeds the random points the fluid retracts into / grows
      out of (used at the start of a death or appearance animation).

    The resolved primitive dimensions are exposed (:attr:`shape_type`,
    :attr:`radius_m`, :attr:`point_a`, :attr:`point_b`) so the Shield can build a
    collision solid that coincides with this mesh without re-parsing the config.

    :param loader: Panda3D loader (``game.app.loader``) for stock/shared models
    :param parent: Node to attach the visible bubble under (the Shield's anchor)
    :param color: RGBA of the bubble -- RGB is the full-health tint, A the
        calm-interior opacity. Defaults to :data:`_SHIELD_COLOR`.
    :param shape: Primitive geometry spec, e.g. ``{"type": "sphere",
        "radius_m": 90}`` or ``{"type": "tube", "point_a": [...],
        "point_b": [...], "radius_m": 40}``. Ignored when ``model`` is given.
    :param model: Path to a 3D model providing both the visible mesh and its
        (baked) collision geometry. Overrides ``shape`` when set.
    :raises ValueError: if ``shape["type"]`` is not ``sphere`` or ``tube``.
    """

    def __init__(
        self, loader, parent, color=None, shape: dict = None, model: str = None
    ):
        color = tuple(color) if color is not None else _SHIELD_COLOR
        shape = shape or {}

        # Resolved geometry (filled by _build); exposed for the matching collider.
        self.shape_type = None
        self.radius_m = None
        self.point_a = None
        self.point_b = None

        self.visual = None
        # The GeomNode whose local space is the shader's vObjPos -- the space in
        # which sinks and impacts are expressed.
        self.geom_np = None
        self.local_radius = 1.0

        # Impact flashes + retraction sinks, uploaded to the shader as arrays.
        self._impacts = []  # list of (Vec3 geometry-space pos, float start_time)
        self._impact_pta = PTA_LVecBase4f.emptyArray(_MAX_IMPACTS)
        self._sink_pta = PTA_LVecBase4f.emptyArray(_MAX_SINKS)
        self._surface_points = []

        self._build(loader, parent, shape, model)
        self._read_surface_points()
        self._apply_shader(color)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------
    def _build(self, loader, parent, shape: dict, model: str):
        """Build the bubble geometry and record its resolved dimensions."""
        if model:
            self.shape_type = "model"
            self.visual = loader.loadModel(model)
            self._style(parent, strip_texture=False)
            return

        shape_type = shape.get("type", "sphere")
        if shape_type == "sphere":
            self.shape_type = "sphere"
            self.radius_m = shape.get("radius_m", _DEFAULT_SPHERE_RADIUS_M)
            # Stock unit sphere scaled to the radius.
            self.visual = loader.loadModel("models/misc/smiley")
            self.visual.setScale(self.radius_m)
            self._style(parent, strip_texture=True)
        elif shape_type == "tube":
            self.shape_type = "tube"
            self.point_a = shape.get("point_a", _DEFAULT_TUBE_POINT_A)
            self.point_b = shape.get("point_b", _DEFAULT_TUBE_POINT_B)
            self.radius_m = shape.get("radius_m", _DEFAULT_TUBE_RADIUS_M)
            self.visual = make_capsule(
                point_a=self.point_a, point_b=self.point_b, radius=self.radius_m
            )
            self._style(parent, strip_texture=False)
        else:
            raise ValueError(f"Unknown shield shape type {shape_type!r}")

    def _style(self, parent, strip_texture: bool):
        """
        Apply the common translucent render state and parent the bubble. The
        shader is applied separately (transparency must be set first, or Panda3D's
        automatic shader generator activates and conflicts with it).
        """
        v = self.visual
        if strip_texture:
            v.setTextureOff(1)
        v.setTransparency(TransparencyAttrib.MAlpha)
        v.setLightOff()
        # Two-sided so the bubble reads from outside AND from inside, and
        # depth-write OFF so it blends as a true translucent surface (a two-sided
        # sphere that wrote depth would self-occlude along its seam, and would
        # occlude whatever is behind it outright rather than letting it show
        # through). It keeps depth-testing, so opaque geometry in front hides it.
        v.setTwoSided(True)
        v.setDepthWrite(False)
        # Draw after the clouds (which sit in the "fixed" bin at sort 50, also
        # depth-write off): the translucent shield then composites *over* the
        # clouds, so a cloud behind it shows through dimmed instead of painting
        # on top -- and, being mostly transparent, it barely tints a cloud in
        # front. This is what keeps clouds from always covering the shield.
        v.setBin("fixed", 60)
        v.reparentTo(parent)

    def _read_surface_points(self):
        """
        Read the bubble's surface vertices in the geometry's local space -- the
        same space the shader sees as ``vObjPos`` and in which sinks/impacts are
        expressed -- and derive the local radius. Records :attr:`geom_np` (used to
        map world hit points into that space). Down-samples to bound later cost.
        """
        node = self.visual.node()
        if node.isOfType(GeomNode.getClassType()):
            geom_np = self.visual
        else:
            geom_np = self.visual.find("**/+GeomNode")
        self.geom_np = geom_np

        points = []
        if geom_np is None or geom_np.isEmpty():
            LOGGER.warning("Shield visual carries no renderable geometry")
            self._surface_points = points
            self.local_radius = 1.0
            return
        geom_node = geom_np.node()
        for gi in range(geom_node.getNumGeoms()):
            vdata = geom_node.getGeom(gi).getVertexData()
            reader = GeomVertexReader(vdata, "vertex")
            while not reader.isAtEnd():
                points.append(Vec3(reader.getData3()))
        if len(points) > _MAX_SURFACE_SAMPLES:
            stride = len(points) // _MAX_SURFACE_SAMPLES + 1
            points = points[::stride]

        center = Vec3(0, 0, 0)
        for p in points:
            center += p
        if points:
            center /= len(points)
        self.local_radius = (
            max((p - center).length() for p in points) if points else 1.0
        )
        self._surface_points = points

    # ------------------------------------------------------------------
    # Shader
    # ------------------------------------------------------------------
    def _apply_shader(self, color):
        """
        Apply the shield shader and seed all its uniforms. Sizes the
        pattern/impact/death scales from the geometry's own radius so the look is
        consistent for any shield shape or modelling scale.
        """
        lr = self.local_radius
        r, g, b = color[0], color[1], color[2]
        base_alpha = color[3] if len(color) > 3 else _SHIELD_COLOR[3]

        v = self.visual
        v.setShader(_shield_shader())
        # Look knobs
        v.setShaderInput("uColorFull", Vec3(r, g, b))
        v.setShaderInput("uColorMid", Vec3(*_SHIELD_COLOR_MID))
        v.setShaderInput("uColorLow", Vec3(*_SHIELD_COLOR_LOW))
        v.setShaderInput("uHealth", 1.0)
        v.setShaderInput("uBaseAlpha", base_alpha)
        v.setShaderInput("uPatternFreq", _PATTERN_CYCLES / lr)
        v.setShaderInput("uWarp", _WARP)
        v.setShaderInput("uSpeed", _SPEED)
        v.setShaderInput("uPulseSpeed", _PULSE_SPEED)
        v.setShaderInput("uPulseDepth", _PULSE_DEPTH)
        v.setShaderInput("uFresnelPower", _FRESNEL_POWER)
        v.setShaderInput("uFresnelGain", _FRESNEL_GAIN)
        v.setShaderInput("uInteriorGlow", _INTERIOR_GLOW)
        v.setShaderInput("uPatternGain", _PATTERN_GAIN)
        v.setShaderInput("uPatternAlpha", _PATTERN_ALPHA)
        v.setShaderInput("uImpactWhiten", _IMPACT_WHITEN)
        # Impacts
        v.setShaderInput("uImpactRadius", _IMPACT_RADIUS_FRAC * lr)
        v.setShaderInput("uImpactDecay", _IMPACT_DECAY)
        v.setShaderInput("uImpactLife", _IMPACT_LIFE_S)
        v.setShaderInput("uImpacts", self._impact_pta)
        v.setShaderInput("uImpactCount", 0)
        # Per-frame scene inputs (seeded; refreshed in render())
        v.setShaderInput("iTime", 0.0)
        v.setShaderInput("iCameraPos", Vec3(0, 0, 0))
        # Death / appearance
        v.setShaderInput("uDeath", 0.0)
        v.setShaderInput("uSinks", self._sink_pta)
        v.setShaderInput("uSinkCount", 0)
        v.setShaderInput("uMaxReach", lr)
        v.setShaderInput("uDeathEdge", _DEATH_EDGE_FRAC * lr)
        v.setShaderInput("uDeathWobble", _DEATH_WOBBLE_FRAC * lr)
        v.setShaderInput("uDeathBead", _DEATH_BEAD_FRAC * lr)
        v.setShaderInput("uDeathWhiten", _DEATH_WHITEN)
        v.setShaderInput("uCoverMargin", _COVER_MARGIN)
        v.setShaderInput("uDeathFadeStart", _DEATH_FADE_START)

    # ------------------------------------------------------------------
    # Per-frame API driven by the owning Shield
    # ------------------------------------------------------------------
    def place_sinks(self):
        """
        Pick random surface points as the retraction/emergence sinks, upload them,
        and calibrate ``uMaxReach`` (the largest distance from any surface point
        to its nearest sink) so death=0 is fully covered and death=1 fully gone.
        """
        points = self._surface_points
        if not points or self.visual is None:
            return
        count = min(_NUM_SINKS, len(points))
        sinks = random.sample(points, count)
        for i in range(_MAX_SINKS):
            if i < count:
                s = sinks[i]
                self._sink_pta.setElement(i, LVecBase4f(s.x, s.y, s.z, 0.0))
            else:
                self._sink_pta.setElement(i, LVecBase4f(0, 0, 0, 0))

        max_reach_sq = 0.0
        for p in points:
            nearest_sq = min((p - s).lengthSquared() for s in sinks)
            max_reach_sq = max(max_reach_sq, nearest_sq)
        max_reach = max_reach_sq**0.5

        self.visual.setShaderInput("uSinks", self._sink_pta)
        self.visual.setShaderInput("uSinkCount", count)
        self.visual.setShaderInput("uMaxReach", max_reach)

    def add_impact(self, world_point, root, now: float):
        """
        Register a laser impact so the shader flashes the bubble where it was hit.

        :param world_point: The impact point in world space
        :param root: The world root node (to convert the point into the
            geometry-local space the shader's ``uImpacts`` expects)
        :param now: Current time, stamped as the flash's start
        """
        if self.geom_np is None or self.geom_np.isEmpty():
            return
        local = self.geom_np.getRelativePoint(root, world_point)
        self._impacts.append((Vec3(local), now))
        if len(self._impacts) > _MAX_IMPACTS:
            self._impacts.pop(0)

    def render(self, now: float, camera_pos, health_frac: float, death: float):
        """
        Refresh the per-frame shader uniforms: time, camera position (for the
        fresnel rim), the health-driven tint, the death/appearance progress, and
        the live impact flashes (dropping any that have expired).

        :param now: Current time (seconds)
        :param camera_pos: Camera position in world space
        :param health_frac: Shield strength fraction in [0, 1] (drives the tint)
        :param death: Death/appearance progress in [0, 1] (0 alive, 1 gone)
        """
        v = self.visual
        if v is None:
            return
        v.setShaderInput("iTime", now)
        v.setShaderInput("iCameraPos", camera_pos)
        v.setShaderInput("uHealth", max(0.0, min(1.0, health_frac)))
        v.setShaderInput("uDeath", death)

        # Drop expired impacts, then upload the survivors.
        self._impacts = [
            (p, s) for (p, s) in self._impacts if now - s <= _IMPACT_LIFE_S
        ]
        for i in range(_MAX_IMPACTS):
            if i < len(self._impacts):
                p, s = self._impacts[i]
                self._impact_pta.setElement(i, LVecBase4f(p.x, p.y, p.z, s))
            else:
                self._impact_pta.setElement(i, LVecBase4f(0, 0, 0, -1.0e9))
        v.setShaderInput("uImpacts", self._impact_pta)
        v.setShaderInput("uImpactCount", len(self._impacts))

    def clean(self):
        """
        Drop references so the model can be garbage collected. The visible node
        itself is removed by the owning Shield (it lives under the Shield's node).
        """
        self.visual = None
        self.geom_np = None
        self._surface_points = []
        self._impacts = []
        self._impact_pta = None
        self._sink_pta = None
