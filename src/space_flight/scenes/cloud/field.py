"""
field.py — A field of in-scene billboard clouds: geometry, shaders, sorting,
wind/recycling, plus the game-facing wrapper.

Clouds are ordinary 3D geometry parented under a node in render.  They
depth-test against whatever is already in the depth buffer, so occlusion by
ships / terrain / cockpit is handled by the hardware — no depth prepass, no
composite, no power-of-two handling, no scene-depth plumbing, no near/far
coupling.

Configuration lives in ONE place: :class:`CloudField`'s constructor (and the
per-type :class:`CloudLayer` records it takes).  cloud.py builds the cloud
*shapes* (data + CPU shading); this module turns them into a drawable, animated
field.  :class:`Clouds` is a thin game adapter over :class:`CloudField`.

Transparency model
------------------
Particles use premultiplied-alpha "over" blending (frag = vec4(rgb*a, a) with
M_add, O_one, O_one_minus_incoming_alpha).  "over" is order-dependent, so the
particles must be drawn back-to-front; the order is kept correct by sorting:

  * Every particle of every cloud lives in ONE Geom (4 verts each); the static
    vertex data (local pos, radius, colour, uv) is uploaded once and never again
    — only the triangle INDEX buffer is reordered.
  * The sort is per cloud (segmented): clouds are ordered by centroid distance,
    particles within a cloud by distance.  Intra- and inter-cloud ordering are
    both correct; cross-cloud interleaving is only approximate where two clouds
    physically intersect.
  * The sort + index gather is spread across resort_frames frames in a
    round-robin (see :meth:`CloudField._restage`): one atomic index upload per
    cycle — no per-frame spike, at the cost of a few frames' draw-order latency.

Particle positions are stored RELATIVE to their cloud centroid; the centroids are
moved each frame by wind and recycled toroidally around the camera within the
domain box, so the heavy vertex data never changes — only a small per-cloud
centroid texture is re-uploaded.  The billboard is built in the vertex shader, so
the only per-frame CPU work is the incremental restage.

Mixing types: pass several :class:`CloudLayer` entries (e.g. cumulus + cirrus);
they share one Geom, so the single global sort orders every type together (layers
superpose correctly from any angle) — unlike separate fields, which don't sort
against each other.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

import numpy as np
from panda3d.core import (
    ColorBlendAttrib,
    Geom,
    GeomEnums,
    GeomNode,
    GeomTriangles,
    GeomVertexArrayFormat,
    GeomVertexData,
    GeomVertexFormat,
    InternalName,
    NodePath,
    OmniBoundingVolume,
    SamplerState,
    Shader,
    Texture,
    TransparencyAttrib,
    Vec3,
)

from space_flight.scenes.cloud.cloud import (
    CloudType,
    build_templates_iter,
    load_cloud_atlas,
)

# ── Per-type layer spec (the only structured, repeating config) ─────────────────


@dataclass
class CloudLayer:
    """One type's worth of clouds in a field.

    cloud_type     CUMULUS / STRATUS / CIRRUS / CUMULONIMBUS (shape preset)
    count          number of cloud placements of this type
    altitude       (min, max) z the placements are scattered between
    n_templates    distinct shapes built once and reused across the count
    density_scale  alpha trim (alpha = particle density x this)
    overrides      per-type shape/optical overrides for build_cloud_particles
    """

    cloud_type: CloudType
    count: int
    altitude: tuple = (1000.0, 1500.0)
    n_templates: int = 8
    density_scale: float = 0.7
    overrides: Optional[dict] = None


def _default_layers():
    """:returns: a sensible default cumulus + cirrus layer list."""
    return [
        CloudLayer(
            CloudType.CUMULUS, count=300, altitude=(1000.0, 1500.0), n_templates=12
        ),
        CloudLayer(
            CloudType.CIRRUS, count=120, altitude=(8000.0, 8500.0), n_templates=6
        ),
    ]


# ── Shaders (travel with the geometry they describe) ────────────────────────────

_VERT = """
#version 330
// Per-vertex: a quad corner in [-1,+1] (p3d_MultiTexCoord0), the particle position
// LOCAL to its cloud centroid (p3d_Vertex), its colour (p3d_Color), radius, atlas
// rect, and cloud id.  The cloud centroid is looked up from the cloudCentres
// texture (moved each frame by wind + recycling on the CPU), so the per-particle
// vertex data never changes.  The billboard is built here.
uniform mat4 p3d_ViewProjectionMatrix;
uniform vec3 camPos;
uniform sampler2D cloudCentres;   // R32F, width 3*K: [x,y,z] per cloud, flat
uniform float wrapRadius;         // half the recycle box (0 → wrap fade disabled)
uniform float wrapFadeBand;       // metres over which a cloud fades at the box face

in vec4 p3d_Vertex;            // particle position LOCAL to its cloud centroid
in vec2 p3d_MultiTexCoord0;    // quad corner [-1,+1]
in vec4 p3d_Color;             // pre-shaded RGBA (a = opacity)
in float i_radius;
in vec4  i_uv_st;              // (u0, v0, du, dv)
in float i_cloudId;

out vec2 uv;
out vec4 vColor;
out vec3 worldPos;
out float vWrapFade;

void main() {
    int b = int(i_cloudId + 0.5) * 3;
    vec3 centre = vec3(texelFetch(cloudCentres, ivec2(b,     0), 0).r,
                       texelFetch(cloudCentres, ivec2(b + 1, 0), 0).r,
                       texelFetch(cloudCentres, ivec2(b + 2, 0), 0).r);
    vec3 pworld = centre + p3d_Vertex.xyz;   // particle centre in world space

    vec3 fwd    = normalize(camPos - pworld);
    // World-up reference, with a fallback when looking straight down the axis.
    vec3 upRef  = abs(fwd.z) > 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
    vec3 right  = normalize(cross(upRef, fwd));
    vec3 up     = cross(fwd, right);

    vec2 corner = p3d_MultiTexCoord0;
    vec3 wp     = pworld + right * (corner.x * i_radius)
                         + up    * (corner.y * i_radius);

    gl_Position = p3d_ViewProjectionMatrix * vec4(wp, 1.0);
    worldPos    = wp;
    vColor      = p3d_Color;
    uv          = i_uv_st.xy + (corner * 0.5 + 0.5) * i_uv_st.zw;

    // Wrap-boundary fade: a cloud fades out as its centre nears the recycle box
    // face (Chebyshev distance in XY from the camera), so teleporting it to the
    // opposite face when it recycles is never visible.
    float edge = max(abs(centre.x - camPos.x), abs(centre.y - camPos.y));
    vWrapFade  = wrapRadius > 0.0
               ? 1.0 - smoothstep(wrapRadius - wrapFadeBand, wrapRadius, edge)
               : 1.0;
}
"""

_FRAG = """
#version 330
uniform sampler2D p3d_Texture0;
uniform vec3  lightDir;      // FROM scene TOWARD sun (== sun_dir)
uniform vec3  viewPos;
uniform vec3  sunGlowColor;
uniform float hgForward;     // forward HG asymmetry (silver lining when back-lit)
uniform float glowStrength;
uniform float hgBackward;    // backward HG asymmetry (< 0 → peaks front-lit)
uniform float backStrength;  // diffuse boost when front-lit (sun behind viewer)

in  vec2 uv;
in  vec4 vColor;
in  vec3 worldPos;
in  float vWrapFade;
out vec4 fragColor;

float hg(float c, float g) {
    float g2 = g * g;
    return (1.0 - g2) / (4.0 * 3.14159 * pow(1.0 + g2 - 2.0 * g * c, 1.5));
}

void main() {
    vec4 tex = texture(p3d_Texture0, uv);
    if (tex.a < 0.01) discard;

    vec3  V    = normalize(viewPos - worldPos);
    float cosT = dot(lightDir, -V);

    // Forward scatter → the bright "silver lining" halo when looking toward the
    // sun through a cloud edge.
    float hgFwd = hg( 1.0, hgForward);
    float hgBck = hg(-1.0, hgForward);
    float phase = (hg(cosT, hgForward) - hgBck) / (hgFwd - hgBck);

    vec3  diff = vColor.rgb * tex.rgb;
    vec3  glow = glowStrength * phase * sunGlowColor;

    // Back scatter → brightening of the near, sun-facing shell when the sun is
    // behind the viewer.  A backward HG lobe (hgBackward < 0) peaks at cosT = -1;
    // normalised to [0,1] (0 = back-lit, 1 = front-lit) and used to boost diffuse.
    float bMin      = hg( 1.0, hgBackward);
    float bMax      = hg(-1.0, hgBackward);
    float backPhase = clamp((hg(cosT, hgBackward) - bMin) / (bMax - bMin), 0.0, 1.0);
    diff *= (1.0 + backStrength * backPhase);

    float a = tex.a * vColor.a * vWrapFade;
    fragColor = vec4((diff + glow) * a, a);   // premultiplied "over"
}
"""


# ── Static vertex format; only the index buffer is reordered per frame ──────────


def _vertex_format() -> GeomVertexFormat:
    """:returns: the interleaved per-vertex format — local position, quad corner,
    pre-shaded RGBA, radius, atlas rect, and cloud id (15 floats / vertex)."""
    fmt = GeomVertexArrayFormat()
    fmt.add_column(
        InternalName.get_vertex(), 3, GeomEnums.NT_float32, GeomEnums.C_point
    )
    fmt.add_column(
        InternalName.get_texcoord(), 2, GeomEnums.NT_float32, GeomEnums.C_texcoord
    )
    fmt.add_column(InternalName.get_color(), 4, GeomEnums.NT_float32, GeomEnums.C_color)
    fmt.add_column(
        InternalName.make("i_radius"), 1, GeomEnums.NT_float32, GeomEnums.C_other
    )
    fmt.add_column(
        InternalName.make("i_uv_st"), 4, GeomEnums.NT_float32, GeomEnums.C_texcoord
    )
    fmt.add_column(
        InternalName.make("i_cloudId"), 1, GeomEnums.NT_float32, GeomEnums.C_other
    )
    combined = GeomVertexFormat()
    combined.add_array(fmt)
    return GeomVertexFormat.register_format(combined)


# Quad corners (CCW): BL, BR, TR, TL — reused as the [-1,+1] offset and UV basis.
_CORNERS = np.array([(-1, -1), (1, -1), (1, 1), (-1, 1)], dtype=np.float32)
# Two triangles per quad, as offsets into a particle's 4-vertex block.
_QUAD_TRIS = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
# Particles per chunk when building/uploading the static vertex buffer, so its
# ~200ms of NumPy work is spread across several frames instead of one.
_VBUF_BLOCK = 20000


def _assemble(templates, placements):
    """Scatter templates into placements and pad to a uniform per-cloud size.

    Every cloud is padded to the largest template's particle count with
    zero-radius particles (which render nothing), so the per-frame draw-order sort
    can be one vectorised segmented argsort over a (n_clouds, n_per) array.

    :param templates: template dicts from :func:`cloud.build_templates`
    :param placements: list of (template_index, offset_xyz)
    :returns: (local, radii, colors, uv_rects, cloud_centres, n_per) — the
        per-particle arrays shaped (n_clouds, n_per, …) (local is each
        particle's offset from its cloud centroid), the (n_clouds, 3) centroids,
        and the padded per-cloud particle count
    """
    n_clouds = len(placements)
    n_per = max(len(templates[ti]["pos"]) for ti, _ in placements)

    local = np.zeros((n_clouds, n_per, 3), np.float32)
    radii = np.zeros((n_clouds, n_per), np.float32)  # 0 → degenerate (no frags)
    colors = np.zeros((n_clouds, n_per, 4), np.float32)
    uv_rects = np.zeros((n_clouds, n_per, 4), np.float32)
    cloud_centres = np.zeros((n_clouds, 3), np.float32)
    for cloud_idx, (template_idx, offset) in enumerate(placements):
        template = templates[template_idx]
        count = len(template["pos"])
        local[cloud_idx, :count] = template["pos"]  # templates are origin-centred
        radii[cloud_idx, :count] = template["radii"]
        colors[cloud_idx, :count] = template["colors"]
        uv_rects[cloud_idx, :count] = template["uv"]
        cloud_centres[cloud_idx] = np.asarray(offset, dtype=np.float32)
    return local, radii, colors, uv_rects, cloud_centres, n_per


class CloudField:
    """A drawable, wind-driven, depth-sorted field of mixed-type billboard clouds.

    All field settings live here (the single configuration surface).  Construct
    with a parent NodePath, a loader (for the atlas), and a list of
    :class:`CloudLayer`; then call :meth:`update` once per frame.
    """

    def __init__(
        self,
        parent,
        game,
        layers=None,
        *,
        domain=24000.0,
        wind=(20.0, 0.0, 0.0),
        sun_direction=(0.2, 1.0, 0.1),
        sun_color=(1.0, 0.8, 0.2),
        ambient_color=(0.4, 0.10, 0.40),
        hg_forward=0.85,
        glow_strength=0.3,
        hg_backward=-0.5,
        back_strength=0.3,
        resort_frames=8,
        wrap_fade_band=None,
        seed=7,
        defer_build=False,
        use_cache=False,
    ):
        """Build the field's geometry and shading from a list of layers.

        :param parent: NodePath the cloud geometry is reparented under
        :param game: the game object (used to load the sprite atlas via asset_manager)
        :param layers: list of :class:`CloudLayer` (defaults to cumulus + cirrus)
        :param domain: side of the camera-centred box clouds scatter/recycle within
        :param wind: metres/second the clouds drift each frame
        :param sun_direction: vector FROM the scene TOWARD the sun (lighting)
        :param sun_color: RGB of direct sunlight
        :param ambient_color: RGB of the ambient/sky fill
        :param hg_forward: forward Henyey-Greenstein asymmetry (silver lining)
        :param glow_strength: strength of the forward-scatter glow
        :param hg_backward: backward HG asymmetry (< 0 peaks when front-lit)
        :param back_strength: diffuse boost when the sun is behind the viewer
        :param resort_frames: frames to spread one full re-sort over (de-spike)
        :param wrap_fade_band: metres of fade at the recycle box face
            (defaults to 12% of domain)
        :param seed: RNG seed for shapes and placement
        :param defer_build: if True, do not build in the constructor; the caller
            must drive :meth:`build` (a generator) instead, one step per frame.
        :param use_cache: if True, load/save the generated cloud templates via
            the on-disk template cache. Off by default so tests and tools never
            touch the user-global cache; the game's loading path opts in.
        """
        self._parent = parent
        self._game = game
        self._use_cache = use_cache
        self._layers = layers if layers is not None else _default_layers()
        self._domain = domain
        self._wind_arg = wind
        self._sun_direction = sun_direction
        self._sun_color_arg = sun_color
        self._ambient_color_arg = ambient_color
        self._hg_forward = hg_forward
        self._glow_strength = glow_strength
        self._hg_backward = hg_backward
        self._back_strength = back_strength
        self._resort_frames_arg = resort_frames
        self._wrap_fade_band_arg = wrap_fade_band
        self._seed = seed

        # Build immediately unless the caller wants to drive build() per frame.
        if not defer_build:
            for _ in self.build():
                pass

    def build(self):
        """
        Generator that builds the field, yielding between chunks of work so a
        loader can spread the cost across frames rather than freezing on one
        construction.

        Template generation dominates the field's build cost (~18-40 ms each;
        the whole default field is ~0.6 s); the static vertex buffer is then
        built and uploaded in particle-blocks. Each yield ends a chunk.
        """
        # Local aliases so the assembly code below reads like a plain build.
        parent = self._parent
        game = self._game
        layers = self._layers
        domain = self._domain
        wind = self._wind_arg
        resort_frames = self._resort_frames_arg
        wrap_fade_band = self._wrap_fade_band_arg
        hg_forward = self._hg_forward
        glow_strength = self._glow_strength
        hg_backward = self._hg_backward
        back_strength = self._back_strength
        seed = self._seed

        sun_color = np.asarray(self._sun_color_arg, dtype=float)[:3]
        ambient_color = np.asarray(self._ambient_color_arg, dtype=float)[:3]
        sun_dir = np.asarray(self._sun_direction, dtype=float)[:3]
        sun_dir = sun_dir / np.linalg.norm(sun_dir)

        atlas_tex, rects = load_cloud_atlas(game)

        # ── Build per-layer shapes, scatter placements within the domain box ──
        half = domain * 0.5
        rng = np.random.default_rng(seed)
        templates, placements = [], []
        for layer in layers:
            first_template = len(templates)
            # One template per frame: this is the heavy, stutter-causing work.
            for template in build_templates_iter(
                layer.n_templates,
                rects,
                sun_color,
                ambient_color,
                sun_dir,
                cloud_type=layer.cloud_type,
                density_scale=layer.density_scale,
                base_seed=seed,
                overrides=layer.overrides,
                use_cache=self._use_cache,
            ):
                templates.append(template)
                yield f"cloud_template[{layer.cloud_type.value}]"
            n_layer_templates = len(templates) - first_template
            z_lo, z_hi = layer.altitude
            # Cycle this layer's placements through its own templates, scattered
            # over the domain box at the layer's altitude.
            for i in range(layer.count):
                placements.append(
                    (
                        first_template + i % n_layer_templates,
                        (
                            float(rng.uniform(-half, half)),
                            float(rng.uniform(-half, half)),
                            float(rng.uniform(z_lo, z_hi)),
                        ),
                    )
                )

        # ── Vertex/GPU assembly, split across frames so its ~170ms of NumPy
        # buffer-building + uploads doesn't land in one frame. Each labelled
        # yield ends a natural chunk. ──
        local, radii, colors, uv_rects, cloud_centres, n_per = _assemble(
            templates, placements
        )

        self._local = np.ascontiguousarray(local.reshape(-1, 3), np.float32)
        n_particles = len(self._local)
        self._n = n_particles
        self._cloud_centres = np.ascontiguousarray(cloud_centres, np.float32)  # (K,3)
        self._n_per = int(n_per)
        self._n_clouds = n_particles // self._n_per

        # Incremental round-robin restage state.
        self._resort_frames = max(1, int(resort_frames))
        self._stage = np.empty(n_particles * 6, dtype=np.uint32)  # staging index buffer
        self._draw_order = None
        self._cyc_cursor = 0
        # Wind + toroidal recycling (centroids dynamic only when either is active).
        self._wind = np.asarray(wind, dtype=np.float32)
        self._wrap_radius = float(domain) * 0.5
        self._wrap_band = (
            0.12 * float(domain) if wrap_fade_band is None else float(wrap_fade_band)
        )
        self._dynamic = bool(self._wind.any()) or self._wrap_radius > 0.0
        yield "cloud_assemble"

        # ── Static vertex data: 4 verts per particle, 15 floats each ─────────
        # Built and uploaded in particle-blocks so the ~200ms of NumPy buffer
        # construction + copy is spread across frames instead of one big spike.
        vdata = GeomVertexData("cloud_field", _vertex_format(), GeomEnums.UH_static)
        vdata.set_num_rows(4 * n_particles)
        dst = memoryview(vdata.modify_array(0)).cast("B")
        colors_flat = colors.reshape(-1, 4)
        radii_flat = radii.reshape(-1)
        uv_flat = uv_rects.reshape(-1, 4)
        row_bytes = 15 * 4  # bytes per vertex (15 float32)
        for b0 in range(0, n_particles, _VBUF_BLOCK):
            b1 = min(b0 + _VBUF_BLOCK, n_particles)
            m = b1 - b0
            block = np.empty((4 * m, 15), dtype=np.float32)
            block[:, 0:3] = np.repeat(self._local[b0:b1], 4, axis=0)
            block[:, 3:5] = np.tile(_CORNERS, (m, 1))
            block[:, 5:9] = np.repeat(colors_flat[b0:b1], 4, axis=0)
            block[:, 9] = np.repeat(radii_flat[b0:b1], 4)
            block[:, 10:14] = np.repeat(uv_flat[b0:b1], 4, axis=0)
            # Per-vertex cloud id = particle index // n_per (fetches the centroid).
            block[:, 14] = np.repeat(np.arange(b0, b1) // self._n_per, 4).astype(
                np.float32
            )
            dst[b0 * 4 * row_bytes : b1 * 4 * row_bytes] = memoryview(block).cast("B")
            yield "cloud_vertexbuf"

        # ── Index buffer: reordered every frame (uint32 for >16k verts) ──────
        self._tris = GeomTriangles(GeomEnums.UH_dynamic)
        self._tris.set_index_type(GeomEnums.NT_uint32)
        self._tris.add_next_vertices(6 * n_particles)  # allocate; overwritten below
        # Per-particle base triangle indices: particle p → its 4 verts at 4p..4p+3.
        self._tri_base = (
            np.arange(n_particles, dtype=np.uint32)[:, None] * 4
        ) + _QUAD_TRIS
        # Seed a valid (natural) order BEFORE add_primitive (it validates indices).
        self._stage[:] = self._tri_base.reshape(-1)
        memoryview(self._tris.modify_vertices()).cast("B")[
            : self._stage.nbytes
        ] = self._stage.tobytes()
        yield "cloud_indexbuf"

        geom = Geom(vdata)
        geom.add_primitive(self._tris)
        gnode = GeomNode("cloud_field")
        gnode.add_geom(geom)

        self.node = NodePath(gnode)
        # Billboards extend past their centres; skip culling rather than inflate bounds.
        self.node.node().set_bounds(OmniBoundingVolume())
        self.node.node().set_final(True)
        self.node.reparent_to(parent)

        self.node.set_shader(Shader.make(Shader.SL_GLSL, _VERT, _FRAG))
        self.node.set_texture(atlas_tex)
        self.node.set_transparency(TransparencyAttrib.M_none)  # blend set explicitly
        self.node.set_depth_write(False)  # translucent: don't occlude each other in Z
        self.node.set_depth_test(True)  # but DO get occluded by opaque scene
        self.node.set_bin("fixed", 50)  # drawn after opaque geometry
        self.node.set_attrib(
            ColorBlendAttrib.make(
                ColorBlendAttrib.M_add,
                ColorBlendAttrib.O_one,
                ColorBlendAttrib.O_one_minus_incoming_alpha,
            )
        )

        # Per-cloud centroid texture (R32F, width 3*K: x,y,z per cloud, flat).
        # Single-channel float → no BGRA channel-order ambiguity.
        self._centre_tex = Texture("cloud_centres")
        self._centre_tex.setup_2d_texture(
            3 * self._n_clouds, 1, Texture.T_float, Texture.F_r32
        )
        self._centre_tex.set_magfilter(SamplerState.FT_nearest)
        self._centre_tex.set_minfilter(SamplerState.FT_nearest)
        self._upload_centres()

        self.node.set_shader_input("camPos", Vec3(0, 0, 0))
        self.node.set_shader_input("viewPos", Vec3(0, 0, 0))
        self.node.set_shader_input("lightDir", Vec3(*sun_dir))  # static sun
        self.node.set_shader_input("sunGlowColor", Vec3(*sun_color))
        self.node.set_shader_input("hgForward", float(hg_forward))
        self.node.set_shader_input("glowStrength", float(glow_strength))
        self.node.set_shader_input("hgBackward", float(hg_backward))
        self.node.set_shader_input("backStrength", float(back_strength))
        self.node.set_shader_input("cloudCentres", self._centre_tex)
        self.node.set_shader_input("wrapRadius", float(self._wrap_radius))
        self.node.set_shader_input("wrapFadeBand", float(self._wrap_band))

    # ── Per-frame ─────────────────────────────────────────────────────────────

    def update(self, cam_pos: Vec3, dt: float = 0.0):
        """Advance the field one frame: re-face billboards, drift + recycle the
        clouds, and continue the incremental draw-order re-sort.

        :param cam_pos: current camera world position
        :param dt: seconds since the last frame (drives wind drift)
        """
        # Cheap, every frame: billboards re-face the camera (built in the VS).
        self.node.set_shader_input("camPos", cam_pos)
        self.node.set_shader_input("viewPos", cam_pos)
        cam_xyz = np.array([cam_pos.x, cam_pos.y, cam_pos.z], dtype=np.float32)

        if self._dynamic:
            if dt:
                self._cloud_centres += self._wind * dt  # wind drift
            if self._wrap_radius > 0.0:
                # Toroidal recycle: wrap each centroid back into the camera-centred
                # box on X/Y by subtracting the nearest whole box-width.
                box_width = 2.0 * self._wrap_radius
                rel = self._cloud_centres[:, :2] - cam_xyz[:2]
                self._cloud_centres[:, :2] = (
                    cam_xyz[:2] + rel - box_width * np.round(rel / box_width)
                )
            self._upload_centres()

        self._restage(cam_xyz)

    def remove(self):
        """Detach the cloud geometry from the scene."""
        self.node.removeNode()

    def _upload_centres(self):
        """Push the current per-cloud centroids into the GPU centroid texture."""
        self._centre_tex.set_ram_image(
            np.ascontiguousarray(self._cloud_centres.reshape(-1), np.float32).tobytes()
        )

    def _restage(self, cam_xyz):
        """Re-sort and re-upload one round-robin slice of the index buffer.

        Each frame handles n_clouds / resort_frames clouds; a fresh cloud
        draw-order is snapshotted at the start of each cycle, and the index buffer
        is uploaded once per completed cycle.  This spreads both the sort and the
        index gather, so there is no per-frame spike.

        :param cam_xyz: current camera world position as a 3-float array
        """
        n_clouds, n_per = self._n_clouds, self._n_per
        clouds_per_frame = -(-n_clouds // self._resort_frames)  # ceil division
        if self._draw_order is None or self._cyc_cursor >= n_clouds:
            # New cycle: snapshot the cloud draw order, far → near (cheap K-argsort).
            centre_rel = self._cloud_centres - cam_xyz
            self._draw_order = np.argsort(
                -np.einsum("ij,ij->i", centre_rel, centre_rel)
            )
            self._cyc_cursor = 0

        start = self._cyc_cursor
        end = min(start + clouds_per_frame, n_clouds)
        cloud_ids = self._draw_order[start:end]  # clouds at these draw-ranks
        # Re-sort just these clouds' particles; world centre = centroid + local.
        world_pos = (
            self._cloud_centres[cloud_ids][:, None, :]
            + self._local.reshape(n_clouds, n_per, 3)[cloud_ids]
        )
        offset = world_pos - cam_xyz  # (m, n_per, 3)
        dist_sq = np.einsum("ijk,ijk->ij", offset, offset)  # (m, n_per)
        intra_order = np.argsort(-dist_sq, axis=1)  # far → near
        particle_ids = cloud_ids[:, None] * n_per + intra_order  # global ids
        # Write these clouds' tri-index blocks into their (contiguous) buffer slots.
        self._stage[start * n_per * 6 : end * n_per * 6] = self._tri_base[
            particle_ids
        ].reshape(-1)
        self._cyc_cursor = end

        if end >= n_clouds:  # cycle complete → ONE atomic upload
            memoryview(self._tris.modify_vertices()).cast("B")[
                : self._stage.nbytes
            ] = self._stage.tobytes()


# ── Game-facing wrapper ─────────────────────────────────────────────────────────


class Clouds:
    """Drops a :class:`CloudField` into a level following the scene convention:
    construct with the game, register a per-frame update in
    game.method_lists, expose clean.  All CloudField settings (layers,
    domain, wind, sun, lighting, …) pass straight through as keyword arguments.

    Usage::

        from space_flight.scenes.cloud.field import Clouds, CloudLayer
        self.clouds = Clouds(game, sun_direction=Vec3(0.2, 1.0, 0.1))
    """

    def __init__(
        self, game, layers=None, *, defer_build=False, use_cache=False, **field_kwargs
    ):
        self.game = game
        self.id = uuid.uuid4()
        self.field = CloudField(
            parent=game.root_node,
            game=game,
            layers=layers,
            defer_build=defer_build,
            use_cache=use_cache,
            **field_kwargs,
        )
        # When building synchronously the field is ready now; register the
        # per-frame update. Deferred builds register it at the end of build().
        if not defer_build:
            game.method_lists[self.id] = [self.update]

    def build(self):
        """
        Drive the deferred field build a chunk per frame, then register the
        per-frame update once the field is ready. Use with defer_build=True::

            self.clouds = Clouds(game, defer_build=True, ...)
            yield from self.clouds.build()
        """
        yield from self.field.build()
        self.game.method_lists[self.id] = [self.update]

    def update(self):
        """Per-frame: drive wind/recycle/sort against the current camera."""
        cam_pos = self.game.app.camera.get_pos(self.game.app.render)
        dt = self.game.game_time.get_time_step()
        self.field.update(cam_pos, dt)

    def clean(self):
        """Remove the per-frame update and detach the cloud geometry."""
        if self.game.method_lists:
            self.game.method_lists.pop(self.id, None)
        self.field.remove()
        self.game = None
