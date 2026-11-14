#version 140
// Hyperspace "outof" effect — dropping out of hyperspace into the scene.
// Simplified and adapted from: https://www.shadertoy.com/view/MlKBWw

#pragma include "hyperspace_common.glsl"

#define NUM_SLICES 125.0
const float MAX_SLICE_OFFSET = 0.4;
const float T_MAX = 2.0;
const float T_JUMP = 0.90;
const float jump_speed = 5.0;
const vec3 blue_col  = vec3(0.3, 0.3, 0.6);
const vec3 white_col = vec3(0.8, 0.8, 0.95);

void main()
{
    vec3 color = vec3(0.0);
    float time = mod(iTime, T_MAX);
    float t = time / T_MAX;
    vec3 v = mouse_rotation() * vec3(screen_point(), 1.0);

    float fade = mix(1.4, 0.0, smoothstep(0.65, 0.95, t));

    float trail_start, trail_end, trail_length = 1.0, trail_x;

    for (float i = 0.0; i < 60.0; i++) {
        vec3 trail_color = vec3(0.0);
        float angle = atan(v.y, v.x) / 3.141592 / 2.0 + 0.13*i;
        float slice = floor(angle * NUM_SLICES);
        float slice_fract = fract(angle * NUM_SLICES);
        float slice_offset = MAX_SLICE_OFFSET * rand(vec2(slice, 4.0+i*25.0)) - (MAX_SLICE_OFFSET/2.0);
        float dist = 10.0 * rand(vec2(slice, 1.0+i*2.0)) - 5.0;
        float z = dist * v.z / length(v.xy);
        float f = sign(dist); if (f == 0.0) f = 1.0;
        float fspeed = f*(rand(vec2(slice, 1.0+i*0.1)) + i*0.01);
        float fjump_speed = f*jump_speed;
        float ftrail_length = f*trail_length;

        trail_end = 10.0*rand(vec2(slice, i+10.0)) - 5.0;
        trail_end -= t * fspeed;
        trail_start = trail_end + ftrail_length;
        if (f >= 0.0) {
            trail_start = max(trail_end,
                trail_start - t*fspeed - mix(0.0, fjump_speed, smoothstep(0.5, 1.0, t)));
        } else {
            trail_start = min(trail_end,
                trail_start - t*fspeed - mix(0.0, fjump_speed, smoothstep(0.5, 1.0, t)));
        }
        trail_x = smoothstep(trail_start, trail_end, z);
        trail_color = mix(blue_col, white_col, trail_x);

        float h = sdLine(vec2(slice_fract+slice_offset, z),
                         vec2(0.5, trail_start), vec2(0.5, trail_end),
                         mix(0.0, 0.015, z));
        float threshold = mix(0.12, 0.0, smoothstep(0.5, 0.8, t));
        h = (h < 0.01) ? 1.0 : 0.75*smoothstep(threshold, 0.0, abs(h));
        trail_color *= fade * h;
        color = max(color, trail_color);
    }

    // Whiteout (fade from white at start)
    color += iMaxWhiteout * (1.0 - smoothstep(0.0, 0.2, t));

    // The black background dissolves into the scene behind the overlay while
    // the streaks keep their brightness (see overlay_color).
    // The 0.35 start must match REVEAL_START / T_MAX in
    // hyperspace_loading_state.py, which starts the simulation at that moment.
    float bg = iBackgroundOpacity * (1.0 - smoothstep(0.35, 0.9, t));
    p3d_FragColor = overlay_color(color, bg, 1.0);
}
