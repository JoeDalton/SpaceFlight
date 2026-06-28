#version 140

in vec4 p3d_Vertex;

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform mat4 uReflMVP;

// Geometric-swell displacement (prototype, gated by uGeometricSwell). The swell
// height field below is the SAME one the fragment shader samples for its normal
// tilt (swellField / fbmNoise / smoothNoise / hash are duplicated verbatim so
// the geometry and the shading normal derive from one source of truth). The
// wavelength/drift are shared from Python via iSwellScale / iSwellDrift.
uniform int   uGeometricSwell;  // 1 = displace the surface, 0 = flat plane
uniform float uSwellAmplitude;  // vertical swell displacement in world units
uniform float uSwellGridHalf;   // half-size of the dense displaced grid (local units)
uniform float iSwellScale;      // swell spatial frequency
uniform float iSwellDrift;      // swell scroll speed along the wind
uniform vec2  iWindDir;         // normalised wind direction in XY
uniform float iTime;

out vec3 vWorldPos;
out vec4 vReflCoord;

// --- Swell height field (identical to ocean.frag) --------------------------
float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

float smoothNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(hash(i + vec2(0, 0)), hash(i + vec2(1, 0)), u.x),
        mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x),
        u.y);
}

float fbmNoise(vec2 p) {
    return smoothNoise(p) * 0.6
         + smoothNoise(p * 2.1 + vec2(5.3, 1.7)) * 0.4;
}

float swellField(vec2 w) {
    vec2 d1 = iWindDir;
    vec2 d2 = vec2(-iWindDir.y, iWindDir.x);  // perpendicular to the wind
    vec2 a = w * iSwellScale        + iTime * iSwellDrift        * d1;
    vec2 b = w * iSwellScale * 1.7  + iTime * iSwellDrift * 0.6  * d2;
    return fbmNoise(a) * fbmNoise(b);
}

void main() {
    vec4 wp = p3d_ModelMatrix * p3d_Vertex;

    // Vertical swell displacement, world-anchored (sampled at world XY so the
    // pattern does not slide as the camera-locked plane follows the camera).
    float h = 0.0;
    if (uGeometricSwell == 1) {
        // Taper to zero before the dense grid's edge so the displaced centre
        // joins the flat border ring seamlessly (see make_swell_grid_mesh).
        float r     = length(p3d_Vertex.xy);  // local radius within the grid
        float taper = 1.0 - smoothstep(uSwellGridHalf * 0.8, uSwellGridHalf, r);
        h = uSwellAmplitude * swellField(wp.xy) * taper;
    }
    wp.z += h;

    vWorldPos  = wp.xyz;
    // Reflection footprint stays on the flat z=0 plane (the fragment also forces
    // z=0), so displacing the surface never skews the reflection lookup.
    vReflCoord = uReflMVP * vec4(wp.xy, 0.0, 1.0);

    // The ocean's model matrix is a pure XY translation (the plane follows the
    // camera), so a world-z offset equals a local-z offset on the vertex.
    vec4 displacedVertex = p3d_Vertex + vec4(0.0, 0.0, h, 0.0);
    gl_Position = p3d_ModelViewProjectionMatrix * displacedVertex;
}
