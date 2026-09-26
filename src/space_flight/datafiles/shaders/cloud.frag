#version 330
// Cloud colour pass. Each billboard is a SAMPLE OF A VOLUME, not a sprite: its
// outline and colour are functions of world position alone, while the sprite only
// supplies how much volume sits behind each pixel (a thickness profile). Types mix
// by superposition in the blender, so a fragment only evaluates its own field.
//
// Premultiplied "over", back to front: with alpha = 1 - exp2(-opticalDepth), N
// overlapping billboards leave transmittance exp2(-sum of depths), i.e. the
// billboards along a view ray ARE the steps of a raymarch. See docs/scenes.md.
uniform sampler3D cloudNoise;    // one tileable octave of value noise, R8
uniform sampler2D p3d_Texture0;  // puff atlas: alpha = per-quad THICKNESS profile
uniform vec3  camPos;
uniform vec3  noiseOffset;      // wind advection, in METRES
uniform float noiseSize;        // volume resolution, for the coord → uvw divide

// LAYER_VEC4S per cloud type, mirroring noise.pack_layer_params. Size is
// MAX_LAYERS * LAYER_VEC4S (a test checks it): too small reads out of bounds, and a
// mismatch with cloud.vert fails to link.
uniform vec4 layerParams[96];

uniform vec3  sunDir;           // FROM the scene TOWARD the sun, normalised
uniform vec3  sunColor;
uniform vec3  skyColor;
uniform vec3  hazeColor;        // what distant cloud tends to
uniform float sunBrightness;
uniform float skyStrength;
uniform float skyOcclusion;     // share of sky light reaching a deck's underside
uniform float exposure;
uniform float horizonFade;      // 1 / metres over which cloud tends fully to haze
uniform float earthCurvature;   // 1 / (2R); undone here, the field is flat

in  vec2  vUv;
in  vec3  worldPos;
in  float vRadius;
in  float vFade;
flat in int vLayer;
out vec4 fragColor;

const int LAYER_VEC4S = 12;

// The type's field and optics. The layer index is dynamically uniform over a draw,
// so these are cached uniform reads.
struct Field {
    vec3  noiseScale;
    vec3  noiseOrigin;    // decorrelating offset plus wind advection
    vec4  octaveScales;
    vec4  octaveWeights;
    float threshLo;
    float threshHi;
    float slabBase;
    float slabThickness;
    float baseRamp;
    float topErosion;
    float topExponent;
    float shadowGain;       // noise.shadow_calibration
    float shadowBias;
    float extinction;       // per BILLBOARD
    float fieldExtinction;  // the field's own, for the sun march and powder
    vec4  shellFade;        // (fadeInLo, fadeInHi, fadeOutLo, fadeOutHi), metres
    int   sunSteps;
    float sunStepLength;
    float shadowStrength;
    float multipleScattering;
    float powderStrength;
    float powderLength;
    float maxOpticalDepth;
    float phaseForward;     // pre-solved by noise.phase_weights
    float phaseBackward;
    float phaseIsotropic;
    float forwardAnisotropy;
};

Field getField(int layer) {
    int b = layer * LAYER_VEC4S;
    vec4 v0 = layerParams[b + 0];
    vec4 v3 = layerParams[b + 3];
    vec4 v4 = layerParams[b + 4];
    vec4 v5 = layerParams[b + 5];
    vec4 v6 = layerParams[b + 6];
    vec4 v7 = layerParams[b + 7];
    vec4 v8 = layerParams[b + 8];
    vec4 v9 = layerParams[b + 9];
    Field f;
    f.noiseScale      = v0.xyz;
    f.threshLo        = v0.w;
    f.octaveScales    = layerParams[b + 1];
    f.octaveWeights   = layerParams[b + 2];
    // Wind arrives in metres and is scaled per layer, so every layer stays locked
    // to its own field whatever its feature size.
    f.noiseOrigin     = v3.xyz + noiseOffset * f.noiseScale;
    f.threshHi        = v3.w;
    f.slabBase        = v4.x;
    f.slabThickness   = v4.y;
    f.baseRamp        = v4.z;
    f.topErosion      = v4.w;
    f.extinction      = v5.x;
    f.fieldExtinction = v5.y;
    f.topExponent     = v6.x;
    f.shadowGain      = v6.y;
    f.shadowBias      = v6.z;
    f.maxOpticalDepth = v6.w;
    f.sunSteps        = int(v7.x + 0.5);
    f.sunStepLength   = v7.y;
    f.shadowStrength  = v7.z;
    f.multipleScattering = v7.w;
    f.powderStrength  = v8.x;
    f.powderLength    = v8.y;
    f.phaseForward    = v8.z;
    f.phaseBackward   = v8.w;
    f.phaseIsotropic  = v9.x;
    f.forwardAnisotropy = v9.y;
    f.shellFade       = layerParams[b + 11];
    return f;
}

float sampleNoise(vec3 coord) {
    return texture(cloudNoise, coord / noiseSize).r;
}

// Constant per-octave offsets (drifting ones would make the clouds boil). MUST
// match OCTAVE_OFFSETS in noise.py, which drives placement; a test reads this file.
const vec3 OCTAVE_2_OFFSET = vec3( 0.31,  0.73,  0.19);
const vec3 OCTAVE_3_OFFSET = vec3(-0.57,  0.11,  0.83);
const vec3 OCTAVE_4_OFFSET = vec3( 0.67, -0.29,  0.41);

float lowOctaves(Field f, vec3 coord) {
    return sampleNoise(coord * f.octaveScales.x)                   * f.octaveWeights.x
         + sampleNoise(coord * f.octaveScales.y + OCTAVE_2_OFFSET) * f.octaveWeights.y;
}

float cloudFbm(Field f, vec3 coord) {
    return lowOctaves(f, coord)
         + sampleNoise(coord * f.octaveScales.z + OCTAVE_3_OFFSET) * f.octaveWeights.z
         + sampleNoise(coord * f.octaveScales.w + OCTAVE_4_OFFSET) * f.octaveWeights.w;
}

// The sun march's two octaves, calibrated onto the full field's distribution.
float shadowFbm(Field f, vec3 coord) {
    return lowOctaves(f, coord) * f.shadowGain + f.shadowBias;
}

// Normalised height in the slab: 0 at the base, 1 at the ceiling.
float slabHeight(Field f, float z) {
    return (z - f.slabBase) / max(f.slabThickness, 1e-3);
}

// Flat bases scale DENSITY; bulging tops RAISE THE THRESHOLD (noise.threshold_lift).
// Shared by the view sample and the sun march so both agree where the cloud ends.
float slabDensity(Field f, float h, float raw) {
    float lift = f.topErosion * pow(clamp(h, 0.0, 1.0), f.topExponent);
    return smoothstep(f.threshLo + lift, f.threshHi + lift, raw)
         * (1.0 - exp2(-f.baseRamp * h));
}

float cloudDensity(Field f, vec3 p) {
    float h = slabHeight(f, p.z);
    if (h <= 0.0 || h >= 1.0) return 0.0;
    return slabDensity(f, h, cloudFbm(f, p * f.noiseScale + f.noiseOrigin));
}

float hgPhase(float x, float g) {
    float g2 = g * g;
    return 0.25 * ((1.0 - g2) * pow(1.0 + g2 - 2.0 * g * x, -1.5));
}

// The pre-solved weights put 1 at 90°, forwardGain at 0° and backwardGain at 180°,
// so no normalisation is needed here.
const float BACKWARD_G = -0.4;

float phaseFunction(Field f, float x) {
    // Clamped as a last guard: a negative radiance renders as a dark hole.
    return max(0.0,
               f.phaseForward   * hgPhase(x, f.forwardAnisotropy)
             + f.phaseBackward  * hgPhase(x, BACKWARD_G)
             + f.phaseIsotropic * 0.25);
}

// Darkens optically THIN cloud. Fed the LOCAL density over a fixed length: the
// sunward depth would invert it, and the quad's chord would tie it to quad size.
float powder(Field f, float density) {
    return 1.0 - exp2(-f.fieldExtinction * density * f.powderLength * 2.0);
}

// Optical depth toward the sun through the same field, which is what lets clouds
// shadow themselves AND each other. A depth, not a transmittance, so everything
// derived from it stays a function of world position only.
float sunOpticalDepth(Field f, vec3 p) {
    if (f.sunSteps <= 0) {
        return 0.0;
    }
    vec3 increment = sunDir * f.sunStepLength;
    vec3 position = p + increment * 0.5;
    float density = 0.0;
    for (int i = 0; i < f.sunSteps; i++, position += increment) {
        float h = slabHeight(f, position.z);
        if (h <= 0.0 || h >= 1.0) {
            continue;
        }
        density += slabDensity(f, h, shadowFbm(f, position * f.noiseScale + f.noiseOrigin));
    }
    return density * f.sunStepLength * f.fieldExtinction * f.shadowStrength;
}

void main() {
    Field f = getField(vLayer);

    float puff = texture(p3d_Texture0, vUv).a;
    if (puff < 0.01) discard;                // the sprite's own soft edge
    float chord = 2.0 * vRadius * puff;

    vec3 toCamera = worldPos - camPos;
    float distance = length(toCamera);
    vec3 V = -toCamera / distance;

    // Sampled ON the quad plane (not mid-chord, which would make overlapping quads
    // disagree), with the vertex stage's droop added back for the flat field.
    vec3 samplePos = vec3(
        worldPos.xy,
        worldPos.z + dot(toCamera.xy, toCamera.xy) * earthCurvature
    );
    float density = cloudDensity(f, samplePos);
    if (density <= 0.0) discard;             // THE crisp silhouette

    // Aerial perspective tends to the haze COLOUR, never to transparent (a fading
    // deck would show the ground behind it). Fully hazed cloud is sky: skip it.
    float haze = clamp(distance * horizonFade, 0.0, 1.0);
    if (haze >= 0.999) discard;
    if (vFade <= 0.0) discard;

    // Capped so every billboard stays a thin veil, never a hard-edged opaque quad.
    float opticalDepth = min(f.extinction * density * chord, f.maxOpticalDepth);

    // LOD shell crossfade: adjacent shells' weights sum to 1. Applied to OPTICAL
    // DEPTH (exact for any depth, unlike alpha) and AFTER the cap (or two shells
    // could each reach it).
    float shellWeight = smoothstep(f.shellFade.x, f.shellFade.y, distance)
                      * (1.0 - smoothstep(f.shellFade.z, f.shellFade.w, distance));
    opticalDepth *= shellWeight;

    float alpha = (1.0 - exp2(-opticalDepth)) * vFade;
    if (alpha <= 0.0) discard;

    // Lighting last, after every discard.
    float sunVisibility = exp2(-sunOpticalDepth(f, samplePos));
    float powderTerm = mix(1.0, powder(f, density), f.powderStrength);
    // Skylight comes from above: occlude the SKY term toward the underside only.
    float skyReach = mix(skyOcclusion, 1.0, clamp(slabHeight(f, samplePos.z), 0.0, 1.0));
    // Multiple-scattering fill: sky-coloured and NOT phase-weighted, or dusk
    // shadows turn orange and sunward shadow outshines side-lit cloud.
    float ambient = skyStrength * skyReach
                  + f.multipleScattering * sunBrightness * (1.0 - sunVisibility);

    float phase = phaseFunction(f, dot(sunDir, -V));
    vec3 colour = sunColor * (sunBrightness * sunVisibility * powderTerm * phase)
                + skyColor * ambient;

    // Soft knee on the PEAK channel, scaling the colour, which preserves hue (a
    // per-channel knee maps a bright orange sun to white). Colours are never
    // negative, so peak / sqrt(peak² + 1) / peak needs no zero guard.
    colour *= exposure;
    float peak = max(max(colour.r, colour.g), colour.b);
    colour *= inversesqrt(peak * peak + 1.0);

    // Haze acts on the displayed colour: it sits between the eye and the cloud.
    colour = mix(colour, hazeColor, haze);

    fragColor = vec4(colour * alpha, alpha);   // premultiplied "over"
}
