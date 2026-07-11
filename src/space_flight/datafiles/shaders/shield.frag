#version 140
// Shield bubble fragment shader — v2, with a "death" retraction animation.
//
// The living look is v1: a smooth low-frequency morphing field (triplanar
// value-noise), a fresnel rim, health-driven tint, and impact flashes.
//
// DEATH ANIMATION ("fluid retracting into random points"):
//   A handful of random SINK points are placed on the surface. The material is
//   considered "wet" wherever it lies within a coverage radius of its nearest
//   sink. As uDeath goes 0 -> 1 that radius shrinks to zero, so the fluid
//   drains away from open surface and retreats into the sinks, finally winking
//   out. The retracting boundary is roughened by animated noise (so it breaks
//   into droplets, not clean circles) and carries a bright meniscus, like the
//   edge of a receding liquid film. It's a pure per-fragment mask on top of the
//   living shader — no mesh changes.

// --- Per-frame / scene uniforms --------------------------------------------
uniform float iTime;
uniform vec3  iCameraPos;      // camera position in world space (for fresnel)

// --- Look knobs (set from Python; see main.py for defaults) -----------------
uniform vec3  uColorFull;      // tint at full health (light blue)
uniform vec3  uColorMid;       // tint at half health (light violet)
uniform vec3  uColorLow;       // tint at zero health (pink-violet)
uniform float uHealth;         // shield strength fraction in [0, 1]
uniform float uBaseAlpha;      // opacity of the calm interior
uniform float uPatternFreq;    // spatial frequency of the field (object-space units^-1)
uniform float uWarp;           // domain-warp strength (how much the field morphs)
uniform float uSpeed;          // animation speed (keep low for a slow morph)
uniform float uPulseSpeed;     // gentle "breathing" rate of the surface field
uniform float uPulseDepth;     // breathing depth (0 = steady)
uniform float uFresnelPower;   // rim tightness (higher = thinner, sharper edge)
uniform float uFresnelGain;    // rim brightness
uniform float uInteriorGlow;   // interior base brightness (flat term)
uniform float uPatternGain;    // interior brightness driven by the surface field
uniform float uPatternAlpha;   // how much the surface field firms up the opacity
uniform float uImpactWhiten;   // how white-hot an impact flash is (0..1)

// --- Impacts ----------------------------------------------------------------
#define MAX_IMPACTS 16
uniform int   uImpactCount;
uniform vec4  uImpacts[MAX_IMPACTS];  // xyz = obj-space pos, w = start time (s)
uniform float uImpactRadius;   // flash radius, object-space units
uniform float uImpactDecay;    // flash decay rate (1/s)
uniform float uImpactLife;     // seconds until an impact is dropped

// --- Death (fluid retraction) ----------------------------------------------
#define MAX_SINKS 12
uniform float uDeath;          // 0 = alive, 1 = fully drained
uniform int   uSinkCount;
uniform vec4  uSinks[MAX_SINKS];  // xyz = obj-space retraction point
uniform float uMaxReach;       // max over-surface distance any point is from a sink
uniform float uDeathEdge;      // softness of the coverage boundary (obj units)
uniform float uDeathWobble;    // boundary roughness amplitude (obj units)
uniform float uDeathBead;      // meniscus width at the fluid edge (obj units)
uniform float uDeathWhiten;    // meniscus whiteness (0..1)
uniform float uCoverMargin;    // coverage-radius margin at death start (>= 1)
uniform float uDeathFadeStart; // uDeath at which the last remnants start to fade

in vec3 vObjPos;
in vec3 vObjNormal;
in vec3 vWorldPos;
in vec3 vWorldNormal;

out vec4 p3d_FragColor;

// ---------------------------------------------------------------------------
// Smooth value noise (same lineage as the ocean shader's noise).
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
        mix(hash(i + vec2(0, 0)), hash(i + vec2(1, 0)), u.x),
        mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x),
        u.y);
}

// Deliberately shallow (2 octaves): we want the LOW-frequency component only.
float fbm(vec2 p) {
    return smoothNoise(p) * 0.65
         + smoothNoise(p * 2.03 + vec2(11.7, 5.3)) * 0.35;
}

// Cheap isotropic noise from a 3D point: average of three planar fbm samples.
float isoNoise(vec3 p) {
    return (fbm(p.xy) + fbm(p.yz + vec2(3.1, 1.7)) + fbm(p.zx + vec2(7.7, 2.3))) / 3.0;
}

// Smooth low-frequency field that slowly drifts AND morphs (animated warp).
float smoothField(vec2 p) {
    float t = iTime * uSpeed;
    vec2 w = vec2(fbm(p * 0.6 + vec2(0.0, t * 0.15)),
                  fbm(p * 0.6 + vec2(5.2, -t * 0.12)));
    return fbm(p + uWarp * w + vec2(t * 0.05, -t * 0.03));
}

// Triplanar evaluation of the field: no seams or poles, any shape.
float surfacePattern() {
    vec3 p = vObjPos * uPatternFreq;
    vec3 n = abs(normalize(vObjNormal));
    n *= n;
    n /= (n.x + n.y + n.z);
    return smoothField(p.yz) * n.x
         + smoothField(p.zx) * n.y
         + smoothField(p.xy) * n.z;
}

float impactGlow() {
    float glow = 0.0;
    for (int i = 0; i < MAX_IMPACTS; i++) {
        if (i >= uImpactCount) break;
        vec4 imp = uImpacts[i];
        float age = iTime - imp.w;
        if (age < 0.0 || age > uImpactLife) continue;
        float d = length(vObjPos - imp.xyz);
        glow += exp(-(d * d) / (uImpactRadius * uImpactRadius)) * exp(-age * uImpactDecay);
    }
    return glow;
}

// Distance from this fragment to the nearest retraction sink (object space).
float nearestSink() {
    float dmin = 1e9;
    for (int i = 0; i < MAX_SINKS; i++) {
        if (i >= uSinkCount) break;
        dmin = min(dmin, length(vObjPos - uSinks[i].xyz));
    }
    return dmin;
}

void main() {
    vec3 N = normalize(vWorldNormal);
    vec3 V = normalize(iCameraPos - vWorldPos);
    float NdotV = abs(dot(N, V));  // abs(): two-sided, back-faces point inward

    float fresnel = uFresnelGain * pow(1.0 - NdotV, uFresnelPower);
    float impact  = impactGlow();

    // Health-driven tint: blue (full) -> violet (half) -> pink (empty).
    float h = clamp(uHealth, 0.0, 1.0);
    vec3 tint = (h > 0.5)
        ? mix(uColorMid, uColorFull, (h - 0.5) * 2.0)
        : mix(uColorLow, uColorMid, h * 2.0);

    // Living surface field with a gentle "breathing" pulse.
    float pulse   = (1.0 - uPulseDepth) + uPulseDepth * sin(iTime * uPulseSpeed);
    float pattern = surfacePattern() * pulse;

    vec3 col  = tint * (uInteriorGlow + uPatternGain * pattern);
    col      += tint * fresnel;
    col      += mix(tint, vec3(1.0), uImpactWhiten) * impact;

    float alpha = uBaseAlpha + uPatternAlpha * pattern + fresnel + impact;

    // --- Death: retract the fluid into the sinks ---------------------------
    // The exact same mask drives the APPEARANCE animation, run in reverse:
    // Python ramps uDeath 0->1 to die (fluid retracts into the sinks and
    // vanishes) or 1->0 to spawn (fluid grows back out of the sinks).
    if (uDeath > 0.0 && uSinkCount > 0) {
        float dmin = nearestSink();

        // Roughen the boundary so it breaks into irregular drops rather than
        // perfect circles. Low frequency + high amplitude => big, lumpy,
        // non-round blobs. The slow time drift makes the edge creep like a
        // draining film.
        float wob = (isoNoise(vObjPos * uPatternFreq * 0.9 + iTime * 0.4) - 0.5)
                    * uDeathWobble * uDeath;
        float dd  = dmin + wob;

        // Coverage radius shrinks to zero: fluid remains only where dd < radius.
        // The margin keeps the first death frame fully covered (no pop).
        float radius = mix(uMaxReach * uCoverMargin, 0.0, uDeath);
        float edge   = radius - dd;                       // >0 wet, <0 drained
        float cover  = smoothstep(0.0, uDeathEdge, edge);

        // Meniscus riding the retracting edge (surface-tension bead).
        float bead = exp(-(edge * edge) / (uDeathBead * uDeathBead))
                     * smoothstep(0.0, 0.06, uDeath);

        // Over the final stretch the last remaining blobs simply fade out
        // (rather than flaring brighter as they collapse to points).
        float finalFade = 1.0 - smoothstep(uDeathFadeStart, 1.0, uDeath);

        // Drain the living material away where the film has receded...
        col   *= cover;
        alpha *= cover;

        // ...then add the fluid edge. Same brightness as the living rim
        // (uFresnelGain), with a faint highlight so it still reads as liquid.
        vec3 hot = mix(tint, vec3(1.0), uDeathWhiten);
        col   += hot * bead * uFresnelGain;
        alpha += bead * uFresnelGain;

        // Everything that remains dissolves away at the very end.
        col   *= finalFade;
        alpha *= finalFade;
    }

    p3d_FragColor = vec4(col, clamp(alpha, 0.0, 1.0));
}
