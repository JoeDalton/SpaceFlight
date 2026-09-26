#version 330
// Cloud colour pass.
//
// Each billboard is a SAMPLE OF A VOLUME, not a sprite. It contributes a thin
// veil of scattering; a solid cloud is the SUM of many veils, exactly as the
// reference's raymarch builds one out of many steps of similar, modest optical
// depth. Three things follow, and all are load-bearing:
//
//   * WHAT the volume looks like -- its outline and its colour -- is a
//     continuous function of world position AND OF NOTHING ELSE. Not of which
//     billboard is asking, and not of which cloud it belongs to. Baked
//     per-particle colour once caused visible quad-shaped patches and a violet
//     cast on shadowed puffs; a per-CLOUD vertical slab then caused something
//     worse, because two overlapping clouds evaluated different density at the
//     same point and the profile's cut at one cloud's ceiling sliced a flat
//     plane through the body of its neighbour -- hard-edged plates and
//     straight-sided holes. The slab now belongs to the cloud TYPE, so every
//     billboard of a type agrees everywhere.
//   * HOW MUCH volume a fragment stands for IS a per-quad property: the sprite
//     atlas supplies a lumpy thickness profile, so one billboard can stand in
//     for a whole lumpy puff instead of a smooth ball. That is a large saving in
//     billboard count, and it costs nothing in seams because thickness only ever
//     scales a fragment's alpha, and overlapping alphas blend smoothly. What it
//     must NEVER do is gate the silhouette -- that belongs to the density field.
//   * Mixing cloud types is a SUPERPOSITION, and the blender performs it. A
//     fragment evaluates only its own type's field; the optical depths of every
//     type's veils add along the view ray for free. So there is never a reason
//     for one fragment to evaluate more than one field.
//
// Blending is premultiplied "over", drawn back-to-front (see field.py). That is
// not a workaround: with alpha = 1 - exp2(-opticalDepth), over-blending N
// overlapping billboards leaves transmittance exp2(-sum of opticalDepth), which
// is exactly the raymarch's accumulation performed by the hardware blender. The
// overlapping billboards along a view ray ARE the march's steps.
uniform sampler3D cloudNoise;    // one tileable octave of value noise, R8
uniform sampler2D p3d_Texture0;  // puff atlas: alpha = per-quad THICKNESS profile
uniform vec3  viewPos;
uniform vec3  noiseOffset;      // wind advection, in METRES (see field.py)
uniform float noiseSize;        // volume resolution, for the coord → uvw divide

// Per cloud TYPE: ten vec4s each, indexed by the flat layer id the vertex stage
// resolved. Carries the type's density field AND its optics -- the sun march and
// the scattering -- because every one of those scales with the type's own
// geometry: a 400 m cirrus sheet and a 2.4 km cumulonimbus tower have no business
// sharing a march length or an optical-depth cap. See noise.pack_layer_params for
// the packing, which this mirrors.
// Size is MAX_LAYERS * LAYER_VEC4S from noise.py, and a test checks it: getting it
// wrong is silent and destructive. Too small and the higher layers read out of
// bounds -- undefined values for their crossfade and extinction, so those layers
// simply stop drawing -- while too small in only ONE stage fails to link outright.
uniform vec4 layerParams[96];

// Scene-wide lighting: the sun and the camera, which every type shares. All live
// uniforms, so the sun can move (there is nothing baked).
uniform vec3  sunDir;           // FROM the scene TOWARD the sun, normalised
uniform vec3  sunColor;         // direct sunlight
uniform vec3  skyColor;         // ambient sky fill
uniform vec3  hazeColor;        // what distant cloud tends to; see main()
uniform float sunBrightness;
uniform float skyStrength;      // weight of the ambient sky term
uniform float skyOcclusion;     // how much of it reaches the layer's underside
uniform float exposure;         // see the tonemapping note in main()
uniform float horizonFade;      // 1 / metres at which a cloud fades fully out
// 1 / (2 * planet radius): how fast the cloud deck droops away with distance. The
// VERTEX stage applies it to the geometry; here it is undone before sampling,
// because the density field is defined on a flat slab. Zero for a flat world.
uniform float earthCurvature;

in  vec2  vUv;          // this fragment's place in its puff sprite
in  vec3  worldPos;
in  float vRadius;
in  float vFade;
flat in int vLayer;
out vec4 fragColor;

const int LAYER_VEC4S = 12;

// The cloud type's field, unpacked once per fragment. Cheap: the layer index is
// dynamically uniform across a draw, so these are cached uniform reads, not the
// two dozen texture fetches a parameter texture would have cost.
struct Field {
    vec3  noiseScale;
    vec3  noiseOrigin;    // the type's decorrelating offset, plus wind advection
    vec4  octaveScales;
    vec4  octaveWeights;
    float threshLo;
    float threshHi;
    float slabBase;
    float slabThickness;
    float baseRamp;         // the flat bottom: scales density
    float topErosion;       // the bulging top: raises the threshold
    float topExponent;      //   ...and the curve of that rise
    float shadowGain;       // calibrates the 2-octave shadow fbm onto the field's
    float shadowBias;       //   own distribution; see noise.shadow_calibration
    float extinction;       // per BILLBOARD: scaled 1/(volume fraction)
    float fieldExtinction;  // the field's own: for the sun march
    vec4  shellFade;        // (fadeInLo, fadeInHi, fadeOutLo, fadeOutHi), metres
    // Optics: how light travels through THIS type (see noise.CloudOptics).
    int   sunSteps;
    float sunStepLength;
    float shadowStrength;
    float multipleScattering;  // sky-coloured shadow fill; see main()
    float powderStrength;
    float powderLength;
    float maxOpticalDepth;
    // Pre-solved phase weights; see phaseFunction. Solved on the CPU from the
    // type's forward_gain / backward_gain, which are the knobs an author sets.
    float phaseForward;
    float phaseBackward;
    float phaseIsotropic;
    float forwardAnisotropy;  // SHAPE only: the falloff, not the gain
};

Field getField(int layer) {
    int b = layer * LAYER_VEC4S;
    vec4 v0 = layerParams[b + 0];
    vec4 v3 = layerParams[b + 3];
    vec4 v4 = layerParams[b + 4];
    vec4 v5 = layerParams[b + 5];
    Field f;
    f.noiseScale     = v0.xyz;
    f.threshLo       = v0.w;
    f.octaveScales   = layerParams[b + 1];
    f.octaveWeights  = layerParams[b + 2];
    // The type's own offset is what makes two types sharing one noise volume
    // carve independently; the wind advection rides on top of it. The advection
    // arrives in METRES and is scaled here, so one uniform serves every layer
    // and each stays locked to its own field whatever its feature size.
    f.noiseOrigin    = v3.xyz + noiseOffset * f.noiseScale;
    f.threshHi       = v3.w;
    f.slabBase       = v4.x;
    f.slabThickness  = v4.y;
    f.baseRamp       = v4.z;
    f.topErosion     = v4.w;
    vec4 v6 = layerParams[b + 6];
    vec4 v7 = layerParams[b + 7];
    vec4 v8 = layerParams[b + 8];
    vec4 v9 = layerParams[b + 9];
    f.topExponent    = v6.x;
    f.shadowGain     = v6.y;
    f.shadowBias     = v6.z;
    f.maxOpticalDepth = v6.w;
    f.extinction     = v5.x;
    f.fieldExtinction = v5.y;
    f.sunSteps       = int(v7.x + 0.5);
    f.sunStepLength  = v7.y;
    f.shadowStrength = v7.z;
    f.multipleScattering = v7.w;
    f.powderStrength = v8.x;
    f.powderLength   = v8.y;
    f.phaseForward   = v8.z;
    f.phaseBackward  = v8.w;
    f.phaseIsotropic = v9.x;
    f.forwardAnisotropy = v9.y;
    f.shellFade      = layerParams[b + 11];
    return f;
}

float sampleNoise(vec3 coord) {
    return texture(cloudNoise, coord / noiseSize).r;
}

// Fixed per-octave offsets, so the octaves never re-align into a grid. They are
// CONSTANT rather than time-varying on purpose: the wind advection already lives
// in the coordinate, and because an octave's scale multiplies the advection along
// with everything else, one offset locks every octave to the field at once.
// Making these drift instead would slide the detail octaves through the
// billboards and make the clouds boil.
//
// These MUST match OCTAVE_OFFSETS in noise.py, which is what drives placement: if
// the two disagree, billboards land in clear air and cloud goes undrawn. A test
// checks the two agree by reading this file.
const vec3 OCTAVE_2_OFFSET = vec3( 0.31,  0.73,  0.19);
const vec3 OCTAVE_3_OFFSET = vec3(-0.57,  0.11,  0.83);
const vec3 OCTAVE_4_OFFSET = vec3( 0.67, -0.29,  0.41);

// Four octaves of value noise, at the reference's own 1 / 2 / 7 / 16 scales and
// 1/f weights. The scales are whole numbers for a reason beyond taste: a cell
// recycling across the domain shifts by one noise period, and an octave at scale
// k then shifts by k periods -- seamless only when k is an integer.
float cloudFbm(Field f, vec3 coord) {
    return sampleNoise(coord * f.octaveScales.x)                   * f.octaveWeights.x
         + sampleNoise(coord * f.octaveScales.y + OCTAVE_2_OFFSET) * f.octaveWeights.y
         + sampleNoise(coord * f.octaveScales.z + OCTAVE_3_OFFSET) * f.octaveWeights.z
         + sampleNoise(coord * f.octaveScales.w + OCTAVE_4_OFFSET) * f.octaveWeights.w;
}

// Two octaves, CALIBRATED onto the full field's distribution. Used only along the
// sun march: Beer-Lambert exponentiates the integral, so high-frequency structure
// along a shadow ray barely survives into the result, and the low octaves carry
// essentially all of the occlusion signal (they correlate with the full field at
// 0.97). Halving the taps per step is what makes the march affordable at this
// overdraw.
//
// The affine correction is not cosmetic. Simply renormalising by the summed
// weights -- which is what this did at first -- leaves the mean AND the spread
// too high, so against the same threshold the march finds 1.65x as much cloud as
// exists and shadows the entire field far too heavily. That showed up as grey
// cloud tops in full sun, with the shading looking plausible everywhere else.
// See noise.shadow_calibration, which derives the gain and bias from the weights.
float shadowFbm(Field f, vec3 coord) {
    float pair = sampleNoise(coord * f.octaveScales.x) * f.octaveWeights.x
               + sampleNoise(coord * f.octaveScales.y + OCTAVE_2_OFFSET)
                 * f.octaveWeights.y;
    return pair * f.shadowGain + f.shadowBias;
}

// The vertical shaping. A cumulus's flat base and its cauliflower top are two
// DIFFERENT physical mechanisms, and this is the one place the shader models them
// differently -- which is the whole reason the tops bulge.
//
//   * The BASE scales density. Condensation begins at one altitude across the
//     whole deck, so a multiplier ramping up from the slab base is exactly right,
//     and it gives the underside a plane.
//   * The TOP raises the THRESHOLD. How high a parcel rises depends on how strong
//     the updraft is there, so the boundary belongs where the field crosses a
//     rising bar: a column whose field value is high keeps clearing it and towers,
//     a weak one stops short, and the top surface follows the field.
//
// Scaling density toward zero at the top CANNOT produce that. It puts the
// silhouette's top wherever the multiplier reaches zero, which is the same
// altitude everywhere, and the clouds read as sliced off against a plane however
// gently the fade is done. That was a real bug, not a tuning miss.
//
// Raising the threshold also bounds the slab for free: once the lift carries the
// threshold past the fbm's maximum nothing can be cloud, so no hard clamp is
// doing that job and there is nothing to see at the ceiling.
//
// Height is normalised by the slab thickness, so every vertical parameter is "per
// slab" rather than per metre and a type keeps its shape whatever its extent.
float slabHeight(Field f, float z) {
    return (z - f.slabBase) / max(f.slabThickness, 1e-3);
}

float baseDensity(Field f, float h) {
    return 1.0 - exp2(-f.baseRamp * h);
}

float thresholdLift(Field f, float h) {
    return f.topErosion * pow(clamp(h, 0.0, 1.0), f.topExponent);
}

// The threshold window, lifted for this height. Shared by the view sample and the
// sun march so the two agree about where the cloud ends.
float coverageAt(Field f, float h, float raw) {
    float lift = thresholdLift(f, h);
    return smoothstep(f.threshLo + lift, f.threshHi + lift, raw);
}

float cloudDensity(Field f, vec3 p) {
    float h = slabHeight(f, p.z);
    if (h <= 0.0 || h >= 1.0) return 0.0;
    // World metres → noise coordinates, advected by the wind so the field
    // translates WITH the billboards instead of them sliding through it.
    vec3 coord = p * f.noiseScale + f.noiseOrigin;
    return coverageAt(f, h, cloudFbm(f, coord)) * baseDensity(f, h);
}

// Henyey-Greenstein phase function.
float hgPhase(float x, float g) {
    float g2 = g * g;
    return 0.25 * ((1.0 - g2) * pow(1.0 + g2 - 2.0 * g * x, -1.5));
}

// The reference's dual-lobe phase: a strong forward lobe (the silver lining when
// you look toward the sun through a cloud) mixed with a weaker backward one.
//
// Normalised by its own value at 90 degrees, so that a side-lit cloud gets a
// phase of 1. That makes sunBrightness mean something an artist can reason
// about -- the brightness of a plain sunlit cloud -- instead of an abstract
// radiometric scale, and it leaves the ratios between angles untouched: the
// forward lobe still peaks around 16x, which the tonemap's knee compresses
// into a highlight rather than a clipped white patch.
//
// There is NO normalising division here, and no normalising constant. The three
// weights arrive pre-solved (noise.phase_weights) so that the phase already comes
// out as 1 at 90 degrees, forwardGain at 0 and backwardGain at 180. That solve is
// what makes those two gains independent knobs: two lobes alone leave only their
// weight ratio free, which is one degree of freedom for two observables, so the
// forward and backward brightnesses could not be set separately -- every
// adjustment of one moved the other through the shared normaliser. The isotropic
// term supplies the missing degree of freedom.
//
// It is also cheaper than what it replaces: two pow calls instead of three, and
// no divide.
const float BACKWARD_G = -0.4;

float phaseFunction(Field f, float x) {
    // Clamped at zero as a last guard. The CPU already refuses gains that would
    // dip negative, but a negative radiance is a dark hole in the middle of a
    // cloud rather than an obvious error, so it is not worth trusting.
    return max(0.0,
               f.phaseForward   * hgPhase(x, f.forwardAnisotropy)
             + f.phaseBackward  * hgPhase(x, BACKWARD_G)
             + f.phaseIsotropic * 0.25);
}

// The "powder" term: darkens cloud that is optically THIN, so a cloud's wispy
// fringes read as wisps rather than as dilute versions of its core. It applies to
// the sun term only, as in the reference.
//
// It must be fed the LOCAL optical depth -- how dense the cloud is HERE -- and
// emphatically not the sunward optical depth. Feeding it the sunward depth makes
// the term a function of how deeply buried a point is, which inverts its meaning:
// the directly-lit surface then has the least sunward depth and so gets the
// heaviest darkening, while brightness peaks somewhere in the middle. The result
// is a cloud top that is greyish overall with scattered bright patches where the
// depth happens to land near the peak -- which is exactly what it looked like.
//
// The local optical depth has to be a function of world position only, or the term
// picks up the billboard's size (a per-quad chord scales with radius, and that
// once made small near billboards dark and large distant ones white). So it is
// built from the FIELD's extinction over a fixed reference length rather than
// from this quad's chord.
float powder(Field f, float density) {
    return 1.0 - exp2(-f.fieldExtinction * density * f.powderLength * 2.0);
}

// Optical depth from p toward the sun: a short march through the same density
// field. This is what makes clouds shadow themselves AND each other -- with one
// field per type spanning the whole sky, a cloud between p and the sun darkens p
// for free, which the old per-cloud fields could not do at all.
//
// It returns the DEPTH rather than the transmittance because two things derive
// from it (the shadow and the powder term), and both must be functions of world
// position only. Deriving either from a fragment's OWN optical depth instead
// couples them to the billboard's size, which is what made small near billboards
// render almost black while large distant ones went white.
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
        vec3 coord = position * f.noiseScale + f.noiseOrigin;
        density += coverageAt(f, h, shadowFbm(f, coord)) * baseDensity(f, h);
    }
    // shadowStrength is the artistic handle on how hard clouds shadow themselves
    // and each other: 1 is the physical value, lower opens up the interiors.
    return density * f.sunStepLength * f.fieldExtinction * f.shadowStrength;
}

void main() {
    Field f = getField(vLayer);

    // The sprite's alpha is the blob's THICKNESS profile -- how many metres of
    // cloud sit behind this pixel -- never a silhouette.
    float puff = texture(p3d_Texture0, vUv).a;
    if (puff < 0.01) discard;                // the sprite's own soft edge
    float chord = 2.0 * vRadius * puff;

    // NOT DONE, and the next thing to try if stretched cirrus still reads too
    // smooth: the atlas sprites are painted cumulus puffs, so a stretched one
    // gives a smooth elliptical lobe rather than the fibrous striations a wisp
    // wants. Stretching MAGNIFIES detail along the long axis (a 5-pixel edge lump
    // becomes a 30-pixel undulation), which is backwards -- a wisp needs fine
    // detail ALONG and softness ACROSS.
    //
    // The cheap fix is not a new atlas but procedural striation: modulate `puff`
    // by a 1-D sample of the noise volume we already have, taken along the
    // stretched axis at a frequency well above the field's finest octave. One
    // extra tap, no new asset, resolution-independent, and it only wants to apply
    // where aspect > 1 (so it would need the aspect passed through from the vertex
    // stage). Left out for now: the field's own anisotropy may carry enough.

    vec3 toCamera = worldPos - viewPos;
    float distance = length(toCamera);
    vec3 V = -toCamera / distance;

    // Sample the field AT THE QUAD PLANE, which passes through the particle
    // centre. It is tempting to offset back along the view ray to the middle
    // of the chord -- nominally the centre of the volume this fragment stands
    // for -- but that displaces the lookup by up to one particle radius, which
    // at these radii is most of a noise feature. Two things went wrong with it:
    // a cloud's holes appeared shifted from the cloud actually drawn, and the
    // offset varied both with the particle's radius and across its sprite, so
    // overlapping billboards disagreed about where the cloud was and cut
    // hard-edged holes in each other. Sampling on the plane keeps the density a
    // function of the position actually being drawn.
    //
    // The one correction: the vertex stage drooped this quad to follow the
    // planet's curve, and the density field is defined on a FLAT slab, so the
    // droop is added back here. Sampling the drooped position instead would push
    // distant cloud out of the bottom of its own slab.
    vec3 samplePos = vec3(
        worldPos.xy,
        worldPos.z + dot(toCamera.xy, toCamera.xy) * earthCurvature
    );
    float density = cloudDensity(f, samplePos);
    if (density <= 0.0) discard;             // THE crisp silhouette

    // Aerial perspective. Distant cloud loses contrast to the air in front of it
    // and tends toward the haze's own colour -- it does NOT become transparent,
    // which is the distinction that matters here. Fading alpha instead (what this
    // did) makes a distant cloud take on whatever is behind it: fine against sky,
    // but looking DOWN at a deck the thing behind it is the ground, so the deck
    // faded to green and the horizon read as a band of bare land.
    float haze = clamp(distance * horizonFade, 0.0, 1.0);
    // Fully hazed cloud is indistinguishable from sky, so stop before the sun
    // march rather than paying for an invisible fragment. This also hides the
    // outermost shell's box edge for free, as long as the haze completes inside it.
    if (haze >= 0.999) discard;
    if (vFade <= 0.0) discard;

    // Per-fragment optical depth, CAPPED. The cap is what keeps the accumulation
    // of many overlapping billboards smooth. A quad allowed to reach alpha ~1
    // becomes an opaque, hard-edged blob and its own outline shows through the
    // cloud; the old sprite-based shader never hit that because its per-quad
    // alpha peaked around 0.6. Every billboard must stay a thin veil.
    float opticalDepth = min(f.extinction * density * chord, f.maxOpticalDepth);

    // LOD shell crossfade. Adjacent shells share a band -- one's fade-out is the
    // next one's fade-in -- so these weights sum to EXACTLY 1 there, and because
    // the weight is evaluated per fragment from the camera distance, two shells
    // agree at any given world point rather than at their cell centres.
    //
    // Applied to OPTICAL DEPTH, and applied AFTER the cap, and both matter:
    //
    //   * on optical depth, because transmittance then multiplies out as
    //     exp2(-w0*od) * exp2(-w1*od) = exp2(-od), exact for any od. Weighting
    //     alpha instead is only right for thin cloud: two half-weight billboards
    //     at od 1.5 give alpha 0.325 each, compositing to 0.544 against the
    //     correct 0.65 -- a ~16 percent light ring at the crossfade radius, which
    //     sweeps across the field as the camera flies.
    //   * after the cap, because capping a weighted depth would let two shells
    //     each reach the cap and sum to twice it.
    float shellWeight = smoothstep(f.shellFade.x, f.shellFade.y, distance)
                      * (1.0 - smoothstep(f.shellFade.z, f.shellFade.w, distance));
    opticalDepth *= shellWeight;

    float alpha = (1.0 - exp2(-opticalDepth)) * vFade;
    if (alpha <= 0.0) discard;

    // Lighting. Sun march last, after every discard, so fragments that never
    // contribute never pay for it.
    float tauSun = sunOpticalDepth(f, samplePos);
    // Pure Beer-Lambert, with NO floor. What fills the shadow is the ambient term
    // below, and putting it there rather than here is the whole point -- see the
    // note on multipleScattering.
    float sunVisibility = exp2(-tauSun);
    // Softened toward 1 by powderStrength: at full strength it takes thin
    // fringes all the way to black, which reads as dirt rather than cloud.
    float powderTerm = mix(1.0, powder(f, density), f.powderStrength);

    // Skylight arrives from above, so the underside of the cloud layer sees less
    // of it. This attenuates the SKY term alone -- it is the sky being occluded,
    // and applying it to the whole colour (as this once did) dims direct sunlight
    // by altitude, which nothing physical justifies and which cost the sunlit tops
    // about a quarter of their brightness.
    float skyReach = mix(skyOcclusion, 1.0, clamp(slabHeight(f, samplePos.z), 0.0, 1.0));

    // Single scattering alone takes a cloud's interior to black, because it only
    // ever removes light along the path to the sun. A real core is lit by light
    // scattered in from every direction, and this term stands in for it. Two
    // things about WHERE it lives are load-bearing, and it used to be wrong on
    // both:
    //
    //   * It is SKY-COLOURED, not sun-coloured. The light reaching a shadowed
    //     interior or underside arrives from the sky and from neighbouring cloud,
    //     not down a direct beam. As a floor on sun visibility it injected the
    //     sun's own colour into every shadow, which at dusk swamped the (properly
    //     blue) sky term by 4.6:1 in red and left the whole deck orange -- with no
    //     blue-grey shadowed sides at all.
    //   * It is NOT phase-weighted. Multiple scattering is near-isotropic. Inside
    //     the direct term it picked up the phase function, so looking toward the
    //     sun multiplied the shadow fill by up to 18x and shadowed cloud came out
    //     BRIGHTER than fully-lit cloud viewed side-on -- which is what flattened
    //     a dusk deck into one uniform orange.
    float ambient = skyStrength * skyReach
                  + f.multipleScattering * sunBrightness * (1.0 - sunVisibility);

    float phase = phaseFunction(f, dot(sunDir, -V));
    vec3 colour = sunColor * (sunBrightness * sunVisibility * powderTerm * phase)
                + skyColor * ambient;

    // The one unavoidable deviation from the reference, which tonemaps the whole
    // frame; the clouds are a translucent element inside an existing pipeline and
    // cannot. The reference's soft knee is applied here, to the cloud's own
    // radiance, after an exposure scale. It is what compresses the forward-
    // scattering peak so the silver lining rolls off instead of clipping, and it
    // does most of the work of bringing the sunlit and shadowed sides to a
    // believable ratio rather than the raw phase function's ~16:1.
    //
    // Applied to the PEAK CHANNEL and used to scale the colour, rather than to
    // each channel independently. Per-channel is the obvious way and it silently
    // destroys hue: every channel approaches the same asymptote, so an orange dusk
    // sun at silver-lining intensity (16, 8.8, 4.2) maps to (0.998, 0.994, 0.972)
    // -- white. The cloud's brightest, most saturated highlights were exactly the
    // ones losing the sun's colour. Scaling by the peak instead preserves
    // chromaticity exactly and can never exceed 1, so the clouds keep whatever
    // colour the light actually has.
    colour *= exposure;
    float peak = max(max(colour.r, colour.g), colour.b);
    if (peak > 0.0) {
        colour *= (peak / sqrt(peak * peak + 1.0)) / peak;
    }

    // Aerial perspective, applied to the DISPLAYED colour: the haze sits between
    // the eye and the cloud, so it acts after the cloud's own tonemapping rather
    // than being scattered by the cloud itself.
    colour = mix(colour, hazeColor, haze);

    fragColor = vec4(colour * alpha, alpha);   // premultiplied "over"
}
