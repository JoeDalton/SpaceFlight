#version 140
// Laser bolt vertex shader: a camera-facing billboard for the capsule-impostor
// fragment shader (laser.frag).
//
// Everything is computed in the projectile node's MODEL space. The node is NOT
// at the origin: the Munition base translates it every frame (LerpPosInterval)
// and orients it so its local +Z axis runs along the bolt's travel direction
// (that same local Z is where the swept collision segment lives). The bolt core
// is therefore the fixed model-space segment [uA, uB] along local Z.
//
// The card is billboarded to face WHATEVER camera is drawing the current pass
// (main view, rear-view mirror, ocean reflection, ...). We read that camera's
// world position from p3d_ViewMatrixInverse and face the quad at it, so the bolt
// is correct in every pass with no per-frame CPU work and no shared uniforms.
// Model <-> world is a plain Z-up rotation here, so (unlike Projection * View)
// there is no hidden coordinate-system conversion to trip over.

uniform mat4 p3d_ModelViewProjectionMatrix;   // model -> clip (composed; correct)
uniform mat4 p3d_ModelMatrixInverse;          // world -> model
uniform mat4 p3d_ViewMatrixInverse;           // view  -> world (column 3 = eye)

uniform vec3  uA;          // core segment start, model space
uniform vec3  uB;          // core segment end,   model space
uniform float uGlowRadius; // halo radius (model units)

in vec4 p3d_Vertex;        // CardMaker corner in the X-Z plane: (x, 0, z)

out vec3 vModelPos;        // this fragment's position on the card (model space)

void main() {
    // Eye position of the current pass's camera, in model space. Column 3 of the
    // inverse view matrix is the camera's world position -- unambiguous in any
    // coordinate convention (unlike the basis columns), so nothing here depends
    // on Panda's view-space axis convention.
    vec3 eye = (p3d_ModelMatrixInverse * p3d_ViewMatrixInverse[3]).xyz;

    vec3 mid = 0.5 * (uA + uB);
    // Square half-size guaranteed to contain the whole segment plus its halo at
    // any viewing angle: the projected segment is never longer than the segment.
    float halfSize = 0.5 * length(uB - uA) + 3.0 * uGlowRadius;

    // Build a square that faces the eye (its plane perpendicular to the eye->bolt
    // ray). The in-plane roll is irrelevant: the capsule is computed analytically
    // in the fragment shader, so the quad is only a canvas that must (a) face the
    // camera and (b) be big enough to contain the bolt's projection.
    vec3 toEye = eye - mid;
    float dist = length(toEye);
    vec3 view = (dist > 1e-5) ? toEye / dist : vec3(0.0, 1.0, 0.0);
    vec3 helper = (abs(view.z) < 0.99) ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 right = normalize(cross(helper, view));
    vec3 up = cross(view, right);

    // CardMaker lays the quad in the X-Z plane, so the corner coordinates are
    // p3d_Vertex.x and p3d_Vertex.z (.y is always 0 -- using it would collapse
    // the quad to a zero-area line and nothing would rasterize).
    vec3 modelPos = mid + p3d_Vertex.x * halfSize * right
                        + p3d_Vertex.z * halfSize * up;

    vModelPos = modelPos;
    gl_Position = p3d_ModelViewProjectionMatrix * vec4(modelPos, 1.0);
}
