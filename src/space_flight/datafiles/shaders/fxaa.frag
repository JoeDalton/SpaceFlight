#version 140
// FXAA (Fast Approximate Anti-Aliasing), simplified from Timothy Lottes' FXAA3.
// Run as a fullscreen post-process pass on the composited scene texture.
//
// The render target may be padded to a power of two; the usable region is the
// lower-left texScale fraction of the texture. All sampling is done in that
// region: the 0..1 quad UV is scaled by texScale, and rcpFrame is one
// render-pixel expressed in texture-UV space (texScale / renderResolution).

uniform sampler2D sceneTex;
uniform vec2 texScale;   // usable fraction of the (possibly padded) texture
uniform vec2 rcpFrame;   // one render-pixel in texture-UV space
in vec2 texcoord;        // 0..1 across the quad
out vec4 p3d_FragColor;

const float FXAA_SPAN_MAX = 8.0;
const float FXAA_REDUCE_MUL = 1.0 / 8.0;
const float FXAA_REDUCE_MIN = 1.0 / 128.0;
const vec3 LUMA = vec3(0.299, 0.587, 0.114);

void main() {
    vec2 uv = texcoord * texScale;

    vec3 rgbNW = texture(sceneTex, uv + vec2(-1.0, -1.0) * rcpFrame).rgb;
    vec3 rgbNE = texture(sceneTex, uv + vec2( 1.0, -1.0) * rcpFrame).rgb;
    vec3 rgbSW = texture(sceneTex, uv + vec2(-1.0,  1.0) * rcpFrame).rgb;
    vec3 rgbSE = texture(sceneTex, uv + vec2( 1.0,  1.0) * rcpFrame).rgb;
    vec3 rgbM  = texture(sceneTex, uv).rgb;

    float lumaNW = dot(rgbNW, LUMA);
    float lumaNE = dot(rgbNE, LUMA);
    float lumaSW = dot(rgbSW, LUMA);
    float lumaSE = dot(rgbSE, LUMA);
    float lumaM  = dot(rgbM,  LUMA);

    float lumaMin = min(lumaM, min(min(lumaNW, lumaNE), min(lumaSW, lumaSE)));
    float lumaMax = max(lumaM, max(max(lumaNW, lumaNE), max(lumaSW, lumaSE)));

    vec2 dir;
    dir.x = -((lumaNW + lumaNE) - (lumaSW + lumaSE));
    dir.y =  ((lumaNW + lumaSW) - (lumaNE + lumaSE));

    float dirReduce = max((lumaNW + lumaNE + lumaSW + lumaSE) * 0.25 * FXAA_REDUCE_MUL,
                          FXAA_REDUCE_MIN);
    float rcpDirMin = 1.0 / (min(abs(dir.x), abs(dir.y)) + dirReduce);
    dir = clamp(dir * rcpDirMin, vec2(-FXAA_SPAN_MAX), vec2(FXAA_SPAN_MAX)) * rcpFrame;

    vec3 rgbA = 0.5 * (
        texture(sceneTex, uv + dir * (1.0 / 3.0 - 0.5)).rgb +
        texture(sceneTex, uv + dir * (2.0 / 3.0 - 0.5)).rgb);
    vec3 rgbB = rgbA * 0.5 + 0.25 * (
        texture(sceneTex, uv + dir * -0.5).rgb +
        texture(sceneTex, uv + dir *  0.5).rgb);

    float lumaB = dot(rgbB, LUMA);
    if (lumaB < lumaMin || lumaB > lumaMax)
        p3d_FragColor = vec4(rgbA, 1.0);
    else
        p3d_FragColor = vec4(rgbB, 1.0);
}
