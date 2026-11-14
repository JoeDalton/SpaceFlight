#version 140
// Hyperspace "inside" effect — a seamlessly looping warp tunnel, held while the
// level loads or while warping in flight.
// Based on theGiallo's https://www.shadertoy.com/view/MttSz2
// MIT License. Use freely; but attribution is expected.

#pragma include "hyperspace_common.glsl"

uniform float iTunnelOpacity;  // overall opacity of the tunnel, 0..1 (look)

const float speed          = 2.0;  // tunnel scroll speed
const float rotation_speed  = 0.3;  // tunnel swirl speed
// The whole effect repeats every T_LOOP seconds with no visible seam. For a
// perfect loop the scroll and swirl must each advance by a whole number of
// periods over T_LOOP: DEPTH_PERIOD = speed * T_LOOP, and rotation_speed *
// T_LOOP must be an integer (here 0.3 * 10 = 3).
const float T_LOOP       = 10.0;
const float DEPTH_PERIOD = speed * T_LOOP;  // scroll distance covered in one loop
const float CIRCLE_R     = 1.5;             // noise sampling-circle radius (detail)

// --- 3D simplex noise (Ashima Arts / Stefan Gustavson) -----------------------
vec3 mod289v3(vec3 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 mod289v4(vec4 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289v4(((x*34.0)+1.0)*x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v)
{
    const vec2 C = vec2(0.166666666666667, 0.333333333333333);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i  = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289v3(i);
    vec4 p = permute(permute(permute(
        i.z + vec4(0.0,i1.z,i2.z,1.0))
        + i.y + vec4(0.0,i1.y,i2.y,1.0))
        + i.x + vec4(0.0,i1.x,i2.x,1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0)*2.0 + 1.0;
    vec4 s1 = floor(b1)*2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 mm = max(0.6 - vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)), 0.0);
    mm = mm * mm;
    return 42.0 * dot(mm*mm, vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}

// Seamlessly tiling fBm. The angular coordinate runs along x; the depth/scroll
// coordinate is wrapped onto a circle (period TAU) in the y-z plane, so the
// pattern repeats with no discontinuity (a hard mod() wrap would leave a
// visible seam). Each octave traverses the circle an
// integer number of extra times (freq doubles), so every octave is periodic
// too: the whole sum loops seamlessly as depth_phase advances by 1.
float loopFbm(float angle, float depth_phase)
{
    float f = 0.0;
    float amp = 0.75;
    float freq = 1.0;
    for (int i = 0; i < 5; i++) {
        float th = TAU * depth_phase * freq;
        f += snoise(vec3(angle * freq, CIRCLE_R * cos(th), CIRCLE_R * sin(th))) * amp;
        amp *= 0.5;
        freq *= 2.0;
    }
    return min(f, 1.0);
}

void main()
{
    // Loop-local time: the effect is periodic in T_LOOP, so wrapping here keeps
    // the arguments small over long loads without introducing a seam.
    float lt = mod(iTime, T_LOOP);

    vec4 col = vec4(0.0);
    vec3 v = mouse_rotation() * vec3(screen_point(), 1.0);
    float z = v.z / length(v.xy);

    float focal_depth = 0.15;
    // Scrolling depth coordinate; expressed in loop-turns for loopFbm.
    float depth = z * focal_depth + lt * speed;

    float a = atan(v.y, v.x);
    a = 0.5 + 0.5 * a / PI;
    a -= lt * rotation_speed;
    float x = fract(a);
    if (x >= 0.5) x = 1.0 - x;  // reflect to hide the angular seam

    float val = 0.45 + 0.55 * loopFbm(2.0 * x, depth / DEPTH_PERIOD);
    val = clamp(val, 0.0, 1.0);
    col.rgb = vec3(0.15, 0.4, 0.9) * val;
    col.rgb += 0.35 * vec3(smoothstep(0.55, 1.0, val));
    col.rgb = clamp(col.rgb, 0.0, 1.0);

    float p_len = length(v.xy);
    float disk_col = exp(-(p_len - 0.025) * 4.0);
    col.rgb += clamp(vec3(disk_col), 0.0, 1.0);

    p3d_FragColor = overlay_color(col.rgb, iBackgroundOpacity, iTunnelOpacity);
}
