#version 140
// Speed dust: the mote's sprite, under the dust's colour scale (its opacity
// grows with speed, fx/speed_dust_cloud.py).

uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;

in vec2 vUV;
out vec4 p3d_FragColor;

void main() {
    p3d_FragColor = texture(p3d_Texture0, vUV) * p3d_ColorScale;
}
