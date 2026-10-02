"""
Unified GPU-driven particle system for Panda3D.

Powers the fire/smoke billboards (one random sprite-atlas tile per particle,
:mod:`space_flight.fx.fire_smoke_fx`) and the laser-hit sparks
(:mod:`space_flight.fx.spark_fx`). The base class is effect-agnostic.

Each effect gets:

- Its own vertex format from :func:`make_particle_format`: the shared
  billboard columns plus the effect's own per-particle columns, each read in
  GLSL by name (``in vec3 velocity;``) — no bit-packing, and no repurposing of
  the semantic color / texcoord columns.
- A :class:`ParticleBuffer` (or subclass) that owns the GeomNode, allocates
  slots, writes vertex data and pushes the per-frame uniforms.
- The same billboard quad topology (:data:`CORNERS`, :data:`TRIS`,
  :data:`POOL_SIZE`).


Vertex layout
-------------
Each particle is one billboard quad = 4 vertices carrying identical data;
only ``corner`` differs, so the vertex shader can expand the quad. Shared
columns:

==============  =====  =========================================================
Column          Type   Content
==============  =====  =========================================================
``vertex``      vec3   World-space spawn position (bias applied CPU-side).
``corner``      vec2   Corner selector: one of (-1,-1) (1,-1) (1,1) (-1,1).
``spawn_time``  float  Buffer-clock time at which the particle becomes active
                       (includes any spawn delay).
==============  =====  =========================================================

Effect columns: fire/smoke adds ``velocity`` (vec3), ``size``, ``spin``,
``lifetime`` (floats) and ``tile_rect`` (vec4 atlas UV rect); sparks add
``velocity``, ``size``, ``lifetime``, ``gravity`` (float) and ``spark_color``
(vec4).

GPU animation
-------------
No vertex data is touched after spawn. The vertex shader reconstructs the
particle's state each frame from the spawn parameters:

.. code-block:: glsl

    float t    = uTime - spawn_time;   // particle age (negative → not yet born)
    float frac = clamp(t / lifetime, 0.0, 1.0);
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;

    vec3 pos = vertex + velocity * max(t, 0.0);  // linear motion
    // size, alpha, spin etc. derived from frac …

:meth:`ParticleBuffer.update` pushes three uniforms every frame: ``uTime``,
``uCamRight``, ``uCamUp``.

Implementation notes
--------------------
- ``setTransparency(MAlpha)`` must be called **before** ``setShader()`` or
  Panda3D's auto-shader generation interferes.
- Bind atlas textures with ``setTexture(TextureStage.getDefault(), tex)`` so
  the shader sees them as ``p3d_Texture0``.
- Custom columns are exposed to GLSL by their exact name (no ``p3d_`` prefix);
  the built-in ``vertex`` column is read as ``p3d_Vertex``.
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

#: Maximum number of live particles per buffer (fire, smoke and sparks each have
#: their own buffer).
POOL_SIZE = 512

#: Local 2-D corners of a billboard quad, counter-clockwise. The vertex shader
#: maps them onto the camera's right / up axes.
CORNERS = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]

#: Triangle indices that tile the four corners into two CCW triangles.
TRIS = [0, 1, 2, 0, 2, 3]


#: Billboard columns present in every particle format. vertex is the standard
#: position column; corner and spawn_time are custom columns read by name.
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

    One interleaved array: the shared billboard columns (:data:`_BASE_COLUMNS`)
    followed by *columns*, each a custom-named COther float column. Registering
    deduplicates the format globally, so buffers with the same *columns* share
    one registered object.

    :param columns: Effect-specific columns as (name, num_components) pairs
                    (e.g. [("velocity", 3), ("size", 1), ("lifetime", 1)]).
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
                   (Vec3/Vec4/tuple) for a wider one.
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

    Particles are animated in the vertex shader; the CPU only pushes three
    uniforms per frame (:meth:`update`). Slots are reused as particles expire,
    tracked CPU-side (``self.slots``) so :meth:`alloc_slot` never reads back GPU
    memory. Sub-classes supply the shader and column layout and call
    :meth:`write_slot` to spawn particles.

    :param game:      Parent game object
    :param shader:    Compiled :class:`Shader` applied to the particle geometry.
    :param columns:   Effect-specific vertex columns as (name, num_components)
                      pairs, appended to the shared billboard columns to build
                      this buffer's format (see :func:`make_particle_format`).
                      Must include a lifetime column (used for the default
                      slot reservation in :meth:`write_slot`).
    :param texture:   Optional :class:`Texture` bound to the default
                      :class:`TextureStage` (p3d_Texture0 in the shader).
    :param additive:  If True, additive blending (src * alpha + dst) for a
                      glow; otherwise standard alpha blending.
    :param bin_order: Sort order within the "transparent" render bin.
    :param task_name: Descriptive name stored as ``self.task_name``. The update
                      is not a Panda3D task: :meth:`update` is registered in
                      ``game.method_lists`` under this buffer's ``id``.
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
        # None  → never used; its vertex data is zeroed (safe).
        # tuple → (write_time, reserved_duration), reserved_duration including
        #         any spawn delay; live until self.time - write_time >= it.
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

        A slot is free if never used or if its reservation has elapsed.

        :return: A free slot index in [0, POOL_SIZE), or None if the pool is
                 full.
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

        All four vertices get identical data except corner (:data:`CORNERS`).
        The billboard columns are written here; every effect column is a keyword
        argument named after it, e.g. velocity=Vec3(...), size=1.5,
        lifetime=2.0. Scalars fill 1-component columns, indexables
        (Vec3/Vec4/tuples) wider ones.

        :param slot_index:    Index into slots / vertex buffer to overwrite.
        :param pos:           World-space spawn position (positional bias already
                              applied by the caller).
        :param spawn_delay:   Seconds before the particle becomes visible
                              (stored as spawn_time = time + spawn_delay, so
                              the shader's age is negative until then).
        :param slot_duration: How long to reserve this slot (seconds, excluding
                              *spawn_delay*). Defaults to the lifetime column.
        :param columns:       One value per effect column, keyed by column name.
                              Must include lifetime.
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

        Called every frame through ``game.method_lists``. Sub-classes pushing
        more uniforms must call super().update().
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
        Unregister the per-frame update and destroy the geometry node.
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

    The JSON is a list of dicts with keys u_min, v_min, u_size, v_size (0-1 UV
    space, already flipped for OpenGL's bottom-left origin by
    scripts/build_particle_atlas.py).

    :param game: The parent game object
    :param texture_path:  Path to the atlas PNG file.
    :param json_path: Path to the JSON rect descriptor.
    :return: A (texture, rects) tuple where *rects* is a list of
              (u, v, uw, vh) tuples, one per sprite frame.
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
