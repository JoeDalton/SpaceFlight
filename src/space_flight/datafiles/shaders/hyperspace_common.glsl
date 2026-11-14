// Shared by the three hyperspace phase shaders (hyperspace_into/inside/outof.frag),
// pulled in with `#pragma include "hyperspace_common.glsl"` right after #version.
//
// The same shaders draw both the loading screen and the in-flight warp; what
// differs is the "look", a handful of uniforms set from Python (see
// HyperspaceLook in fx/hyperspace_overlay.py). With the loading look
// (all opacities and the whiteout at 1) the output is the original opaque
// effect; the warp look makes the black background transparent so the game
// scene shows through.

// --- Panda3D uniforms (replace the ShaderToy built-ins) ---
uniform float iTime;
uniform vec2  iResolution;
uniform vec3  iMouse;         // xy = pos, z = button pressed (>0)
uniform float iAlpha;         // cross-fade opacity, driven from Python
uniform float iCenterOffset;  // tunnel vanishing point above the screen centre
// --- Look uniforms ---
uniform float iBackgroundOpacity;  // opacity of the black background, 0..1
uniform float iMaxWhiteout;        // strength of the white flashes (and the
                                   // into flare's final swell), 0..1
// ----------------------------------------------------------
out vec4 p3d_FragColor;

#define TAU 6.28318
#define PI 3.141592

// Pixel position, centred and scaled so the shorter screen side spans [-1, 1],
// with the vanishing point (p = 0) moved up by iCenterOffset.
vec2 screen_point()
{
    vec2 p = (2.0 * gl_FragCoord.xy - iResolution.xy)
        / min(iResolution.x, iResolution.y);
    return p + vec2(0.0, -iCenterOffset);
}

// View rotation from the mouse (a ShaderToy leftover, kept for tweaking: iMouse
// is (0, 0, 0) in game, which gives the identity).
mat3 mouse_rotation()
{
    vec2 mo = (2.0 * iMouse.xy - iResolution.xy) / min(iResolution.x, iResolution.y);
    float ay = 0.0, ax = 0.0;
    if (iMouse.z > 0.0) {
        ay = 3.0 * mo.x;
        ax = 3.0 * mo.y;
    }
    mat3 mY = mat3(cos(ay),0.0,sin(ay), 0.0,1.0,0.0, -sin(ay),0.0,cos(ay));
    mat3 mX = mat3(1.0,0.0,0.0, 0.0,cos(ax),sin(ax), 0.0,-sin(ax),cos(ax));
    return mX * mY;
}

float rand(vec2 co)
{
    return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453);
}

// Distance from p to the segment [a, b], minus a ring thickness.
float sdLine(in vec2 p, in vec2 a, in vec2 b, in float ring)
{
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
    return length(pa - ba * h) - ring;
}

// Final fragment colour, the same for every phase. The background (black) covers
// the screen with the given opacity; brighter pixels are more opaque, so streaks
// and glows stay visible over the scene even where the background is see-through.
// The colour is divided by its alpha so blending it over the scene gives back
// the intended brightness.
//
// :param color: the effect's colour over black
// :param background: opacity of the black background at this pixel, 0..1
// :param opacity: overall opacity of the effect, 0..1
vec4 overlay_color(vec3 color, float background, float opacity)
{
    float brightness = max(color.r, max(color.g, color.b));
    float a = clamp(max(background, brightness), 0.0, 1.0);
    return vec4(a > 0.0 ? color / a : vec3(0.0), a * opacity * iAlpha);
}
