#version 140
// Full-screen cockpit damage overlay — passthrough vertex shader: the render2d
// fullscreen quad already spans the screen; forward its [0,1] UV (v up).
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 vUV;
void main() {
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
    vUV = p3d_MultiTexCoord0;
}
