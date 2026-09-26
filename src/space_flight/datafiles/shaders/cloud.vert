#version 330
// Cloud billboard vertex shader.
//
// Per-vertex: a quad corner in [-1,+1] (p3d_MultiTexCoord0), the particle
// position LOCAL to its cell's centre (p3d_Vertex), its radius, its sprite rect,
// and its cell id.  Cell centres move every frame (wind, toroidal recycling) and
// come from the cellParams texture, so the heavy per-particle vertex data never
// changes.  The billboard is built here.
//
// The billboard carries no colour of its own, and no silhouette: it exists to
// tell the fragment shader WHERE in the volume it is and HOW MUCH volume sits
// behind each of its pixels (see cloud.frag). The sprite rect it carries is a
// thickness profile, not an outline -- the outline is a function of world
// position, which is what keeps overlapping billboards from showing as patches.
uniform mat4 p3d_ViewProjectionMatrix;
uniform vec3 camPos;
// R32F, width CELL_PARAMS_STRIDE*K, one row: per cell, flat, in order
// [x, y, z, layerId]. The layer id rides along here rather than in a vertex
// column because it is a property of a whole cell, and the cell fetch is already
// being paid for.
uniform sampler2D cellParams;
// Eleven vec4s per cloud type; see noise.pack_layer_params for the packing. Only
// the recycle box and the billboard shape are needed at this stage, but the
// declaration must match cloud.frag's EXACTLY -- a shared uniform declared with a
// different array size in the two stages fails to link ("has different type
// across different shaders"), and the clouds then draw nothing at all.
uniform vec4 layerParams[96];
uniform float nearFadeRadii;   // fade a billboard out within this many radii
// 1 / (2 * planet radius). The cloud deck is placed on a FLAT slab -- which is
// fine out to a few tens of km, where the drop is metres -- but a field reaching
// past ~40 km needs the curve: at 64 km the drop is 320 m and at 128 km it is
// 1.3 km, comparable to the whole slab thickness. Without it distant cloud floats
// above the horizon instead of sinking behind it. cloud.frag undoes this before
// sampling the field, which stays flat.
uniform float earthCurvature;

in vec4 p3d_Vertex;            // particle position LOCAL to its cell centre
in vec2 p3d_MultiTexCoord0;    // quad corner [-1,+1]
in float i_radius;
in vec4  i_uv_st;              // this particle's atlas rect (u0, v0, du, dv)
in float i_cellId;

out vec2  vUv;          // place in the puff sprite, which is a THICKNESS profile
out vec3  worldPos;     // this fragment's position on the quad, in world space
out float vRadius;
out float vFade;        // recycle-boundary and near-camera fade
flat out int vLayer;    // which cloud type's density field this billboard samples

const int CELL_PARAMS_STRIDE = 4;
// Cells are wrapped into ROWS rather than laid out in one long line. A single row
// would need STRIDE * n_cells texels, which runs into GL_MAX_TEXTURE_DIMENSION
// once the field has a few LOD shells -- and when the texture cannot be created
// every fetch returns zero, so every cell sits at the origin claiming layer 0 and
// the whole field collapses into one blob. Must match _CELLS_PER_ROW in field.py.
const int CELLS_PER_ROW = 1024;
const int LAYER_VEC4S = 12;

float cellParam(int cell, int index) {
    int row = cell / CELLS_PER_ROW;
    int column = (cell - row * CELLS_PER_ROW) * CELL_PARAMS_STRIDE + index;
    return texelFetch(cellParams, ivec2(column, row), 0).r;
}

void main() {
    int cell = int(i_cellId + 0.5);
    vec3 centre = vec3(cellParam(cell, 0), cellParam(cell, 1), cellParam(cell, 2));
    vLayer = int(cellParam(cell, 3) + 0.5);

    vec4 optical = layerParams[vLayer * LAYER_VEC4S + 5];
    float wrapRadius   = optical.z;
    float wrapFadeBand = optical.w;

    vec3 pworld = centre + p3d_Vertex.xyz;   // particle centre in world space
    // Droop with the planet's curve, measured from the camera so the deck falls
    // away in every direction and the horizon follows the viewer. Done before the
    // billboard basis, so a drooped quad still faces the camera squarely.
    vec2 horizontal = pworld.xy - camPos.xy;
    pworld.z -= dot(horizontal, horizontal) * earthCurvature;

    vec3 fwd    = normalize(camPos - pworld);
    // World-up reference, with a fallback when looking straight down the axis.
    vec3 upRef  = abs(fwd.z) > 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
    vec3 right  = normalize(cross(upRef, fwd));
    vec3 up     = cross(fwd, right);

    // ── Billboard shape ────────────────────────────────────────────────────────
    // A fibrous type (cirrus) stretches its quads along the field's own streak
    // direction, which is what turns a line of countable puffs into wisps: it is
    // ROUNDNESS that makes the eye resolve a billboard as a discrete object.
    //
    // The long axis must be a WORLD direction projected into the billboard plane,
    // not the quad's local X -- otherwise the wisps swing around as the camera
    // turns. And it comes from the FIELD (noise.streak_direction) rather than
    // being authored, so the quads and the field cannot comb different ways.
    vec4 shape = layerParams[vLayer * LAYER_VEC4S + 10];
    float aspect = shape.x;
    float stretch = 1.0;
    if (aspect > 1.0001) {
        vec3 along = vec3(shape.yz, 0.0);
        along -= fwd * dot(along, fwd);       // project onto the quad plane
        // |along| is the sine of the angle between the streak and the view ray,
        // so it falls to zero as the view swings onto the streak axis. Using it
        // to interpolate the stretch gives the right foreshortening for free: a
        // long thin wisp seen end-on reads as a disc.
        float visible = length(along);
        if (visible > 1e-4) {
            right = along / visible;
            up    = cross(fwd, right);
        }
        // Below that the direction is numerically meaningless -- but the stretch
        // has gone to 1 with it, and a square quad's orientation does not matter,
        // so the degeneracy heals itself and the fallback basis above will do.
        stretch = mix(1.0, sqrt(aspect), visible);
    }

    vec2 corner = p3d_MultiTexCoord0;
    // Area-preserving: sqrt(aspect) one way, 1/sqrt(aspect) the other. The quad's
    // footprint is therefore EXACTLY unchanged, and since the fragment's chord
    // still comes from i_radius, so is its optical depth -- no recalibration.
    vec3 wp     = pworld + right * (corner.x * i_radius * stretch)
                         + up    * (corner.y * i_radius / stretch);

    gl_Position = p3d_ViewProjectionMatrix * vec4(wp, 1.0);
    worldPos    = wp;
    vUv         = i_uv_st.xy + (corner * 0.5 + 0.5) * i_uv_st.zw;
    vRadius     = i_radius;

    // Recycle-boundary fade, when one is needed at all. A cell recycles by
    // teleporting one box width; when the box is a whole number of the field's
    // noise periods it lands where the field is bit-identical, so the teleport is
    // invisible and the CPU passes a zero band (see cloud.snap_to_noise_period).
    // Only an anisotropic field, whose two horizontal periods differ, cannot have
    // such a box and still needs to be faded across the boundary.
    vFade = wrapFadeBand > 0.0
          ? 1.0 - smoothstep(wrapRadius - wrapFadeBand, wrapRadius,
                             max(abs(centre.x - camPos.x),
                                 abs(centre.y - camPos.y)))
          : 1.0;

    // Near fade: a billboard the camera is nearly touching covers a huge part
    // of the screen, so its sprite reads as one big smeared blob rather than as
    // cloud, and it clips against the near plane as a hard-edged quad. Fading
    // it out over the last few radii keeps flying through a cloud looking like
    // volume: the billboards you are inside disappear, and the ones a little
    // further off carry the look.
    if (nearFadeRadii > 0.0) {
        float toCamera = length(camPos - pworld);
        vFade *= smoothstep(0.0, nearFadeRadii * i_radius, toCamera);
    }
}
