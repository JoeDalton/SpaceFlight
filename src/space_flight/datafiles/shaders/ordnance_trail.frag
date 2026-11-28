#version 140

// The clouds in front (WorldBuilder's cloud_cover.glsl, on Panda's model
// path): the clouds write no depth, so this, drawn after them, fades itself
// by the cloud between the camera and each fragment.
#pragma include "cloud_cover.glsl"
// Ordnance engine trail: the ordnance's colour, brightest along the ribbon's
// axis, fading with the point's age (vAlpha), additive.

uniform vec3  uColor;
uniform float uEdgeStart;  // |side| where the soft edge starts (1 = hard edge)

in float vSide;
in float vAlpha;
in float vDistance;
out vec4 fragColor;

void main() {
    float across = 1.0 - smoothstep(uEdgeStart, 1.0, abs(vSide));
    vec3 col = uColor * vAlpha * across;
    if (max(col.r, max(col.g, col.b)) < 0.003) discard;
    // Additive (ONE, ONE): the colour alone
    col *= 1.0 - cloudCoverBefore(gl_FragCoord.xy, vDistance);
    fragColor = vec4(col, 1.0);
}
