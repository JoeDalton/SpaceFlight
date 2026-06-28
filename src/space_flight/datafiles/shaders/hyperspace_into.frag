#version 140
// Hyperspace "into" effect — entering hyperspace.
// Simplified and adapted from: https://www.shadertoy.com/view/MlKBWw

// --- Panda3D uniforms (replaces ShaderToy built-ins) ---
uniform float iTime;
uniform vec2  iResolution;
uniform vec3  iMouse;
uniform float iAlpha;         // cross-fade opacity, driven from Python
uniform float iCenterOffset;  // tunnel vanishing-point offset below screen centre
uniform float iIntoDuration;  // animation length (s); == the Python INTO_DURATION
// -------------------------------------------------------
out vec4 p3d_FragColor;

#define FLARE 1
#define TAU 6.28318
#define NUM_SLICES 125.0
const float MAX_SLICE_OFFSET = 0.4;
// Ease-in exponent (>1): time crawls at the start, then accelerates. 1 = linear,
// 2 = strong parabolic ease-in.
const float INTO_EASE = 1.8;
const float T_JUMP = 0.75;
const float jump_speed = 15.0;
const vec3 blue_col  = vec3(0.3, 0.3, 0.5);
const vec3 white_col = vec3(0.85, 0.85, 0.9);
const vec3 flare_col = vec3(0.9, 0.9, 1.4);

float sdLine(in vec2 p, in vec2 a, in vec2 b, in float ring)
{
    vec2 pa = p-a, ba = b-a;
    float h = clamp(dot(pa,ba)/dot(ba,ba), 0.0, 1.0);
    return length(pa - ba*h) - ring;
}

float rand(vec2 co) {
    return fract(sin(dot(co.xy, vec2(12.9898,78.233))) * 43758.5453);
}

vec3 lensflare(vec3 uv, vec3 pos, float flare_size, float ang_offset)
{
    float z = uv.z / length(uv.xy);
    vec2 main = uv.xy - pos.xy;
    float dist = length(main);
    float num_points = 2.71;
    float disk_size = 0.2;
    float inv_size = 1.0 / flare_size;
    float ang = atan(main.y, main.x) + ang_offset;
    float fade = (z < 0.0) ? -z : 1.0;
    float f0 = 1.0/(dist * inv_size + 1.0);
    f0 = f0 + f0*(0.1*sin((sin(ang*2.0+pos.x)*4.0 - cos(ang*3.0+pos.y))*num_points) + disk_size);
    if (z < 0.0)
        return clamp(mix(vec3(f0), vec3(0.0), 0.75*fade), 0.0, 1.0);
    else
        return vec3(f0);
}

vec3 cc(vec3 color, float factor, float factor2)
{
    float w = color.x+color.y+color.z;
    return mix(color, vec3(w)*factor, w*factor2);
}

void main()
{
    vec2 fragCoord = gl_FragCoord.xy;

    vec3 color = vec3(0.0);
    // Clamp (don't wrap): once the flare whites out the screen, t HOLDS at 1 so
    // the white frame stays for the cross-fade into the tunnel, instead of
    // mod() restarting the trails. INTO_EASE eases the pacing in (slow → fast).
    float t = pow(clamp(iTime / iIntoDuration, 0.0, 1.0), INTO_EASE);
    vec2 p = (2.0*fragCoord - iResolution.xy) / min(iResolution.x, iResolution.y);
    vec2 mo = (2.0*iMouse.xy - iResolution.xy) / min(iResolution.x, iResolution.y);
    p += vec2(0.0, -iCenterOffset);

    float ay = 0.0, ax = 0.0;
    if (iMouse.z > 0.0) { ay = 3.0*mo.x; ax = 3.0*mo.y; }
    mat3 mY = mat3(cos(ay),0.0,sin(ay), 0.0,1.0,0.0, -sin(ay),0.0,cos(ay));
    mat3 mX = mat3(1.0,0.0,0.0, 0.0,cos(ax),sin(ax), 0.0,-sin(ax),cos(ax));
    mat3 m = mX * mY;

    float p_len = length(p);
    vec3 v = m * vec3(p, 1.0);

    float fade = clamp(mix(0.1, 1.1, t*2.0), 0.0, 2.0);

    for (float i = 0.0; i < 80.0; i++) {
        vec3 trail_color = vec3(0.0);
        float angle = atan(v.y, v.x) / 3.141592 / 2.0 + 0.13*i;
        float slice = floor(angle * NUM_SLICES);
        float slice_fract = fract(angle * NUM_SLICES);
        float slice_offset = MAX_SLICE_OFFSET * rand(vec2(slice, 4.0+i*25.0)) - (MAX_SLICE_OFFSET/2.0);
        float dist = 10.0 * rand(vec2(slice, 1.0+i*10.0)) - 5.0;
        float z = dist * v.z / length(v.xy);
        float f = sign(dist); if (f == 0.0) f = 1.0;
        float fspeed = f*(0.1*rand(vec2(slice, 1.0+i*10.0)) + i*0.01);
        float fjump_speed = f*jump_speed;
        float trail_start = 10.0*rand(vec2(slice, 0.0+i*10.0)) - 5.0;
        trail_start -= mix(0.0, fjump_speed, smoothstep(T_JUMP, 1.0, t));
        float trail_end = trail_start - t*fspeed;
        float trail_x = smoothstep(trail_start, trail_end, z);
        trail_color = mix(blue_col, white_col, trail_x);
        float h = sdLine(vec2(slice_fract+slice_offset, z),
                         vec2(0.5, trail_start), vec2(0.5, trail_end),
                         mix(0.0, 0.015, t*z));
        float threshold = 0.09;
        h = (h < 0.01) ? 1.0 : 0.85*smoothstep(threshold, 0.0, abs(h));
        trail_color *= fade * h;
        color = max(color, trail_color);
    }


    #ifdef FLARE
        // Add the disk at the center to transition into the hyperspace
        // tunnel
        float flare_size = mix(0.0, 0.1, smoothstep(0.35, T_JUMP + 0.2, t));
        flare_size += mix(0.0, 20.0, smoothstep(T_JUMP + 0.05, 1.0, t));
        vec3 flare = flare_col * lensflare(v, vec3(0.0), flare_size, t);
        color += cc(flare, 0.5, 0.1);
        //color += flare;
        // Whiteout
        color += mix(0.0, 1.0, smoothstep(T_JUMP + 0.1, 1.0, t));
    #else
        // Whiteout
        color += mix(0.0, 1.0, smoothstep(T_JUMP - 0.0, 1.0, t));
    #endif

    p3d_FragColor = vec4(color, iAlpha);
}
