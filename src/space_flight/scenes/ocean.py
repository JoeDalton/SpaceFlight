"""
Ocean — clipmap LOD ocean with planar reflections for Panda3D.

Usage:
    from ocean import Ocean
    self.ocean = Ocean(self)

    # In your update task:
    self.ocean.update(camera_pos, t)
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import (
    BitMask32,
    Camera,
    ClipPlaneAttrib,
    Geom,
    GeomEnums,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    LMatrix4f,
    LPlane,
    LVecBase2f,
    LVecBase3f,
    LVecBase4f,
    PlaneNode,
    PTA_LVecBase2f,
    Shader,
    Texture,
)

from space_flight import DATAFILES_PATH
from space_flight.game.collisions import attach_collision_plane
from space_flight.utils import compute_next_power_of_2

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# Fraction of the camera far distance used as the ocean plane's half-size.
# >1 so the plane's edges always lie beyond the far clip and are never visible.
_PLANE_FAR_FACTOR = 3.0

# Camera mask bit used to hide the ocean from the reflection camera
_OCEAN_BIT = BitMask32.bit(1)

# Max wave iterations the shader's iWaveDirs[] array can hold (must match the
# MAX_WAVE_ITER #define in ocean.frag).
_MAX_WAVE_ITER = 64


def compute_wave_dirs(wind_dir: LVecBase2f, wind_strength: float) -> PTA_LVecBase2f:
    """Precompute the per-iteration wave directions the fragment shader uses.

    These depend only on the iteration index and the wind, not on the pixel, so
    we build them once on the CPU and pass them as a uniform array instead of
    recomputing sin/cos/normalize/mix per pixel per iteration in the shader.
    Mirrors the original in-shader formula exactly.

    :param wind_dir: Wind direction in the XY plane (normalised).
    :param wind_strength: How strongly directions align to the wind; 0 =
        random, 1 = fully aligned.
    :return: One normalised wave direction per shader iteration.
    """
    pta = PTA_LVecBase2f()
    it = 0.0
    ws = wind_strength
    for _ in range(_MAX_WAVE_ITER):
        rx, ry = math.sin(it), math.cos(it)
        # mix(rndDir, wind_dir, ws)
        mx = rx * (1.0 - ws) + wind_dir.x * ws
        my = ry * (1.0 - ws) + wind_dir.y * ws
        length = max(math.hypot(mx, my), 1e-5)
        pta.pushBack(LVecBase2f(mx / length, my / length))
        it += 1232.399963
    return pta


def make_plane_mesh(size: float) -> GeomNode:
    """
    Single flat XY quad of the given world size, centred on the origin.

    The ocean surface has no vertical displacement — all wave detail is
    computed per-pixel in the fragment shader from the interpolated world
    position.  Across a flat triangle that interpolation is exact, so a single
    quad is pixel-identical to any tessellation: no subdivision is needed, and
    the vertex carries only its position (no unused normal/texcoord).

    :param size: Edge length of the quad, in world units.
    :return: A :class:`GeomNode` holding the flat quad.
    """
    fmt = GeomVertexFormat.getV3()
    vdata = GeomVertexData("ocean_plane", fmt, Geom.UHStatic)
    vdata.setNumRows(4)

    vw = GeomVertexWriter(vdata, "vertex")
    half = size * 0.5
    for x, y in ((-half, -half), (half, -half), (half, half), (-half, half)):
        vw.addData3f(x, y, 0.0)

    tris = GeomTriangles(Geom.UHStatic)
    tris.addVertices(0, 1, 2)
    tris.addVertices(0, 2, 3)

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("ocean_plane")
    node.addGeom(geom)
    return node


def make_swell_grid_mesh(grid_half: float, subdivs: int, outer_half: float) -> GeomNode:
    """
    Mesh for the geometric-swell prototype: a dense uniform grid of half-size
    ``grid_half`` (where the vertex shader displaces the surface by the swell),
    surrounded by a single ring of huge border cells reaching ``outer_half`` so
    the ocean still covers the view to the horizon.  The displacement is tapered
    to zero before ``grid_half`` (in the shader), so the flat border joins
    seamlessly — no projected-grid / clipmap machinery needed.

    :param grid_half: Half-size of the dense inner grid, in world units.
    :param subdivs: Number of subdivisions across the dense inner grid.
    :param outer_half: Half-size of the flat outer border, in world units.
    :return: A :class:`GeomNode` holding the grid mesh.
    """
    # Per-axis coordinates: outer border, then the uniform inner span, then the
    # far border.  The two border steps are huge but stay flat (taper → 0).
    #
    # Built with NumPy + bulk buffer uploads rather than per-vertex/-triangle
    # Python calls: at the default 256 subdivisions this is a 259x259 grid
    # (~67k verts, ~133k tris), and the naive loop spent ~210ms here. The
    # vectorised form is byte-identical and ~25x faster.
    coords = np.empty(subdivs + 3, dtype=np.float32)
    coords[0] = -outer_half
    coords[1 : subdivs + 2] = (
        -grid_half + 2.0 * grid_half * np.arange(subdivs + 1) / subdivs
    )
    coords[subdivs + 2] = outer_half
    m = coords.size

    # Vertex positions (m*m, 3): vertex j*m + i sits at (coords[i], coords[j], 0).
    verts = np.zeros((m * m, 3), dtype=np.float32)
    verts[:, 0] = np.tile(coords, m)
    verts[:, 1] = np.repeat(coords, m)

    fmt = GeomVertexFormat.getV3()
    vdata = GeomVertexData("ocean_grid", fmt, Geom.UHStatic)
    vdata.setNumRows(m * m)
    memoryview(vdata.modifyArray(0)).cast("B")[: verts.nbytes] = verts.tobytes()

    # Two triangles per cell, matching the original winding:
    #   (v0, v0+1, v0+m) and (v0+1, v0+m+1, v0+m), with v0 = j*m + i.
    jj, ii = np.meshgrid(np.arange(m - 1), np.arange(m - 1), indexing="ij")
    v0 = (jj * m + ii).ravel().astype(np.uint32)
    tri = np.empty((v0.size, 6), dtype=np.uint32)
    tri[:, 0] = v0
    tri[:, 1] = v0 + 1
    tri[:, 2] = v0 + m
    tri[:, 3] = v0 + 1
    tri[:, 4] = v0 + m + 1
    tri[:, 5] = v0 + m
    indices = tri.reshape(-1)

    tris = GeomTriangles(Geom.UHStatic)
    # >65535 verts at the default subdivisions, so indices must be 32-bit.
    tris.setIndexType(GeomEnums.NT_uint32)
    tris.addNextVertices(indices.size)
    memoryview(tris.modifyVertices()).cast("B")[: indices.nbytes] = indices.tobytes()

    geom = Geom(vdata)
    geom.addPrimitive(tris)
    node = GeomNode("ocean_grid")
    node.addGeom(geom)
    return node


class Ocean:
    #: Terrain material, read at laser-hit time to pick a spark colour.
    material = "water"

    def __init__(
        self,
        game: FlightState,
        water_color: LVecBase3f = LVecBase3f(0.02, 0.06, 0.14),
        ripple_strength: float = 0.02,
        wind_dir: LVecBase2f = LVecBase2f(1.0, 0.0),
        wind_strength: float = 0.5,
        wave_iterations: int = 36,
        geometric_swell: bool = False,
        swell_grid_subdivs: int = 512,
        swell_grid_half: float = 4000.0,
        swell_amplitude: float = 20.0,
        swell_scale: float = 0.004,
        swell_drift: float = 0.1,
        fm_depth: float = 0.2,
        wave_fade_near: float = 300.0,
        wave_fade_far: float = 5000.0,
        wave_fade_k2: float = 0.001,
        vert_shader: Path = DATAFILES_PATH / "shaders/ocean.vert",
        frag_shader: Path = DATAFILES_PATH / "shaders/ocean.frag",
    ) -> None:
        """
        Build the ocean surface, its shared reflection buffer, and shader.

        :param game: The game instance.
        :param water_color: Deep-water scatter colour.
        :param ripple_strength: Normal-based UV perturbation strength.
        :param wind_dir: Wind direction in the XY plane (normalised).
        :param wind_strength: How strongly the waves align to the wind; 0 =
            random, 1 = fully aligned.
        :param wave_iterations: Wave-detail quality knob; higher is sharper but
            costlier (e.g. 16 or 36).
        :param geometric_swell: Prototype mode that geometrically displaces the
            surface by the swell rather than only shading it.
        :param swell_grid_subdivs: Tessellation of the dense centre grid used by
            the geometric-swell mode.
        :param swell_grid_half: Half-size of the dense grid, in world units.
        :param swell_amplitude: Vertical swell displacement, in world units.
        :param swell_scale: Swell spatial frequency, shared by the vertex and
            fragment shaders; a long wavelength so the geometric-swell mesh
            samples it without aliasing.
        :param swell_drift: Swell scroll speed along the wind, shared by the
            vertex and fragment shaders.
        :param fm_depth: Small-wave frequency-modulation depth, in radians; the
            swell field modulates the wave phase to break the dominant octave's
            tiling (0 = off). Fragment-only; does not affect the geometric-swell
            displacement.
        :param wave_fade_near: Distance, in world units, below which small waves
            are at full detail.
        :param wave_fade_far: Distance, in world units, beyond which small waves
            are fully suppressed.
        :param wave_fade_k2: Exponential decay rate for the iteration count
            (``iter = max_iter * exp(-k2 * dist)``).
        :param vert_shader: Path to ``ocean.vert``.
        :param frag_shader: Path to ``ocean.frag``.
        """
        self.game = game
        self.id = uuid.uuid4()
        self.base_node = self.game.root_node.attachNewNode("ocean")

        # ── Reflection buffer (shared by all LOD levels) ──────────────────────
        refl_scale = self.game.app.graphics_settings.config["render"][
            "reflection_scale"
        ]
        self.refl_tex, uv_scale = self.make_reflection_buffer(refl_scale, water_color)

        # ── Shader (shared by all LOD levels) ─────────────────────────────────
        shader = Shader.load(Shader.SL_GLSL, vertex=vert_shader, fragment=frag_shader)

        # ── Camera-locked surface ─────────────────────────────────────────────
        # Sized past the far clip so its edges are never visible; it follows the
        # camera in XY each frame so the view is always covered to the horizon.
        # Flat single quad by default; a dense displaced grid when geometric
        # swell is enabled (prototype).
        plane_size = self.game.app.camLens.getFar() * 2.0 * _PLANE_FAR_FACTOR
        if geometric_swell:
            mesh = make_swell_grid_mesh(
                swell_grid_half, swell_grid_subdivs, plane_size * 0.5
            )
        else:
            mesh = make_plane_mesh(plane_size)
        self.ocean_node = self.base_node.attachNewNode(mesh)
        self.ocean_node.setShader(shader)
        self.ocean_node.setShaderInput("iTime", 0.0)
        self.ocean_node.setShaderInput("iCameraPos", LVecBase3f(0, 0, 20))
        self.ocean_node.setShaderInput("iWaterColor", water_color)
        self.ocean_node.setShaderInput("iReflectionTex", self.refl_tex)
        self.ocean_node.setShaderInput("iRippleStrength", ripple_strength)
        self.ocean_node.setShaderInput("iWindDir", wind_dir)
        self.ocean_node.setShaderInput("iWindStrength", wind_strength)
        self.ocean_node.setShaderInput(
            "iIterationsNormal", min(int(wave_iterations), _MAX_WAVE_ITER)
        )
        self.ocean_node.setShaderInput(
            "iWaveDirs", compute_wave_dirs(wind_dir, wind_strength)
        )
        self.ocean_node.setShaderInput("uReflMVP", LMatrix4f.identMat())
        self.ocean_node.setShaderInput("uReflUVScale", uv_scale)
        # Geometric-swell prototype: vertex-shader displacement (off by default).
        self.ocean_node.setShaderInput("uGeometricSwell", 1 if geometric_swell else 0)
        self.ocean_node.setShaderInput("uSwellAmplitude", float(swell_amplitude))
        self.ocean_node.setShaderInput("uSwellGridHalf", float(swell_grid_half))
        # Swell frequency/drift shared by the vertex and fragment shaders.
        self.ocean_node.setShaderInput("iSwellScale", float(swell_scale))
        self.ocean_node.setShaderInput("iSwellDrift", float(swell_drift))
        # Swell-driven frequency modulation of the small waves (frag-only).
        self.ocean_node.setShaderInput("uFmDepth", float(fm_depth))
        self.ocean_node.setShaderInput("uDebugMode", 0)
        self.ocean_node.setShaderInput("uWaveOff", 0)
        self.ocean_node.setShaderInput("uExposure", 0.9)
        self.ocean_node.setShaderInput("uWaveFadeNear", float(wave_fade_near))
        self.ocean_node.setShaderInput("uWaveFadeFar", float(wave_fade_far))
        self.ocean_node.setShaderInput("uWaveFadeK2", float(wave_fade_k2))
        # Hide the ocean from the reflection camera
        self.ocean_node.hide(_OCEAN_BIT)

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

    def update(self) -> None:
        """Call every frame from your update task."""
        current_time = self.game.game_time.get_current_time()
        camera_pos = self.game.app.camera.getPos(self.base_node)
        self.mirror_camera()

        # Build reflection MVP once, share across all rings
        view = LMatrix4f()
        view.invertFrom(self.refl_cam.getMat(self.base_node))
        proj = self.refl_cam_node.getLens().getProjectionMat()
        mvp = view * proj

        # The valid (rendered) region of the reflection texture is buffer_size /
        # texture_size.  The texture is padded to a power of two only on pipelines
        # that require it (the default Panda3D pipeline); simplepbr renders into a
        # full-size NPOT texture, so the padding-based estimate set at init is
        # wrong there.  The texture's real size is only known once the buffer is
        # realized on the GPU, so refresh uReflUVScale on the first realized frame
        # from the actual dimensions — correct under either pipeline, no toggle.
        if not hasattr(self, "_uv_scale_set"):
            tex_w = self.refl_tex.getXSize()
            tex_h = self.refl_tex.getYSize()
            if tex_w > 0 and tex_h > 0:
                self._uv_scale_set = True
                uv_scale = LVecBase2f(
                    self.refl_buffer.getXSize() / tex_w,
                    self.refl_buffer.getYSize() / tex_h,
                )
                self.ocean_node.setShaderInput("uReflUVScale", uv_scale)

        # Keep the plane centred under the camera so the view is always covered.
        # The wave pattern is anchored in world space (shader reads world
        # position), so sliding the plane introduces no motion artifacts.
        self.ocean_node.setPos(camera_pos.x, camera_pos.y, 0.0)
        self.ocean_node.setShaderInput("iTime", current_time)
        self.ocean_node.setShaderInput("iCameraPos", camera_pos)
        self.ocean_node.setShaderInput("uReflMVP", mvp)

    def set_wave_iterations(self, iterations: int) -> None:
        """Adjust wave-detail quality at runtime (e.g. from a settings menu).

        Higher = sharper waves up close but more expensive per pixel; lower =
        smoother and cheaper.  Far/grazing water already uses fewer iterations.

        :param iterations: Wave-detail iteration count, clamped to the shader's
            maximum.
        """
        self.ocean_node.setShaderInput(
            "iIterationsNormal", min(int(iterations), _MAX_WAVE_ITER)
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def make_reflection_buffer(
        self, refl_scale: float, water_color: LVecBase3f
    ) -> tuple[Texture, LVecBase2f]:
        """
        Create the offscreen buffer and mirrored camera for planar reflections.

        :param refl_scale: Reflection resolution as a fraction of the 3D render
            size (< 1 renders reflections cheaper than the main view).
        :param water_color: Colour the buffer is cleared to, seen where the
            reflection camera renders nothing.
        :return: The reflection :class:`Texture` and the provisional UV scale
            (buffer size / padded texture size) for the first frame.
        """
        # Size off the 3D render resolution (which may be a downscale of the
        # window when render-scale is active) rather than the window itself, so
        # the reflection cost scales with the chosen internal resolution.
        render_w, render_h = self.game.app.graphics_manager.get_render_size()
        buf_w = max(1, int(render_w * refl_scale))
        buf_h = max(1, int(render_h * refl_scale))

        refl_tex = Texture("refl_tex")
        refl_tex.setWrapU(Texture.WMClamp)
        refl_tex.setWrapV(Texture.WMClamp)

        self.refl_buffer = self.game.app.win.makeTextureBuffer(
            "refl_buffer", buf_w, buf_h, refl_tex
        )
        self.refl_buffer.setSort(-100)
        # DEBUG: reflection-buffer background = bright red, to see where the
        # reflection camera renders nothing (no skybox/geometry) and the clear
        # colour shows through.
        self.refl_buffer.setClearColor(LVecBase4f(*water_color, 1))
        # self.refl_buffer.setClearColor((1.0, 0.0, 0.0, 1))

        self.refl_cam_node = Camera("refl_cam")
        # Use a wider lens than the main camera to avoid frustum culling
        # artifacts when turning quickly — the extra margin ensures reflected
        # objects are never culled at the edges of the reflection buffer.
        refl_lens = self.game.app.camLens.makeCopy()
        fov = self.game.app.camLens.getFov()
        refl_lens.setFov(fov.x * 1.4, fov.y * 1.4)
        # The reflection camera sits ~2*altitude further from the skybox's far
        # side than the main camera, so the skybox (scaled to the main camera's
        # far distance) gets clipped at the reflected zenith — a hole that grows
        # with altitude.  Push the reflection far plane well past the skybox so
        # it always renders in full.
        refl_lens.setFar(self.game.app.camLens.getFar() * 4.0)
        self.refl_cam_node.setLens(refl_lens)
        self.refl_cam = self.base_node.attachNewNode(self.refl_cam_node)

        # Use only the lower 20 bits, excluding bit 1 (ocean rings)
        self.refl_cam_node.setCameraMask(BitMask32(0xFFFFF & ~2))

        # TODO(perf): selectively cull objects from the reflection pass to save
        # rendering cost.  The reflection re-renders all scene geometry; objects
        # that contribute little to the reflection (small, distant, or visually
        # unimportant) can be excluded by reserving another camera-mask bit as a
        # "do not reflect" flag and hiding tagged objects from refl_cam_node
        # (same mechanism as _OCEAN_BIT above).  Best when there are many minor
        # objects; not worthwhile for a single large hero object.

        self.refl_buffer.makeDisplayRegion(0, 1, 0, 1).setCamera(self.refl_cam)

        clip_plane = PlaneNode("water_clip")
        clip_plane.setPlane(LPlane(0, 0, 1, 0))
        self.clip_np = self.base_node.attachNewNode(clip_plane)
        clip_attrib = ClipPlaneAttrib.makeAllOff().addOnPlane(self.clip_np)
        self.refl_cam_node.setInitialState(
            self.refl_cam_node.getInitialState().addAttrib(clip_attrib)
        )

        # Provisional UV scale for the first frame, before the buffer is realized
        # and its true (possibly padded) texture size is known.  update() refreshes
        # this from the actual texture dimensions on the first realized frame, which
        # is correct under both the padding (default) and NPOT (simplepbr) pipelines.
        uv_scale = LVecBase2f(
            buf_w / compute_next_power_of_2(buf_w),
            buf_h / compute_next_power_of_2(buf_h),
        )
        return refl_tex, uv_scale

    def mirror_camera(self) -> None:
        """Mirror the reflection camera across the water plane (Z = 0)."""
        pos = self.game.app.camera.getPos(self.base_node)
        hpr = self.game.app.camera.getHpr(self.base_node)
        self.refl_cam.setPos(self.base_node, pos.x, pos.y, -pos.z)
        self.refl_cam.setHpr(self.base_node, hpr.x, -hpr.y, -hpr.z)

    def clean(self) -> None:
        """
        Cleans the Ocean object
        """
        if self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass
        # Destroy the offscreen reflection buffer; removing base_node alone
        # leaves the buffer registered with the graphics engine, so it keeps
        # rendering its camera every frame (a leak across scene reloads).
        self.game.app.graphicsEngine.removeWindow(self.refl_buffer)
        self.base_node.removeNode()
        self.game = None
