#version 140
// Spark particle vertex shader (hit sparks).
//
// Reconstructs each spark's current state on the GPU from its spawn-time
// parameters (stored once, per vertex, at spawn). No vertex data is touched
// after spawn; only the per-frame uniforms below change.
//
// Unlike the explosion, colour and gravity are carried PER PARTICLE (not as
// uniforms) so bursts of different hit types — metal / ice / magic — can be
// alive simultaneously in one buffer without repainting each other.

in vec3  p3d_Vertex;    // world-space spawn position
in vec2  corner;        // billboard corner selector, one of (±1, ±1)
in vec3  velocity;      // world units / s
in float size;          // billboard half-size (world units)
in float spawn_time;    // absolute buffer-clock value at birth
in float lifetime;      // particle lifetime (seconds)
in float gravity;       // downward acceleration (world units / s²)
in vec4  spark_color;   // premixed RGBA tint for this spark

uniform mat4  p3d_ModelViewProjectionMatrix;
uniform float uTime;      // buffer clock (seconds since buffer creation)
uniform vec3  uCamRight;  // world-space camera right axis (billboard)
uniform vec3  uCamUp;     // world-space camera up    axis (billboard)

out vec2 vCorner;  // [-1,1] corner, forwarded to the fragment shader for the SDF
out vec4 vColor;   // per-spark tint
out float vAlpha;

void main() {
    float t     = uTime - spawn_time;
    float ta    = max(t, 0.0);
    float frac  = clamp(t / max(lifetime, 0.001), 0.0, 1.0);
    float alive = (t >= 0.0 && t < lifetime) ? 1.0 : 0.0;

    // Ballistic trajectory: linear velocity + constant downward gravity.
    vec3 pos = p3d_Vertex + velocity * ta + vec3(0.0, 0.0, -gravity) * 0.5 * ta * ta;

    // Sparks shrink as they age (opposite of fire, which grows).
    float sz = size * (0.3 + 0.7 * (1.0 - frac)) * alive;

    pos += uCamRight * corner.x * sz + uCamUp * corner.y * sz;
    gl_Position = p3d_ModelViewProjectionMatrix * vec4(pos, 1.0);

    vCorner = corner;
    vColor  = spark_color;
    // Quadratic fade-out gives a sharper, more energetic disappearance.
    vAlpha  = (1.0 - frac) * (1.0 - frac) * alive;
}
