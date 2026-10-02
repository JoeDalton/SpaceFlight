#version 140
// Full-screen cockpit damage overlay — fragment shader.
//
// Two contributions (colours added, alpha = max), driven by uniforms from
// fx/cockpit_fx.py:
//
//  * A radial damage VIGNETTE: a uVignetteColor wash growing inward from the
//    screen edges as uVignetteStrength rises (health tiers).
//  * A directional hit FLASH: a uFlashColor bloom biased toward uFlashDir (the
//    screen direction the shot came from) plus a faint full-screen wash so a
//    head-on hit still registers. uFlashStrength jumps to a peak on a hit
//    (_FLASH_PEAK) and decays to 0.
//
// Output is alpha-blended (MAlpha) over the scene.

in vec2 vUV;
out vec4 fragColor;

uniform vec3  uVignetteColor;    // damage tint (red)
uniform float uVignetteStrength; // 0 = intact; pulsing when critical (CPU-side)
uniform vec3  uFlashColor;       // hit tint = the laser's colour
uniform vec2  uFlashDir;         // screen dir the shot came from (x right, y up)
uniform float uFlashStrength;    // 0..peak, decays after a hit

void main() {
    vec2 p = vUV - vec2(0.5);       // centred, y up
    float r = length(p) * 2.0;      // ~0 centre, ~1 mid-edge, >1 corners

    // --- Damage vignette: coloured wash rising from the edges ---
    float edge = smoothstep(0.35, 0.95, r);
    float vig = clamp(uVignetteStrength, 0.0, 2.0) * edge;
    vec3 col = uVignetteColor * vig;
    float alpha = vig;

    // --- Directional hit flash ---
    if (uFlashStrength > 0.0) {
        vec2 dir = normalize(uFlashDir + vec2(1e-5, 0.0));
        // 1 on the side the hit came from, 0 on the opposite side.
        float side = 0.5 + 0.5 * dot(normalize(p + vec2(1e-6, 0.0)), dir);
        float edgeGlow = smoothstep(0.1, 1.0, r);
        // Directional bloom on the hit side + a faint uniform wash.
        float flash = uFlashStrength * (0.25 + 0.75 * side * edgeGlow);
        col += uFlashColor * flash;
        alpha = max(alpha, flash);
    }

    fragColor = vec4(col, clamp(alpha, 0.0, 1.0));
}
