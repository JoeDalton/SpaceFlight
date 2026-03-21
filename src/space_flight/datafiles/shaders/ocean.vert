#version 140

in vec4 p3d_Vertex;

uniform mat4 p3d_ModelViewProjectionMatrix;
uniform mat4 p3d_ModelMatrix;
uniform mat4 uReflMVP;

out vec3 vWorldPos;
out vec4 vReflCoord;

void main() {
    vec4 wp    = p3d_ModelMatrix * p3d_Vertex;
    vWorldPos  = wp.xyz;
    vReflCoord = uReflMVP * wp;
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
