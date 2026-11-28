#version 140

// The clouds in front (WorldBuilder's cloud_cover.glsl, on Panda's model
// path): the clouds write no depth, so this, drawn after them, fades itself
// by the cloud between the camera and each fragment.
#pragma include "cloud_cover.glsl"
// Speed dust: the mote's sprite, under the dust's colour scale (its opacity
// grows with speed, fx/speed_dust_cloud.py).

uniform sampler2D p3d_Texture0;
uniform vec4 p3d_ColorScale;

in vec2 vUV;
in float vDistance;
out vec4 p3d_FragColor;

void main() {
    p3d_FragColor = texture(p3d_Texture0, vUV) * p3d_ColorScale;
    p3d_FragColor.a *= 1.0 - cloudCoverBefore(gl_FragCoord.xy, vDistance);
}
