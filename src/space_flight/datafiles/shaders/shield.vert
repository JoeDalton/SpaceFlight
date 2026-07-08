#version 140
// Shield bubble vertex shader (v2 — identical to v1).
// Passes to the fragment shader:
//   - object-space position/normal: a stable domain for the surface field and
//     the death "retraction" (both are anchored to the hull, so they stay put
//     as the ship rotates).
//   - world position/normal: used for the view-dependent fresnel rim glow.

in vec4 p3d_Vertex;
in vec3 p3d_Normal;

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;

out vec3 vObjPos;
out vec3 vObjNormal;
out vec3 vWorldPos;
out vec3 vWorldNormal;

void main() {
    vObjPos    = p3d_Vertex.xyz;
    vObjNormal = normalize(p3d_Normal);

    vec4 wp      = p3d_ModelMatrix * p3d_Vertex;
    vWorldPos    = wp.xyz;
    // Uniform-scale assumption (a shield bubble is scaled uniformly), so the
    // upper 3x3 of the model matrix suffices to carry the normal to world space.
    vWorldNormal = normalize(mat3(p3d_ModelMatrix) * p3d_Normal);

    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
