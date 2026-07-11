#version 140
// Explosion particle fragment shader.
//
// Samples the sprite atlas for this particle's tile and applies the alpha
// computed by the vertex shader. The tile's UV rect arrives per-particle as
// the interpolated varying vTileRect (identical across the quad's corners),
// so no uniform array or dynamic indexing is needed to pick the sprite.

uniform sampler2D p3d_Texture0;  // sprite atlas (auto-bound via default TextureStage)

in vec2  vUV;        // [0,1] corner UV within the billboard quad
in vec4  vTileRect;  // atlas tile (u, v, uw, vh) in UV space
in float vAlpha;     // combined opacity from the vertex shader

out vec4 fragColor;

void main() {
    // Early discard avoids the texture fetch for fully invisible fragments.
    if (vAlpha <= 0.001) discard;

    // vTileRect.xy = bottom-left UV corner of the tile in the atlas.
    // vTileRect.zw = width / height of the tile in UV space.
    // vUV          = interpolated [0,1] position within the billboard quad.
    vec2 uv  = vTileRect.xy + vUV * vTileRect.zw;
    vec4 tex = texture(p3d_Texture0, uv);

    fragColor = vec4(tex.rgb, tex.a * vAlpha);
}
