"""
Unified GPU-driven particle system for Panda3D.
Provides two effects that were previously in separate modules:

- **Explosion** — fire + smoke billboards, sprite-atlas animated.
- **Sparkle** — hit sparks, procedural SDF circle with glow.

Both effects share:

- A single custom vertex format (:data:`_FMT`).
- A single base class :class:`ParticleBuffer` that owns the GeomNode,
  manages slot allocation, writes vertex data, and drives the per-frame
  uniform update.
- Identical billboard quad topology (:data:`_CORNERS`, :data:`_TRIS`,
  :data:`_POOL_SIZE`).


Vertex layout (shared by all buffers)
--------------------------------------
Each particle is one billboard quad = 4 vertices.
All four vertices of a quad carry identical simulation data; only
``corner.xy`` differs so the vertex shader can expand the quad.

============================  =====  =============================================
Column                        Type   Content
============================  =====  =============================================
``vertex``                    vec3   World-space spawn position (bias applied
                                     CPU-side before writing).
``color.xyz``                 vec3   Initial velocity (world units / s).
``color.w``                   float  **Effect-specific packed payload** — see
                                     each effect's packing note below.
``texcoord.xy``               vec2   Corner selector: one of
                                     (-1,-1) (1,-1) (1,1) (-1,1).
``texcoord.z``                float  ``spawn_time`` — absolute value of the
                                     buffer clock when the particle becomes
                                     active (includes any delay offset).
``texcoord.w``                float  **Effect-specific packed payload** — see
                                     each effect's packing note below.
============================  =====  =============================================

Packing schemes
---------------
Both effects reuse the same two "spare" floats (``color.w`` and
``texcoord.w``) but interpret them differently.

**Explosion** — two values packed per float using integer / fractional parts:

.. code-block:: text

    color.w    →  size_spin
        int  part = round(size * 100)            # size in world units × 100
        frac part = (spin_rate / SPIN_MAX + 1) / 2   # spin mapped to [0, 1)

    texcoord.w →  tile_life
        int  part = tile_index                   # atlas sprite index
        frac part = lifetime / 10.0              # lifetime in [0, 9.99] s

**Sparkle** — values stored directly, no packing needed:

.. code-block:: text

    color.w    →  size        # billboard half-size in world units
    texcoord.w →  lifetime    # particle lifetime in seconds

GPU animation
-------------
No vertex data is touched after spawn. The vertex shader reconstructs
the particle's current state each frame from the stored spawn parameters:

.. code-block:: glsl

    float t    = uTime - spawn_time;   // particle age (negative → not yet born)
    float frac = clamp(t / lifetime, 0.0, 1.0);
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;

    vec3 pos = spawn_pos + velocity * max(t, 0.0);  // linear motion
    // size, alpha, spin etc. derived from frac …

Three uniforms are updated every frame by :meth:`ParticleBuffer.update`:
``uTime``, ``uCamRight``, ``uCamUp``.

Implementation notes
--------------------
- ``setTransparency(MAlpha)`` must be called **before** ``setShader()``
  or Panda3D's auto-shader generation interferes.
- Atlas textures must be bound via ``setTexture(TextureStage.getDefault(), tex)``
  for the shader to see them as ``p3d_Texture0``.
- ``p3d_MultiTexCoord0`` arrives in the shader as a ``vec4``; UVs are in ``.xy``.
- GLSL 140 forbids dynamic array indexing, so atlas rects are uploaded as
  individual uniforms (``uTileRect0``, ``uTileRect1``, …) and selected via
  an ``if / else`` chain in the fragment shader.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path

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


def make_geom_vertex_format() -> GeomVertexFormat:
    """
    Build and register the shared custom vertex format.

    The format has **one interleaved array** with three columns:

    - ``vertex``   (3 * float32, CPoint)   — spawn position.
    - ``color``    (4 * float32, CColor)   — velocity + packed payload.
    - ``texcoord`` (4 * float32, CTexcoord)— corner + spawn_time + packed payload.

    Registering the format deduplicates it globally; calling this function
    more than once returns the same registered object.

    :returns: The registered :class:`GeomVertexFormat`.
    """
    arr = GeomVertexArrayFormat()
    arr.addColumn(InternalName.getVertex(), 3, Geom.NTFloat32, Geom.CPoint)
    arr.addColumn(InternalName.getColor(), 4, Geom.NTFloat32, Geom.CColor)
    arr.addColumn(InternalName.getTexcoord(), 4, Geom.NTFloat32, Geom.CTexcoord)
    fmt = GeomVertexFormat()
    fmt.addArray(arr)
    return GeomVertexFormat.registerFormat(fmt)


# Registered vertex format, shared by all particle buffers.
FMT = make_geom_vertex_format()


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

    Sub-classes supply effect-specific GLSL sources and call
    :meth:`write_slot` to spawn individual particles.

    :param game:      Parent game object
    :param vert_src:  GLSL vertex shader source string.
    :param frag_src:  GLSL fragment shader source string.
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
        game,
        vert_src: str,
        frag_src: str,
        texture: Texture | None = None,
        additive: bool = False,
        bin_order: int = 20,
        task_name: str = "particle_buffer_update",
    ):
        self.game = game
        self.id = uuid.uuid4()
        self.game.method_lists[self.id] = []
        self.time = 0.0
        # None  → slot was never used and its vertex data is zeroed (safe).
        # tuple → (absolute_spawn_time, reserved_duration); slot is live until
        #         self.time - spawn_time >= reserved_duration.
        self.slots: list[tuple | None] = [None] * POOL_SIZE

        # --- Vertex buffer ---
        # UHDynamic because the CPU writes individual slots at spawn time.
        vdata = GeomVertexData("pb", FMT, Geom.UHDynamic)
        vdata.setNumRows(POOL_SIZE * 4)  # 4 vertices per quad
        self.vdata = vdata

        # Zero-initialise all vertices. Dead particles have spawn_time far in
        # the past so the shader's alive flag is 0 → quad collapses to size 0.
        wp = GeomVertexWriter(vdata, "vertex")
        wc = GeomVertexWriter(vdata, "color")
        wt = GeomVertexWriter(vdata, "texcoord")
        for _ in range(POOL_SIZE * 4):
            wp.addData3(0, 0, 0)
            wc.addData4(0, 0, 0, 0)
            wt.addData4(0, 0, 0, 0)

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
        self.node_path.setShader(Shader.make(Shader.SL_GLSL, vert_src, frag_src))
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

        :returns: A free slot index in ``[0, _POOL_SIZE)``, or ``None``
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
        vel: Vec3,
        color_w: float,
        texcoord_w: float,
        spawn_delay: float = 0.0,
        slot_duration: float | None = None,
    ):
        """
        Write one particle quad into *slot_index*.

        All four corners receive identical simulation data; only ``corner.xy``
        differs (the four values from :data:`_CORNERS`). The vertex shader
        uses the corner to offset the billboard along the camera axes.

        **Packing contracts** (caller's responsibility):

        *Explosion effect*:

        .. code-block:: text

            color_w    = float(round(size * 100)) + clamp((spin/SPIN_MAX+1)/2, 0, 0.999)
                         └─ int part: size * 100  └─ frac part: normalised spin

            texcoord_w = float(tile_index) + clamp(lifetime / 10.0, 0, 0.999)
                         └─ int part: atlas tile  └─ frac part: lifetime / 10 s

        *Sparkle effect*:

        .. code-block:: text

            color_w    = size       (raw float, no packing)
            texcoord_w = lifetime   (raw float, no packing)

        :param slot_i:        Index into ``_slots`` / vertex buffer to overwrite.
        :param pos:           World-space spawn position (positional bias already
                              applied by the caller).
        :param vel:           Initial velocity in world units per second.
        :param color_w:       Effect-specific value for ``color.w``
                              (see packing contracts above).
        :param texcoord_w:    Effect-specific value for ``texcoord.w``
                              (see packing contracts above).
        :param spawn_delay:   Seconds before the particle becomes visible.
                              The stored ``spawn_time = _time + spawn_delay``
                              makes ``t = uTime - spawn_time`` negative during
                              the delay window, keeping the quad invisible.
        :param slot_duration: How long to reserve this slot (seconds, excluding
                              *spawn_delay*). Defaults to
                              ``fract(texcoord_w) * 10``, which is valid for
                              the explosion packing scheme. Pass explicitly for
                              sparkles (where ``texcoord_w`` is raw lifetime).
        """
        now = self.time
        base_v = slot_index * 4
        # spawn_time is stored as an absolute clock value. The shader computes
        # t = uTime - spawn_time, which is negative while the delay is pending.
        spawn_t = now + spawn_delay

        wp = GeomVertexWriter(self.vdata, "vertex")
        wp.setRow(base_v)
        wc = GeomVertexWriter(self.vdata, "color")
        wc.setRow(base_v)
        wt = GeomVertexWriter(self.vdata, "texcoord")
        wt.setRow(base_v)

        for cx, cy in CORNERS:
            wp.addData3(pos)
            wc.addData4(vel.x, vel.y, vel.z, color_w)
            # texcoord.z carries spawn_time; texcoord.xy is the corner selector
            wt.addData4(cx, cy, spawn_t, texcoord_w)

        # Default duration decodes the explosion packing (frac part × 10 s).
        # Callers using raw lifetime in texcoord_w must pass slot_duration explicitly.
        duration = (
            slot_duration
            if slot_duration is not None
            else math.fmod(texcoord_w, 1.0) * 10.0
        )
        # Reserve the slot for delay + lifetime so alloc_slot() does not reclaim
        # it before the particle has even appeared on screen.
        self.slots[slot_index] = (now, duration + spawn_delay)

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self):
        """
        Push the three per-frame uniforms to the GPU.

        Called automatically by the games task manager
        Override in a sub-class to push additional per-frame uniforms,
        remembering to call ``super().update()``.
        """
        self.time = self.game.game_time.get_current_time()
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

    def set_input(self, name: str, value):
        """
        Set a shader uniform by name.

        :param name:  Uniform name as declared in the GLSL source.
        :param value: Value compatible with :meth:`NodePath.setShaderInput`.
        """
        self.node_path.setShaderInput(name, value)

    def set_texture(self, texture: Texture):
        """
        Replace the texture bound to the default :class:`TextureStage`.

        :param tex: New :class:`Texture` to bind.
        """
        self.node_path.setTexture(TextureStage.getDefault(), texture)

    def clean(self):
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


def load_atlas(game, texture_path: Path, json_path: Path) -> tuple[Texture, list]:
    """
    Load a sprite atlas from a PNG and its companion JSON descriptor.

    The JSON is a list of dicts with keys ``u_min``, ``v_min``, ``u_size``,
    ``v_size`` (all in 0-1 UV space, already flipped for OpenGL's bottom-left
    origin by the atlas build tool).

    :param game: The parent game object
    :param texture_path:  Path to the atlas PNG file.
    :param json_path: Path to the JSON rect descriptor.
    :returns: A ``(texture, rects)`` tuple where *rects* is a list of
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
