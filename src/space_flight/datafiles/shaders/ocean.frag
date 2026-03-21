#version 140

uniform float     iTime;
uniform vec3      iCameraPos;
uniform vec3      iWaterColor;
uniform sampler2D iReflectionTex;
uniform float     iRippleStrength;
uniform vec2      uReflUVScale;
uniform vec2      iWindDir;       // normalised wind direction in XY, set from Python
uniform float     iWindStrength;  // 0=fully random waves, 1=all waves follow wind

in  vec3 vWorldPos;
in  vec4 vReflCoord;
out vec4 fragColor;

#define DRAG_MULT         0.38
#define WAVE_HEIGHT       10.0
#define WAVE_SCALE        0.5
#define ITERATIONS_NORMAL 36
#define SWELL_SCALE       0.03
#define SWELL_STRENGTH    0.2
#define WARP_SCALE        0.05
#define WARP_STRENGTH     1.0
#define NOISE_SCALE       0.01
#define NOISE_STRENGTH    0.75

// ---------------------------------------------------------------------------
// Noise
// ---------------------------------------------------------------------------
float hash(vec2 p) {
    p = fract(p * vec2(127.1, 311.7));
    p += dot(p, p + 19.19);
    return fract(p.x * p.y);
}

float smoothNoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
        mix(hash(i + vec2(0,0)), hash(i + vec2(1,0)), u.x),
        mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x),
        u.y);
}

float fbmNoise(vec2 p) {
    return smoothNoise(p) * 0.6
         + smoothNoise(p * 2.1 + vec2(5.3, 1.7)) * 0.4;
}

// ---------------------------------------------------------------------------
// Waves
// ---------------------------------------------------------------------------
vec2 wavedx(vec2 position, vec2 direction, float frequency, float timeshift) {
    float x    = dot(direction, position) * frequency + timeshift;
    float wave = exp(sin(x) - 1.0);
    float dx   = wave * cos(x);
    return vec2(wave, -dx);
}

float getwaves(vec2 position, int iterations) {
    float wavePhaseShift = length(position) * 0.1;
    float iter           = 0.0;
    float frequency      = 1.0;
    float timeMultiplier = 2.0;
    float weight         = 1.0;
    float sumOfValues    = 0.0;
    float sumOfWeights   = 0.0;
    for (int i = 0; i < iterations; i++) {
        // Random base direction from iter
        vec2 rndDir = vec2(sin(iter), cos(iter));
        // Bias toward wind direction
        vec2 p = normalize(mix(rndDir, iWindDir, iWindStrength));

        vec2 res = wavedx(position, p, frequency,
                          iTime * timeMultiplier + wavePhaseShift);
        position      += p * res.y * weight * DRAG_MULT;
        sumOfValues   += res.x * weight;
        sumOfWeights  += weight;
        weight         = mix(weight, 0.0, 0.2);
        frequency     *= 1.18;
        timeMultiplier *= 1.07;
        iter           += 1232.399963;
    }
    return sumOfValues / sumOfWeights;
}

vec2 domainWarp(vec2 pos) {
    float wx = getwaves(pos * WARP_SCALE,                   4);
    float wy = getwaves(pos * WARP_SCALE + vec2(3.7, 1.3), 4);
    return vec2(wx, wy) * WARP_STRENGTH;
}

vec3 oceanNormal(vec2 pos, float e, int iterations) {
    vec2  ex = vec2(e, 0.0);
    vec2  sp = pos * WAVE_SCALE;
    vec2  sex = ex * WAVE_SCALE;
    float H  = getwaves(pos,               iterations) * WAVE_HEIGHT;
    vec3  a  = vec3(pos.x, pos.y, H);
    vec3  b  = vec3(pos.x - e, pos.y,     getwaves(sp - sex.xy, iterations) * WAVE_HEIGHT);
    vec3  c  = vec3(pos.x,     pos.y + e, getwaves(sp + sex.yx, iterations) * WAVE_HEIGHT);
    return normalize(cross(a - b, a - c));
}

// ---------------------------------------------------------------------------
// Tonemapping
// ---------------------------------------------------------------------------
vec3 aces_tonemap(vec3 color) {
    mat3 m1 = mat3(
        0.59719, 0.07600, 0.02840,
        0.35458, 0.90834, 0.13383,
        0.04823, 0.01566, 0.83777
    );
    mat3 m2 = mat3(
         1.60475, -0.10208, -0.00327,
        -0.53108,  1.10813, -0.07276,
        -0.07367, -0.00605,  1.07602
    );
    vec3 v = m1 * color;
    vec3 a = v * (v + 0.0245786) - 0.000090537;
    vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081;
    return pow(clamp(m2 * (a / b), 0.0, 1.0), vec3(1.0 / 2.2));
}

// ---------------------------------------------------------------------------
void main() {
    float dist = length(vWorldPos - iCameraPos);

    float e        = max(0.01, dist * 0.005);
    int normalIter = max(2, ITERATIONS_NORMAL - int(dist * 0.08));

    // Domain warp
    vec2 warp      = domainWarp(vWorldPos.xy);
    vec2 warpedPos = vWorldPos.xy + warp;

    // Detail normal
    vec3 N = oceanNormal(warpedPos, e, normalIter);

    // Swell normal
    vec3 Nswell = oceanNormal(vWorldPos.xy * SWELL_SCALE, e * SWELL_SCALE, 8);
    N = normalize(mix(N, Nswell, SWELL_STRENGTH));

    // Large-scale noise mask
    float noise = fbmNoise(vWorldPos.xy * NOISE_SCALE + iTime * 0.002);
    N = normalize(mix(N, vec3(0.0, 0.0, 1.0), noise * NOISE_STRENGTH));

    N = mix(N, vec3(0.0, 0.0, 1.0), 0.8 * min(1.0, sqrt(dist * 0.01) * 1.1));

    vec3 V = normalize(vWorldPos - iCameraPos);

    float NdotV  = max(0.0, dot(N, -V));
    float fresnel = 0.04 + 0.96 * pow(1.0 - NdotV, 5.0);

    vec2 reflUV      = ((vReflCoord.xy / vReflCoord.w) * 0.5 + 0.5) * uReflUVScale;
    vec2 perturbedUV = reflUV + N.xy * iRippleStrength * uReflUVScale;

    vec3 reflected = texture(iReflectionTex, clamp(perturbedUV, 0.0, 1.0)).rgb;
    vec3 scattered = iWaterColor * (1.0 - fresnel);

    vec3 C = fresnel * reflected + scattered;

    fragColor = vec4(aces_tonemap(C * 2.0), 1.0);
}
