#version 140
// Full-screen cockpit damage overlay — passthrough vertex shader.
//
// Drawn on a render2d CardMaker fullscreen quad, so p3d_Vertex already spans
// the screen; we only forward the [0,1] UV (v up) to the fragment shader.
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 vUV;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    vUV = p3d_MultiTexCoord0;
}
