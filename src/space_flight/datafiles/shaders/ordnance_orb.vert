#version 140
// Ordnance orb (fx/ordnance_orb.py): a card facing the eye, centred on the
// ordnance's node and expanded in view space, so it faces whatever camera draws
// the pass (main view, rear-view mirror, reflection) without any uniform.

in vec4 p3d_Vertex;  // CardMaker corner in the X-Z plane: (x, 0, z), in [-1, 1]

uniform mat4  p3d_ModelViewMatrix;
uniform mat4  p3d_ProjectionMatrix;
uniform float uHalfSize;  // the card's half-size, metres

out vec2  vCorner;    // [-1, 1] across the card
out float vDistance;  // from the camera to the card's centre, metres

void main() {
    vec4 centre = p3d_ModelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
    vCorner = p3d_Vertex.xz;
    vDistance = length(centre.xyz);
    centre.xy += p3d_Vertex.xz * uHalfSize;
    gl_Position = p3d_ProjectionMatrix * centre;
}
