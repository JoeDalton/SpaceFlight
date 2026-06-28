#version 140
// Plain scene-composite blit: copy the (possibly downscaled) render target to
// the window, letting the GPU upscale. Used when FXAA is off.
//
// The render target may be padded to a power of two; the usable region is the
// lower-left texScale fraction of the texture, so the 0..1 quad UVs are scaled
// by texScale before sampling.

uniform sampler2D sceneTex;
uniform vec2 texScale;
in vec2 texcoord;
out vec4 p3d_FragColor;

void main() {
    p3d_FragColor = vec4(texture(sceneTex, texcoord * texScale).rgb, 1.0);
}
