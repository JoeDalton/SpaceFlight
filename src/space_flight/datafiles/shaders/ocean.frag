#version 140

uniform float     iTime;
uniform vec3      iCameraPos;
uniform vec3      iWaterColor;
uniform sampler2D iReflectionTex;
uniform float     iRippleStrength;
uniform vec2      uReflUVScale;
uniform mat4      uReflMVP;       // reflection view-projection (used per-fragment)
uniform vec2      iWindDir;       // normalised wind direction in XY, set from Python
uniform float     iWindStrength;  // 0=fully random waves, 1=all waves follow wind
uniform int       iIterationsNormal;  // wave-detail iterations (quality knob, set from Python)
// Swell spatial frequency and scroll speed — set from Python so the vertex and
// fragment shaders share one source of truth (the wavelength is load-bearing:
// the geometric-swell mesh must sample it without aliasing).
uniform float     iSwellScale;
uniform float     iSwellDrift;
// Frequency-modulation depth (radians). The low-frequency swell field is added
// to the small-wave phase, so the wave field drifts over the swell's scale and
// the exact tiling of the dominant (lowest-frequency) octave is broken up. 0
// disables FM.
uniform float     uFmDepth;
uniform int       uDebugMode;  // 0 normal, 1 N, 2 reflUV, 3 fresnel, 4 worldgrid
uniform int       uWaveOff;    // debug: 1 = skip small-wave normal, swell only
uniform float     uExposure;   // pre-tonemap exposure
uniform float     uWaveFadeNear;  // distance at which small-wave detail is still full
uniform float     uWaveFadeFar;   // distance beyond which small waves are fully suppressed
uniform float     uWaveFadeK2;    // exponential decay rate for iteration count: iter = iIterationsNormal * exp(-k2 * dist)

// Per-iteration wave directions, precomputed on the CPU.  They depend only on
// the iteration index and the wind (not on the pixel), so computing them here
// would repeat the same sin/cos/normalize/mix for every pixel every iteration.
#define MAX_WAVE_ITER 64
uniform vec2      iWaveDirs[MAX_WAVE_ITER];

in  vec3 vWorldPos;
out vec4 fragColor;

#define DRAG_MULT         0.38
#define WAVE_HEIGHT       10.0
#define WAVE_SCALE        0.5
#define SWELL_STRENGTH    0.5    // how strongly the swell tilts the normal (frag-only)
#define WARP_SCALE        0.05
#define WARP_STRENGTH     1.0
#define NOISE_SCALE       0.01
#define NOISE_STRENGTH    0.75

// Angle-based detail falloff (sine of the view-ray elevation angle).
// Below GRAZE_HI the surface fades to a flat near-mirror; full detail above it.
// Keyed on angle (not distance) so the look is consistent across altitude.
#define GRAZE_LO          0.0
#define GRAZE_HI          0.12
#define ITERATIONS_MIN    2

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

// Large-scale swell field: the product of two value-noise layers drifting in
// different directions (and at different scales/speeds).  The product makes the
// pattern interfere and continuously change shape over time instead of rigidly
// scrolling, so the swell never looks like one fixed shape sliding past.
float swellField(vec2 w) {
    vec2 d1 = iWindDir;
    vec2 d2 = vec2(-iWindDir.y, iWindDir.x);  // perpendicular to the wind
    vec2 a = w * iSwellScale        + iTime * iSwellDrift        * d1;
    vec2 b = w * iSwellScale * 1.7  + iTime * iSwellDrift * 0.6  * d2;
    return fbmNoise(a) * fbmNoise(b);
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
    float frequency      = 1.0;
    float timeMultiplier = 2.0;
    float weight         = 1.0;
    float sumOfValues    = 0.0;
    float sumOfWeights   = 0.0;
    for (int i = 0; i < iterations && i < MAX_WAVE_ITER; i++) {
        vec2 p = iWaveDirs[i];  // precomputed (wind-biased) direction

        vec2 res = wavedx(position, p, frequency,
                          iTime * timeMultiplier + wavePhaseShift);
        position      += p * res.y * weight * DRAG_MULT;
        sumOfValues   += res.x * weight;
        sumOfWeights  += weight;
        weight         = mix(weight, 0.0, 0.2);
        frequency     *= 1.18;
        timeMultiplier *= 1.07;
    }
    return sumOfValues / sumOfWeights;
}

vec2 domainWarp(vec2 pos, int iterations, float strength) {
    float wx = getwaves(pos * WARP_SCALE,                   iterations);
    float wy = getwaves(pos * WARP_SCALE + vec2(3.7, 1.3), iterations);
    return vec2(wx, wy) * strength;
}

// Analytic wave-height gradient (∂H/∂x, ∂H/∂y) accumulated in a SINGLE pass.
// Each wave term is wave = exp(sin(x) - 1) with x = freq * dot(p, pos) + t, so
// its slope is d(wave)/dpos = wave * cos(x) * freq * p — known in closed form.
// This replaces the old 3x getwaves finite-difference normal with one pass and
// no height accumulation (the surface is a flat plane; only the slope matters).
// Approximation: the loop advects `position` to sharpen crests, and we keep
// that advection so the field matches getwaves(), but we don't differentiate
// through it — the standard, visually-faithful real-time simplification.
//
// fmPhase is the swell-driven frequency-modulation phase (constant per fragment,
// varying slowly across the surface). Added to every octave's phase, it shifts
// each octave's crests — most in world units for the longest-wavelength octave —
// so the dominant tiling drifts with the swell. It is treated as locally
// constant for the gradient (same simplification already applied to
// wavePhaseShift and the advection); the swell is low-frequency, so its spatial
// derivative is negligible next to freq*p and omitting it keeps the normal stable.
vec2 waveGradient(vec2 position, int iterations, float fmPhase) {
    float wavePhaseShift = length(position) * 0.1;
    float frequency      = 1.0;
    float timeMultiplier = 2.0;
    float weight         = 1.0;
    vec2  sumGrad        = vec2(0.0);
    float sumOfWeights   = 0.0;
    for (int i = 0; i < iterations && i < MAX_WAVE_ITER; i++) {
        vec2  p     = iWaveDirs[i];
        float x     = dot(p, position) * frequency + iTime * timeMultiplier + wavePhaseShift + fmPhase;
        float wave  = exp(sin(x) - 1.0);
        float dwave = wave * cos(x);  // d(wave)/dx
        sumGrad      += dwave * frequency * p * weight;
        position     += p * (-dwave) * weight * DRAG_MULT;  // same advection as getwaves
        sumOfWeights += weight;
        weight         = mix(weight, 0.0, 0.2);
        frequency     *= 1.18;
        timeMultiplier *= 1.07;
    }
    return sumGrad / sumOfWeights;
}

vec3 oceanNormal(vec2 pos, int iterations, float fmPhase) {
    // Slope of the height field (scaled by WAVE_HEIGHT) → surface normal.
    vec2 g = waveGradient(pos, iterations, fmPhase) * WAVE_HEIGHT;
    return normalize(vec3(-g.x, -g.y, 1.0));
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
    vec3  V    = normalize(vWorldPos - iCameraPos);

    // Angle-based detail (sine of the view-ray elevation angle): 1 looking
    // straight down, 0 at the horizon.  Drives both the look (normal flatten +
    // ripple) and the per-pixel loop counts, so it stays consistent across
    // altitude with no distance-dependent seam.
    float detailAngle = smoothstep(GRAZE_LO, GRAZE_HI, abs(V.z));
    // Distance fade: 1.0 close up, 0.0 beyond uWaveFadeFar.  Independent of
    // angle so high-altitude straight-down views still lose detail at distance.
    float distFade    = 1.0 - smoothstep(uWaveFadeNear, uWaveFadeFar, dist);
    // Combined LOD factor drives iteration counts and warp strength.
    float lodFactor   = detailAngle * distFade;

    // --- Swell field (sampled once; drives both the small-wave frequency
    //     modulation below and the swell normal-tilt further down) -----------
    float epsW  = 0.5 / iSwellScale;  // world step ≈ 0.5 in primary noise space
    float s0    = swellField(vWorldPos.xy);
    vec2  sgrad = vec2(swellField(vWorldPos.xy + vec2(epsW, 0.0)) - s0,
                       swellField(vWorldPos.xy + vec2(0.0, epsW)) - s0) / 0.5;
    // FM phase for the small waves: the swell recentred (so the phase wanders
    // both ways rather than only advancing) and scaled by the depth knob. World-
    // anchored, view-independent — so crests stay put as the camera moves.
    float fmPhase = uFmDepth * (s0 - 0.1);

    // --- Small waves (faded by both angle and distance) ----------------------
    vec3 N;
    if (detailAngle < 0.01) {
        // Grazing/horizon: waves are sub-pixel — skip them, flat mirror.
        N = vec3(0.0, 0.0, 1.0);
    } else {
        // Exponential decay: aggressive early drop but waves survive to large distances.
        // Tune uWaveFadeK2 (Python: wave_fade_k2): larger = faster decay.
        // At k2=0.001: 36→22 at 500u, →13 at 1000u, →5 at 2000u, →2 at 3000u.
        int   normalIter = max(ITERATIONS_MIN, int(float(iIterationsNormal) * exp(-uWaveFadeK2 * dist)));
        int   warpIter   = int(mix(1.0, 4.0, lodFactor));

        if (uWaveOff == 1) {
            // Debug: no small waves, start flat and let the swell gradient tilt it.
            N = vec3(0.0, 0.0, 1.0);
        } else {
            // Domain warp (iterations and strength fade with LOD)
            vec2 warp      = domainWarp(vWorldPos.xy, warpIter, WARP_STRENGTH * lodFactor);
            vec2 warpedPos = vWorldPos.xy + warp;

            // Detail normal (WAVE_SCALE sets the wave size, applied at the call site)
            N = oceanNormal(warpedPos * WAVE_SCALE, normalIter, fmPhase);
        }

        // Flatten small-wave normal toward vertical at grazing angles.
        N = normalize(mix(vec3(0.0, 0.0, 1.0), N, detailAngle));
        // Strength fade by distance — applies before swell so it does not affect swell normals.
        N = normalize(mix(vec3(0.0, 0.0, 1.0), N, distFade));
    }

    // --- Swell tilt (unconditional — large wavelength, no distance fading) ---
    N = normalize(N - vec3(sgrad * SWELL_STRENGTH, 0.0));

    // Large-scale noise mask (unconditional)
    float noise = fbmNoise(vWorldPos.xy * NOISE_SCALE + iTime * 0.002);
    N = normalize(mix(N, vec3(0.0, 0.0, 1.0), noise * NOISE_STRENGTH));

    // Final angle flatten on the fully combined normal — keeps horizon a flat mirror.
    N = normalize(mix(vec3(0.0, 0.0, 1.0), N, detailAngle));

    float NdotV  = max(0.0, dot(N, -V));
    float fresnel = 0.04 + 0.96 * pow(1.0 - NdotV, 5.0);

    // Reflection coordinate computed per-fragment from the flat surface
    // position (z=0).  Doing the projective divide here — rather than
    // interpolating a clip-space coord from the vertices — keeps it consistent
    // when the geometry is displaced (the vertex clip-w would otherwise skew
    // the divide per cell, sampling the wrong reflection texel).
    vec4 rc          = uReflMVP * vec4(vWorldPos.xy, 0.0, 1.0);
    vec2 reflUV      = ((rc.xy / rc.w) * 0.5 + 0.5) * uReflUVScale;
    // Ripple perturbation fades with detail so grazing pixels sample the
    // undistorted (near-mirror) reflection instead of clamped edge texels.
    vec2 perturbedUV = reflUV + N.xy * iRippleStrength * detailAngle * uReflUVScale;

    // Clamp to the rendered region [0, uReflUVScale] — beyond it is the
    // texture's power-of-two padding (clear colour), so the ripple must never
    // push the sample out there or it picks up bright/garbage edge texels.
    vec3 reflected = texture(iReflectionTex, clamp(perturbedUV, vec2(0.0), uReflUVScale)).rgb;
    vec3 scattered = iWaterColor * (1.0 - fresnel);

    vec3 C = fresnel * reflected + scattered;

    if (uDebugMode == 1) {        // surface normal (xy encoded)
        fragColor = vec4(0.5 + 0.5 * N.x, 0.5 + 0.5 * N.y, N.z, 1.0); return;
    } else if (uDebugMode == 2) { // reflection UV
        fragColor = vec4(reflUV / uReflUVScale, 0.0, 1.0); return;
    } else if (uDebugMode == 3) { // fresnel
        fragColor = vec4(vec3(fresnel), 1.0); return;
    } else if (uDebugMode == 4) { // world-position grid (continuity check)
        vec2 g = fract(vWorldPos.xy / 31.25);
        fragColor = vec4(g, 0.0, 1.0); return;
    } else if (uDebugMode == 5) { // reflUV clamp indicator (red = clamped)
        vec2 cl = clamp(perturbedUV, vec2(0.0), uReflUVScale);
        bool clamped = (cl != perturbedUV);
        fragColor = vec4(clamped ? 1.0 : 0.0, reflected.g, 0.0, 1.0); return;
    } else if (uDebugMode == 6) { // raw reflected colour (pre fresnel/tonemap)
        fragColor = vec4(reflected, 1.0); return;
    } else if (uDebugMode == 7) { // pre-tonemap C*2 > 1 saturation (red=clipped chan)
        vec3 lin = C * 2.0;
        fragColor = vec4(step(1.0, lin.r), step(1.0, lin.g), step(1.0, lin.b), 1.0); return;
    } else if (uDebugMode == 8) { // FM phase field (swell-driven), wrapped to [0,1]
        fragColor = vec4(vec3(0.5 + 0.5 * sin(fmPhase)), 1.0); return;
    }

    fragColor = vec4(aces_tonemap(C * uExposure), 1.0);
}
