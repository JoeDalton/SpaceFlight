"""
Ocean — clipmap LOD ocean with planar reflections for Panda3D.

Usage:
    from ocean import Ocean
    self.ocean = Ocean(self)

    # In your update task:
    self.ocean.update(camera_pos, t)
"""

import math
import uuid

from panda3d.core import (
    BitMask32,
    Camera,
    ClipPlaneAttrib,
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LMatrix4f,
    LPlane,
    LVecBase2f,
    LVecBase3f,
    PlaneNode,
    Shader,
    Texture,
)

from space_flight import DATAFILES_PATH
from space_flight.game.collisions import attach_collision_plane
from space_flight.utils import compute_next_power_of_2

# ---------------------------------------------------------------------------
# LOD configuration
#   size   : world size of the ring in metres
#   subdivs: number of quads per side
#   snap   : camera position is snapped to this grid (metres)
#   inner  : fraction of the ring's half-size left empty (hole for inner LOD)
# ---------------------------------------------------------------------------
LOD_LEVELS = [
    dict(size=200, subdivs=64, snap=1, inner=0.0),  # 0: close
    dict(size=2000, subdivs=64, snap=10, inner=0.09),  # 1: mid
    dict(size=20000, subdivs=64, snap=100, inner=0.09),  # 2: far
]

# Camera mask bit used to hide ocean rings from the reflection camera
_OCEAN_BIT = BitMask32.bit(1)


def _make_ring_mesh(size: float, subdivs: int, inner_fraction: float = 0.0):
    """
    Flat XY mesh of given world size.  If inner_fraction > 0, quads whose
    centre falls within (inner_fraction * half_size) of the origin are
    skipped, leaving a hole for the finer inner LOD ring.
    """
    fmt = GeomVertexFormat.getV3n3t2()
    vdata = GeomVertexData("ocean_ring", fmt, Geom.UHStatic)
    n = subdivs + 1
    vdata.setNumRows(n * n)

    vw = GeomVertexWriter(vdata, "vertex")
    nw = GeomVertexWriter(vdata, "normal")
    tw = GeomVertexWriter(vdata, "texcoord")

    half = size * 0.5
    for j in range(n):
        for i in range(n):
            x = -half + size * i / subdivs
            y = -half + size * j / subdivs
            vw.addData3f(x, y, 0.0)
            nw.addData3f(0.0, 0.0, 1.0)
            tw.addData2f(i / subdivs, j / subdivs)

    hole = half * inner_fraction
    tris = GeomTriangles(Geom.UHStatic)
    for j in range(subdivs):
        for i in range(subdivs):
            cx = -half + size * (i + 0.5) / subdivs
            cy = -half + size * (j + 0.5) / subdivs
            if hole > 0 and abs(cx) < hole and abs(cy) < hole:
                continue
            v0 = j * n + i
            tris.addVertices(v0, v0 + 1, v0 + n)
            tris.addVertices(v0 + 1, v0 + n + 1, v0 + n)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("ocean_ring")
    node.addGeom(geom)
    return node


class Ocean:
    def __init__(
        self,
        game,
        refl_scale=0.5,
        water_color=LVecBase3f(0.02, 0.06, 0.14),
        ripple_strength=0.02,
        wind_dir=LVecBase2f(1.0, 0.0),  # normalised XY
        wind_strength=0.5,  # 0=random, 1=fully aligned
        vert_shader=DATAFILES_PATH / "shaders/ocean.vert",
        frag_shader=DATAFILES_PATH / "shaders/ocean.frag",
    ):
        """
        Parameters
        ----------
        game            : The game instance
        refl_scale      : reflection buffer resolution relative to window
        water_color     : deep water scatter colour
        ripple_strength : normal-based UV perturbation strength
        vert_shader     : path to ocean.vert
        frag_shader     : path to ocean.frag
        """
        self.game = game
        self.id = uuid.uuid4()
        self.base_node = self.game.root_node.attachNewNode("ocean")

        # ── Reflection buffer (shared by all LOD levels) ──────────────────────
        self._refl_tex, uv_scale = self._make_reflection_buffer(refl_scale, water_color)

        # ── Shader (shared by all LOD levels) ─────────────────────────────────
        shader = Shader.load(Shader.SL_GLSL, vertex=vert_shader, fragment=frag_shader)

        # ── One mesh node per LOD level ───────────────────────────────────────
        self._rings = []
        for lod in LOD_LEVELS:
            node = self.base_node.attachNewNode(
                _make_ring_mesh(lod["size"], lod["subdivs"], lod["inner"])
            )
            node.setShader(shader)
            node.setShaderInput("iTime", 0.0)
            node.setShaderInput("iCameraPos", LVecBase3f(0, 0, 20))
            node.setShaderInput("iWaterColor", water_color)
            node.setShaderInput("iReflectionTex", self._refl_tex)
            node.setShaderInput("iRippleStrength", ripple_strength)
            node.setShaderInput("iWindDir", wind_dir)
            node.setShaderInput("iWindStrength", wind_strength)
            node.setShaderInput("uReflMVP", LMatrix4f.identMat())
            node.setShaderInput("uReflUVScale", uv_scale)
            # Hide ocean rings from the reflection camera
            node.hide(_OCEAN_BIT)
            self._rings.append((node, lod))

        self.game.method_lists[self.id] = [self.update]

        # Initialize collisions
        attach_collision_plane(
            game=self.game,
            name="terrain",
            collider_type="terrain",
            parent_node=self.base_node,
            parent_object=self,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self):
        """Call every frame from your update task."""
        current_time = self.game.game_time.get_current_time()
        camera_pos = self.game.app.camera.getPos(self.base_node)
        self._mirror_camera()

        # Build reflection MVP once, share across all rings
        view = LMatrix4f()
        view.invertFrom(self._refl_cam.getMat(self.base_node))
        proj = self._refl_cam_node.getLens().getProjectionMat()
        mvp = view * proj

        for node, lod in self._rings:
            # Snap ring XY to grid so it stays centred under the camera
            snap = lod["snap"]
            sx = math.floor(camera_pos.x / snap) * snap
            sy = math.floor(camera_pos.y / snap) * snap
            node.setPos(sx, sy, 0.0)

            node.setShaderInput("iTime", current_time)
            node.setShaderInput("iCameraPos", camera_pos)
            node.setShaderInput("uReflMVP", mvp)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _make_reflection_buffer(self, refl_scale, water_color):
        win_w = self.game.app.win.getXSize()
        win_h = self.game.app.win.getYSize()
        buf_w = max(1, int(win_w * refl_scale))
        buf_h = max(1, int(win_h * refl_scale))

        refl_tex = Texture("refl_tex")
        refl_tex.setWrapU(Texture.WMClamp)
        refl_tex.setWrapV(Texture.WMClamp)

        self._refl_buffer = self.game.app.win.makeTextureBuffer(
            "refl_buffer", buf_w, buf_h, refl_tex
        )
        self._refl_buffer.setSort(-100)
        self._refl_buffer.setClearColor(
            (water_color.x, water_color.y, water_color.z, 1)
        )

        self._refl_cam_node = Camera("refl_cam")
        # Use a wider lens than the main camera to avoid frustum culling
        # artifacts when turning quickly — the extra margin ensures reflected
        # objects are never culled at the edges of the reflection buffer.
        refl_lens = self.game.app.camLens.makeCopy()
        fov = self.game.app.camLens.getFov()
        refl_lens.setFov(fov.x * 1.4, fov.y * 1.4)
        self._refl_cam_node.setLens(refl_lens)
        self._refl_cam = self.base_node.attachNewNode(self._refl_cam_node)

        # Use only the lower 20 bits, excluding bit 1 (ocean rings)
        self._refl_cam_node.setCameraMask(BitMask32(0xFFFFF & ~2))

        self._refl_buffer.makeDisplayRegion(0, 1, 0, 1).setCamera(self._refl_cam)

        clip_plane = PlaneNode("water_clip")
        clip_plane.setPlane(LPlane(0, 0, 1, 0))
        self._clip_np = self.base_node.attachNewNode(clip_plane)
        clip_attrib = ClipPlaneAttrib.makeAllOff().addOnPlane(self._clip_np)
        self._refl_cam_node.setInitialState(
            self._refl_cam_node.getInitialState().addAttrib(clip_attrib)
        )

        uv_scale = LVecBase2f(
            buf_w / compute_next_power_of_2(buf_w),
            buf_h / compute_next_power_of_2(buf_h),
        )
        return refl_tex, uv_scale

    def _mirror_camera(self):
        pos = self.game.app.camera.getPos(self.base_node)
        hpr = self.game.app.camera.getHpr(self.base_node)
        self._refl_cam.setPos(self.base_node, pos.x, pos.y, -pos.z)
        self._refl_cam.setHpr(self.base_node, hpr.x, -hpr.y, -hpr.z)

    def clean(self):
        """
        Cleans the Ocean object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        self.base_node.removeNode()
        self.game = None
