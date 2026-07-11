#version 140
// Explosion particle vertex shader.
//
// Reconstructs each billboard particle's current state on the GPU from its
// spawn-time parameters (stored once, per vertex, at spawn). No vertex data
// is touched after spawn; only the per-frame uniforms below change.
//
// Every per-particle value arrives in its own named vertex column (see
// fx/__init__.py's vertex-layout table) — no bit-packing to unpack here.

in vec3  p3d_Vertex;   // world-space spawn position
in vec2  corner;       // billboard corner selector, one of (±1, ±1)
in vec3  velocity;     // world units / s
in float size;         // billboard half-size (world units)
in float spin;         // rotation rate (radians/s; negative = CCW)
in float spawn_time;   // absolute buffer-clock value at birth
in float lifetime;     // particle lifetime (seconds)
in vec4  tile_rect;    // atlas tile (u, v, uw, vh) in UV space

uniform mat4  p3d_ModelViewProjectionMatrix;
uniform float uTime;      // buffer clock (seconds since buffer creation)
uniform vec3  uCamRight;  // world-space camera right axis (billboard)
uniform vec3  uCamUp;     // world-space camera up    axis (billboard)
uniform float uFadein;    // fraction of lifetime over which alpha ramps 0 → 1

out vec2  vUV;       // [0,1] corner UV within the billboard quad
out vec4  vTileRect; // atlas rect, forwarded to the fragment shader
out float vAlpha;    // combined fade-out * fade-in * alive gate

void main() {
    // --- Particle age ---
    // t < 0 during the spawn_delay window → particle is not yet born.
    float t = uTime - spawn_time;
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;
    float frac  = clamp(t / max(lifetime, 0.001), 0.0, 1.0);

    // --- Fade-in ramp ---
    // Alpha rises linearly from 0 to 1 over the first uFadein fraction of life.
    float fade_in = (uFadein > 0.0) ? clamp(frac / uFadein, 0.0, 1.0) : 1.0;

    // --- World-space centre position (linear motion, no gravity) ---
    // max(t, 0) prevents the particle from moving backwards during the delay.
    vec3 pos = p3d_Vertex + velocity * max(t, 0.0);

    // --- Billboard size (grows from 30% to 100% over life, zeroed when dead) ---
    float sz = (size * (0.3 + frac * 0.7)) * alive;

    // --- Spin: rotate corner around the quad centre ---
    float angle = spin * max(t, 0.0);
    float cs = cos(angle), sn = sin(angle);
    vec2 rot = vec2(cs * corner.x - sn * corner.y,
                    sn * corner.x + cs * corner.y);

    // --- Billboard: project the rotated corner onto the camera axes ---
    pos += uCamRight * rot.x * sz + uCamUp * rot.y * sz;

    gl_Position = p3d_ModelViewProjectionMatrix * vec4(pos, 1.0);

    // Remap corner [-1,1] → [0,1] for UV interpolation in the fragment shader.
    vUV       = corner * 0.5 + 0.5;
    vTileRect = tile_rect;
    vAlpha    = (1.0 - frac) * fade_in * alive;
}
