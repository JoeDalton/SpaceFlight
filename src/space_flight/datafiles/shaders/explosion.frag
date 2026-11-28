#version 140

// The clouds in front (WorldBuilder's cloud_cover.glsl, on Panda's model
// path): the clouds write no depth, so this, drawn after them, fades itself
// by the cloud between the camera and each fragment.
#pragma include "cloud_cover.glsl"
// Explosion particle fragment shader.
//
// Samples the sprite atlas for this particle's tile and applies the vertex
// alpha. The tile's UV rect arrives as vTileRect (identical at all four
// corners), so no uniform array or dynamic indexing is needed.

uniform sampler2D p3d_Texture0;  // sprite atlas (auto-bound via default TextureStage)

in vec2  vUV;        // [0,1] corner UV within the billboard quad
in vec4  vTileRect;  // atlas tile (u, v, uw, vh) in UV space
in float vAlpha;
in float vDistance;     // combined opacity from the vertex shader

out vec4 fragColor;

void main() {
    // Early discard avoids the texture fetch for fully invisible fragments.
    if (vAlpha <= 0.001) discard;

    // vTileRect.xy = bottom-left UV corner of the tile in the atlas.
    // vTileRect.zw = width / height of the tile in UV space.
    // vUV          = interpolated [0,1] position within the billboard quad.
    vec2 uv  = vTileRect.xy + vUV * vTileRect.zw;
    vec4 tex = texture(p3d_Texture0, uv);

    // Straight alpha (smoke) or alpha-weighted additive (fire): the alpha alone
    float cover = cloudCoverBefore(gl_FragCoord.xy, vDistance);
    fragColor = vec4(tex.rgb, tex.a * vAlpha * (1.0 - cover));
}
