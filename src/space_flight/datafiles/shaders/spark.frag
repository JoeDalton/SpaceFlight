#version 140
// Spark particle fragment shader (hit sparks).
//
// Renders each billboard quad as a round, glowing spark: an SDF circle discards
// the quad's corners, a soft glow + hard core builds the shape, and the
// per-spark tint (vColor, premixed CPU-side) colours it. An optional texture
// (spark.png) adds detail via its red channel; the shape floors to the
// procedural glow so it still reads if the texture is flat.

uniform sampler2D p3d_Texture0;  // spark sprite (auto-bound via default TextureStage)

in vec2  vCorner;  // [-1,1] position within the billboard quad
in vec4  vColor;   // per-spark tint
in float vAlpha;   // combined opacity from the vertex shader

out vec4 fragColor;

void main() {
    // SDF circle: discard fragments outside the inscribed unit circle so the
    // quad renders as a round spark rather than a rectangle.
    float d = dot(vCorner, vCorner);
    if (d > 1.0) discard;
    if (vAlpha <= 0.0) discard;

    vec2 uv  = vCorner * 0.5 + 0.5;
    vec4 tex = texture(p3d_Texture0, uv);

    // Soft glow around the perimeter + bright hard core at the centre.
    float glow  = 1.0 - smoothstep(0.0, 1.0, d);
    float core  = 1.0 - smoothstep(0.0, 0.15, d);
    float shape = clamp(max(tex.r * tex.a, glow + core * 0.8), 0.0, 1.0);

    fragColor = vec4(vColor.rgb * shape, vAlpha * shape);
}
