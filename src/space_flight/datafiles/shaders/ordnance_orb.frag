#version 140

// The clouds in front (WorldBuilder's cloud_cover.glsl, on Panda's model
// path): the clouds write no depth, so this, drawn after them, fades itself
// by the cloud between the camera and the orb.
#pragma include "cloud_cover.glsl"
// Ordnance orb: a white-hot core and a soft halo of the ordnance's colour,
// drawn additively. Distances are measured in core radii; every look knob is
// a uniform fed from the header constants of fx/ordnance_orb.py.

uniform vec3  uColor;           // the ordnance's colour
uniform float uHaloFactor;      // card half-size / core radius
uniform float uCoreEdge;        // fraction of the core radius where its edge starts to soften
uniform float uCoreWhiteMix;    // 0: coloured core, 1: pure white core
uniform float uHaloSigma;       // gaussian width of the halo, core radii
uniform float uHaloIntensity;   // halo brightness
uniform float uIntensity;       // overall brightness (the colour's alpha)

in vec2  vCorner;
in float vDistance;
out vec4 fragColor;

void main() {
    // Distance from the centre, in core radii
    float d = length(vCorner) * uHaloFactor;
    float core = 1.0 - smoothstep(uCoreEdge, 1.0, d);
    float halo = exp(-(d * d) / (uHaloSigma * uHaloSigma))
                 * (1.0 - smoothstep(0.7 * uHaloFactor, uHaloFactor, d));

    vec3 coreColor = mix(uColor, vec3(1.0), uCoreWhiteMix);
    vec3 col = (coreColor * core + uColor * halo * uHaloIntensity) * uIntensity;
    if (max(col.r, max(col.g, col.b)) < 0.004) discard;

    // Additive (ONE, ONE): the colour alone
    col *= 1.0 - cloudCoverBefore(gl_FragCoord.xy, vDistance);
    fragColor = vec4(col, 1.0);
}
