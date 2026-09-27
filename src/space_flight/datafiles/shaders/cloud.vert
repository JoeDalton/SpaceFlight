#version 330
// Cloud billboard vertex shader. Builds the camera-facing quad from a particle
// position LOCAL to its cell, whose centre (wind + recycling) comes from the
// cellParams texture, so the vertex data never changes. The quad carries no colour
// and no silhouette: it only tells cloud.frag where in the volume it is.
// The field node has no transform of its own, so its model space is the
// cells' world frame (the parent), wherever that sits under render.
uniform mat4 p3d_ModelViewProjectionMatrix;
uniform vec3 camPos;
// R32F, rows of CELLS_PER_ROW cells, each [x, y, z, layerId].
uniform sampler2D cellParams;
// LAYER_VEC4S per cloud type (noise.pack_layer_params). Must be declared exactly as
// in cloud.frag, or the stages fail to link and nothing draws.
uniform vec4 layerParams[96];
uniform float nearFadeRadii;   // fade a billboard out within this many radii
// 1 / (2 * planet radius): the deck droops with distance to sink behind the
// horizon. cloud.frag undoes it before sampling the (flat) field.
uniform float earthCurvature;

in vec4 p3d_Vertex;            // particle position LOCAL to its cell centre
in vec2 p3d_MultiTexCoord0;    // quad corner [-1,+1]
in float i_radius;
in vec4  i_uv_st;              // atlas rect (u0, v0, du, dv)
in float i_cellId;

out vec2  vUv;          // place in the sprite, a THICKNESS profile
out vec3  worldPos;
out float vRadius;
out float vFade;        // recycle-boundary and near-camera fade
flat out int vLayer;

const int CELL_PARAMS_STRIDE = 4;
// Rows keep the texture under GL_MAX_TEXTURE_DIMENSION. Must match field.py.
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

    vec3 pworld = centre + p3d_Vertex.xyz;
    // Droop measured from the camera, before the billboard basis, so a drooped quad
    // still faces the camera squarely.
    vec2 horizontal = pworld.xy - camPos.xy;
    pworld.z -= dot(horizontal, horizontal) * earthCurvature;

    vec3 fwd    = normalize(camPos - pworld);
    vec3 upRef  = abs(fwd.z) > 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
    vec3 right  = normalize(cross(upRef, fwd));
    vec3 up     = cross(fwd, right);

    // Fibrous types stretch along the field's WORLD streak axis projected into the
    // quad plane (a local axis would swing as the camera turns). |along| is the
    // sine to the view ray, so a wisp seen end-on foreshortens to a disc, and the
    // degenerate end-on basis only occurs once the stretch is already 1.
    vec4 shape = layerParams[vLayer * LAYER_VEC4S + 10];
    float aspect = shape.x;
    float stretch = 1.0;
    if (aspect > 1.0001) {
        vec3 along = vec3(shape.yz, 0.0);
        along -= fwd * dot(along, fwd);
        float visible = length(along);
        if (visible > 1e-4) {
            right = along / visible;
            up    = cross(fwd, right);
        }
        stretch = mix(1.0, sqrt(aspect), visible);
    }

    vec2 corner = p3d_MultiTexCoord0;
    // Area-preserving, so the footprint and hence the optical depth are unchanged.
    vec3 wp     = pworld + right * (corner.x * i_radius * stretch)
                         + up    * (corner.y * i_radius / stretch);

    gl_Position = p3d_ModelViewProjectionMatrix * vec4(wp, 1.0);
    worldPos    = wp;
    vUv         = i_uv_st.xy + (corner * 0.5 + 0.5) * i_uv_st.zw;
    vRadius     = i_radius;

    // Recycle-boundary fade; the band is zero when the box recycles seamlessly.
    vFade = wrapFadeBand > 0.0
          ? 1.0 - smoothstep(wrapRadius - wrapFadeBand, wrapRadius,
                             max(abs(centre.x - camPos.x),
                                 abs(centre.y - camPos.y)))
          : 1.0;

    // Billboards the camera is inside would smear across the screen and clip
    // against the near plane; fading them lets the farther ones carry the look.
    if (nearFadeRadii > 0.0) {
        float toCamera = length(camPos - pworld);
        vFade *= smoothstep(0.0, nearFadeRadii * i_radius, toCamera);
    }
}
