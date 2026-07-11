"""
Unified GPU-driven particle system for Panda3D.

Currently powers the **explosion** effect (fire + smoke billboards,
sprite-atlas animated). The base class is effect-agnostic, so further
billboard effects can reuse it.

Each effect gets:

- Its own custom vertex format built by :func:`make_particle_format`: the
  shared billboard columns (``vertex``, ``corner``, ``spawn_time``) plus the
  effect's own per-particle columns. Every column is read in GLSL directly by
  name (``in vec3 velocity;`` etc.) — no bit-packing, and no repurposing of
  the semantic ``color`` / ``texcoord`` columns.
- A :class:`ParticleBuffer` (or subclass) that owns the GeomNode, manages slot
  allocation, writes vertex data, and drives the per-frame uniform update.
- Identical billboard quad topology (:data:`CORNERS`, :data:`TRIS`,
  :data:`POOL_SIZE`).


Vertex layout
-------------
Each particle is one billboard quad = 4 vertices. All four vertices of a quad
carry identical simulation data; only ``corner`` differs so the vertex shader
can expand the quad. The shared billboard columns every format includes:

==============  =====  ===========================================================
Column          Type   Content
==============  =====  ===========================================================
``vertex``      vec3   World-space spawn position (bias applied CPU-side).
``corner``      vec2   Corner selector: one of (-1,-1) (1,-1) (1,1) (-1,1).
``spawn_time``  float  Absolute value of the buffer clock when the particle
                       becomes active (includes any delay offset).
==============  =====  ===========================================================

Each effect appends its own columns. The explosion effect
(:mod:`space_flight.fx.explosion_fx`) adds ``velocity`` (vec3), ``size``
(float), ``spin`` (float), ``lifetime`` (float) and ``tile_rect`` (vec4, the
atlas tile UV rect); the spark effect (:mod:`space_flight.fx.spark_fx`) adds
``velocity``, ``size``, ``lifetime``, ``gravity`` (float) and ``spark_color``
(vec4).

GPU animation
-------------
No vertex data is touched after spawn. The vertex shader reconstructs
the particle's current state each frame from the stored spawn parameters:

.. code-block:: glsl

    float t    = uTime - spawn_time;   // particle age (negative → not yet born)
    float frac = clamp(t / lifetime, 0.0, 1.0);
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;

    vec3 pos = vertex + velocity * max(t, 0.0);  // linear motion
    // size, alpha, spin etc. derived from frac …

Three uniforms are updated every frame by :meth:`ParticleBuffer.update`:
``uTime``, ``uCamRight``, ``uCamUp``.

Implementation notes
--------------------
- ``setTransparency(MAlpha)`` must be called **before** ``setShader()``
  or Panda3D's auto-shader generation interferes.
- Atlas textures must be bound via ``setTexture(TextureStage.getDefault(), tex)``
  for the shader to see them as ``p3d_Texture0``.
- Custom vertex columns are exposed to GLSL by their exact column name (no
  ``p3d_`` prefix); the built-in ``vertex`` column is read as ``p3d_Vertex``.
- The atlas tile is selected per-particle by carrying its UV rect in the
  ``tile_rect`` column, so the fragment shader needs neither a uniform array
  nor dynamic indexing to sample the right sprite.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from panda3d.core import (
    BitMask32,
    ColorBlendAttrib,
    CullFaceAttrib,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexArrayFormat,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    InternalName,
    OmniBoundingVolume,
    Point3,
    Shader,
    Texture,
    TextureStage,
    TransparencyAttrib,
    Vec3,
)

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# ---------------------------------------------------------------------------
# Shared geometry constants
# ---------------------------------------------------------------------------

#: Maximum number of live particles per buffer.
#: Fire, smoke, and sparkles each get their own buffer of this size.
POOL_SIZE = 512

#: Local 2-D corners of a billboard quad, in counter-clockwise order.
#: The vertex shader rotates and scales these, then maps them onto the
#: camera's right / up axes to form a screen-facing quad.
CORNERS = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]

#: Triangle indices that tile the four corners into two CCW triangles.
TRIS = [0, 1, 2, 0, 2, 3]


#: Billboard-machinery columns present in every particle format, regardless of
#: effect. ``vertex`` is the standard position column; ``corner`` and
#: ``spawn_time`` are custom columns read in GLSL by name. Effect-specific
#: columns (velocity, size, lifetime, and any extras) are appended per effect.
_BASE_COLUMNS = [
    (InternalName.getVertex(), 3, Geom.CPoint),
    (InternalName.make("corner"), 2, Geom.COther),
    (InternalName.make("spawn_time"), 1, Geom.COther),
]

#: Zero fill values keyed by column width, for zero-initialising dead slots.
_ZERO_BY_WIDTH = {1: 0.0, 2: (0.0, 0.0), 3: (0.0, 0.0, 0.0), 4: (0.0, 0.0, 0.0, 0.0)}


def make_particle_format(columns: list[tuple[str, int]]) -> GeomVertexFormat:
    """
    Build and register a particle vertex format for one effect.

    The format has **one interleaved array** holding the shared billboard
    columns (:data:`_BASE_COLUMNS`) followed by the effect-specific *columns*.
    Each effect column is a custom-named ``COther`` float column, read in GLSL
    directly by name (``in vec3 velocity;`` etc.).

    Registering the format deduplicates it globally, so two buffers built from
    the same *columns* share one registered object.

    :param columns: Effect-specific columns as ``(name, num_components)`` pairs
                    (e.g. ``[("velocity", 3), ("size", 1), ("lifetime", 1)]``).
    :return: The registered :class:`GeomVertexFormat`.
    """
    arr = GeomVertexArrayFormat()
    for name, num_components, contents in _BASE_COLUMNS:
        arr.addColumn(name, num_components, Geom.NTFloat32, contents)
    for name, num_components in columns:
        arr.addColumn(
            InternalName.make(name), num_components, Geom.NTFloat32, Geom.COther
        )
    fmt = GeomVertexFormat()
    fmt.addArray(arr)
    return GeomVertexFormat.registerFormat(fmt)


def _add_column_data(writer: GeomVertexWriter, width: int, value: object) -> None:
    """
    Append one column value of *width* components to *writer*.

    :param writer: The column's :class:`GeomVertexWriter`.
    :param width:  Number of components (1-4).
    :param value:  A scalar for a 1-component column, or an indexable
                   (``Vec3``/``Vec4``/tuple) for a wider one.
    """
    if width == 1:
        writer.addData1(float(value))
    elif width == 2:
        writer.addData2(value[0], value[1])
    elif width == 3:
        writer.addData3(value[0], value[1], value[2])
    else:
        writer.addData4(value[0], value[1], value[2], value[3])


# ---------------------------------------------------------------------------
# Base particle buffer
# ---------------------------------------------------------------------------


class ParticleBuffer:
    """
    Pre-allocated GPU geometry node holding POOL_SIZE billboard quads.

    All particle animation runs on the GPU in the vertex shader. The CPU's
    only per-frame work is pushing three lightweight uniforms
    (``uTime``, ``uCamRight``, ``uCamUp``) via :meth:`update`.

    Slots are reused as particles expire. The CPU-side ``_slots`` list tracks
    ``(spawn_time, total_duration)`` pairs so :meth:`alloc_slot` can find a
    free slot without reading back GPU memory.

    Sub-classes supply an effect-specific :class:`Shader` and column layout and
    call :meth:`write_slot` to spawn individual particles.

    :param game:      Parent game object
    :param shader:    Compiled :class:`Shader` (typically loaded from files via
                      ``Shader.load``) applied to the particle geometry.
    :param columns:   Effect-specific vertex columns as ``(name, num_components)``
                      pairs, appended to the shared billboard columns to build
                      this buffer's format (see :func:`make_particle_format`).
                      Must include a ``lifetime`` column (used for the default
                      slot reservation in :meth:`write_slot`).
    :param texture:   Optional :class:`Texture` bound to the default
                      :class:`TextureStage` (accessible as ``p3d_Texture0``
                      in the shader). Pass ``None`` if the effect uses a
                      procedural shader with no texture.
    :param additive:  If ``True``, use additive blending
                      ``(src * alpha + dst * 1)`` for a bright glow effect.
                      If ``False``, use standard alpha blending.
    :param bin_order: Sort order within the ``"transparent"`` render bin.
    :param task_name: Unique name for the Panda3D per-frame update task.
                      Must differ between simultaneous buffers.
    """

    def __init__(
        self,
        game: FlightState,
        shader: Shader,
        columns: list[tuple[str, int]],
        texture: Texture | None = None,
        additive: bool = False,
        bin_order: int = 20,
        task_name: str = "particle_buffer_update",
    ) -> None:
        self.game = game
        self.id = uuid.uuid4()
        self.game.method_lists[self.id] = []
        self.time = 0.0
        # None  → slot was never used and its vertex data is zeroed (safe).
        # tuple → (absolute_spawn_time, reserved_duration); slot is live until
        #         self.time - spawn_time >= reserved_duration.
        self.slots: list[tuple | None] = [None] * POOL_SIZE

        # Column-width lookup, used by write_slot to dispatch on component count.
        self._column_widths = dict(columns)

        # --- Vertex buffer ---
        # UHDynamic because the CPU writes individual slots at spawn time.
        vdata = GeomVertexData("pb", make_particle_format(columns), Geom.UHDynamic)
        vdata.setNumRows(POOL_SIZE * 4)  # 4 vertices per quad
        self.vdata = vdata

        # Zero-initialise all vertices. Dead particles have lifetime 0 so the
        # shader's alive flag is 0 → the quad collapses to size 0.
        w_vertex = GeomVertexWriter(vdata, "vertex")
        w_corner = GeomVertexWriter(vdata, "corner")
        w_spawn = GeomVertexWriter(vdata, "spawn_time")
        col_writers = [(GeomVertexWriter(vdata, name), w) for name, w in columns]
        for _ in range(POOL_SIZE * 4):
            w_vertex.addData3(0, 0, 0)
            w_corner.addData2(0, 0)
            w_spawn.addData1(0)
            for writer, width in col_writers:
                _add_column_data(writer, width, _ZERO_BY_WIDTH[width])

        # --- Index buffer (static — triangle topology never changes) ---
        tris = GeomTriangles(Geom.UHStatic)
        for i in range(POOL_SIZE):
            b = i * 4  # first vertex of this quad
            for idx in TRIS:
                tris.addVertex(b + idx)
            tris.closePrimitive()

        geom = Geom(vdata)
        geom.addPrimitive(tris)
        gn = GeomNode("pb")
        gn.addGeom(geom)

        self.node_path = self.game.root_node.attachNewNode(gn)

        # --- Render state ---
        # IMPORTANT: setTransparency must come before setShader; otherwise
        # Panda3D's automatic shader generator activates and conflicts with
        # the custom shader.
        self.node_path.setTransparency(TransparencyAttrib.MAlpha)
        self.node_path.setShader(shader)
        if texture is not None:
            # Binding to the default TextureStage makes the texture accessible
            # as p3d_Texture0 in the shader without any manual sampler setup.
            self.node_path.setTexture(TextureStage.getDefault(), texture)

        if additive:
            # Additive blending: final = src_colour × src_alpha + dst_colour.
            # Overlapping particles brighten naturally, giving a glow / fire
            # look. Also order-independent, so no depth-sorting is needed.
            self.node_path.setAttrib(
                ColorBlendAttrib.make(
                    ColorBlendAttrib.MAdd,
                    ColorBlendAttrib.OIncomingAlpha,
                    ColorBlendAttrib.OOne,
                )
            )
        # Allow the quads to be seen from both sides (e.g. in the rear view mirror)
        self.node_path.setAttrib(CullFaceAttrib.make(CullFaceAttrib.MCullNone))
        # Transparent quads must not write to the depth buffer or they would
        # incorrectly occlude geometry behind their rectangular silhouette.
        self.node_path.setDepthWrite(False)
        self.node_path.setBin("transparent", bin_order)
        # Particles are self-illuminated; scene lights should not affect them.
        self.node_path.setLightOff()
        # Tell Panda3D the node is always visible so it skips frustum culling.
        # The GPU discards dead / invisible fragments cheaply via early-out in
        # the shader, so the cost of "always drawing" this node is minimal.
        self.node_path.node().setBounds(OmniBoundingVolume())
        self.node_path.node().setFinal(True)
        # Particle geometry must never participate in collision traversals.
        self.node_path.node().setIntoCollideMask(BitMask32.allOff())

        # Seed per-frame uniforms with safe defaults.
        self.node_path.setShaderInput("uTime", 0.0)
        self.node_path.setShaderInput("uCamRight", Vec3(1, 0, 0))
        self.node_path.setShaderInput("uCamUp", Vec3(0, 0, 1))

        self.task_name = task_name

        self.game.method_lists[self.id].append(self.update)

    # ------------------------------------------------------------------
    # Slot management
    # ------------------------------------------------------------------

    def alloc_slot(self) -> int | None:
        """
        Find and return a free slot index.

        A slot is considered free when:

        - It has never been used (``_slots[i] is None``), or
        - Enough buffer-clock time has elapsed since its spawn that its
          particle has fully expired (``_time - spawn_time >= duration``).

        :return: A free slot index in ``[0, _POOL_SIZE)``, or ``None``
                  if the pool is completely full.
        """
        now = self.time
        for i, s in enumerate(self.slots):
            if s is None or now - s[0] >= s[1]:
                return i
        return None

    def write_slot(
        self,
        slot_index: int,
        pos: Point3,
        spawn_delay: float = 0.0,
        slot_duration: float | None = None,
        **columns: object,
    ) -> None:
        """
        Write one particle quad into *slot_index*.

        All four corners receive identical simulation data; only ``corner``
        differs (the four values from :data:`CORNERS`). The vertex shader uses
        the corner to offset the billboard along the camera axes.

        The billboard-machinery columns (``vertex``, ``corner``, ``spawn_time``)
        are written here; every other column is supplied as a keyword argument
        matching an effect column name (see :func:`make_particle_format`), e.g.
        ``velocity=Vec3(...)``, ``size=1.5``, ``lifetime=2.0``. Scalars fill
        1-component columns; indexables (``Vec3``/``Vec4``/tuples) fill wider
        ones. There is no packing to undo on the GPU side.

        :param slot_index:    Index into ``slots`` / vertex buffer to overwrite.
        :param pos:           World-space spawn position (positional bias already
                              applied by the caller).
        :param spawn_delay:   Seconds before the particle becomes visible.
                              The stored ``spawn_time = time + spawn_delay``
                              makes ``t = uTime - spawn_time`` negative during
                              the delay window, keeping the quad invisible.
        :param slot_duration: How long to reserve this slot (seconds, excluding
                              *spawn_delay*). Defaults to the ``lifetime`` column.
        :param columns:       One value per effect column, keyed by column name.
                              Must include ``lifetime``.
        """
        now = self.time
        base_v = slot_index * 4
        # spawn_time is stored as an absolute clock value. The shader computes
        # t = uTime - spawn_time, which is negative while the delay is pending.
        spawn_t = now + spawn_delay

        w_vertex = GeomVertexWriter(self.vdata, "vertex")
        w_vertex.setRow(base_v)
        w_corner = GeomVertexWriter(self.vdata, "corner")
        w_corner.setRow(base_v)
        w_spawn = GeomVertexWriter(self.vdata, "spawn_time")
        w_spawn.setRow(base_v)
        col_writers = {name: GeomVertexWriter(self.vdata, name) for name in columns}
        for writer in col_writers.values():
            writer.setRow(base_v)

        for cx, cy in CORNERS:
            w_vertex.addData3(pos)
            w_corner.addData2(cx, cy)
            w_spawn.addData1(spawn_t)
            for name, value in columns.items():
                _add_column_data(col_writers[name], self._column_widths[name], value)

        duration = slot_duration if slot_duration is not None else columns["lifetime"]
        # Reserve the slot for delay + lifetime so alloc_slot() does not reclaim
        # it before the particle has even appeared on screen.
        self.slots[slot_index] = (now, duration + spawn_delay)

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self) -> None:
        """
        Push the three per-frame uniforms to the GPU.

        Called automatically by the games task manager
        Override in a sub-class to push additional per-frame uniforms,
        remembering to call ``super().update()``.
        """
        self.time = self.game.game_time.get_current_time()
        # Billboard orientation is a pure rendering concern (there is no
        # camera, and nothing to render, headless).
        if self.game.headless:
            return
        cam_mat = self.game.app.camera.getMat(self.game.root_node)
        cam_right, cam_up = cam_mat.getRow3(0), cam_mat.getRow3(2)
        # Row 0 = camera right axis, row 2 = camera up axis
        # (Panda3D uses a Y-forward, Z-up convention).
        self.node_path.setShaderInput("uTime", self.time)
        self.node_path.setShaderInput("uCamRight", cam_right)
        self.node_path.setShaderInput("uCamUp", cam_up)

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def set_input(self, name: str, value: object) -> None:
        """
        Set a shader uniform by name.

        :param name:  Uniform name as declared in the GLSL source.
        :param value: Value compatible with :meth:`NodePath.setShaderInput`.
        """
        self.node_path.setShaderInput(name, value)

    def set_texture(self, texture: Texture) -> None:
        """
        Replace the texture bound to the default :class:`TextureStage`.

        :param texture: New :class:`Texture` to bind.
        """
        self.node_path.setTexture(TextureStage.getDefault(), texture)

    def clean(self) -> None:
        """
        Remove the update task and destroy the geometry node.
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.node_path.removeNode()


# ---------------------------------------------------------------------------
# Atlas loader
# ---------------------------------------------------------------------------


def load_atlas(
    game: FlightState, texture_path: Path, json_path: Path
) -> tuple[Texture, list]:
    """
    Load a sprite atlas from a PNG and its companion JSON descriptor.

    The JSON is a list of dicts with keys ``u_min``, ``v_min``, ``u_size``,
    ``v_size`` (all in 0-1 UV space, already flipped for OpenGL's bottom-left
    origin by the atlas build tool).

    :param game: The parent game object
    :param texture_path:  Path to the atlas PNG file.
    :param json_path: Path to the JSON rect descriptor.
    :return: A ``(texture, rects)`` tuple where *rects* is a list of
              ``(u, v, uw, vh)`` tuples, one per sprite frame.
    """
    with open(json_path) as f:
        data = json.load(f)
    rects = [(r["u_min"], r["v_min"], r["u_size"], r["v_size"]) for r in data]

    tex = game.app.asset_manager.get_asset(
        asset_type="texture",
        path=texture_path,
    ).get_texture()
    tex.setMagfilter(Texture.FTLinear)
    tex.setMinfilter(Texture.FTLinear)
    # Clamp prevents colour bleeding from neighbouring atlas frames at quad edges.
    tex.setWrapU(Texture.WMClamp)
    tex.setWrapV(Texture.WMClamp)
    return tex, rects
