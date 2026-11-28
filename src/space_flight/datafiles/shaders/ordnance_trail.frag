#version 140

// The clouds in front (WorldBuilder's cloud_cover.glsl, on Panda's model
// path): the clouds write no depth, so this, drawn after them, fades itself
// by the cloud between the camera and each fragment.
#pragma include "cloud_cover.glsl"
// Ordnance engine trail: the ordnance's colour, shaded as a glowing cylinder
// seen across its width. The glow across the ribbon follows the thickness a
// view ray crosses in a cylinder, sqrt(1 - side^2); where it is thick and the
// trail still bright, a hot core turns the colour toward white. The core dies
// faster along the trail than the glow does. Additive, faded with the point's
// age (vAlpha).

uniform vec3  uColor;
uniform float uBrightness;     // the head's brightness: vAlpha's peak
uniform float uCylinderPower;  // 1 = a plain cylinder, more = a sharper glow
uniform float uCoreStart;      // thickness (0..1) from which the core shows
uniform float uCoreWhiteMix;   // how white the core gets
uniform float uCoreFadePower;  // how fast the core dies along the trail

in float vSide;
in float vAlpha;
in float vDistance;
out vec4 fragColor;

void main() {
    // Thickness of the cylinder across the ribbon: 1 on its axis, 0 at its edges
    float thickness = sqrt(max(1.0 - vSide * vSide, 0.0));
    float glow = pow(thickness, uCylinderPower);
    // The core: where thick and bright
    float remaining = clamp(vAlpha / max(uBrightness, 1e-4), 0.0, 1.0);
    float core = smoothstep(uCoreStart, 1.0, thickness) * pow(remaining, uCoreFadePower);
    vec3 col = mix(uColor, vec3(1.0), core * uCoreWhiteMix) * (vAlpha * glow);
    if (max(col.r, max(col.g, col.b)) < 0.003) discard;
    // Additive (ONE, ONE): the colour alone
    col *= 1.0 - cloudCoverBefore(gl_FragCoord.xy, vDistance);
    fragColor = vec4(col, 1.0);
}
