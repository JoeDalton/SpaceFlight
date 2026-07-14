#version 140
// Laser bolt fragment shader: an analytic "capsule impostor".
//
// Every fragment of the camera-facing card shoots a ray from the eye through
// itself and measures the distance to the bolt's core SEGMENT [uA, uB]. That
// distance -> brightness gives a glowing capsule that is correct at EVERY angle:
// a long streak side-on, a round disc head-on, foreshortened in between. There
// is no surface and no mesh -- only a signed-distance field sampled per pixel --
// so a grazing viewing angle stays a clean capsule instead of a flat sliver.
//
// All maths is in the node's MODEL space (see laser.vert). The eye of whatever
// camera is drawing this pass comes from p3d_ViewMatrixInverse (column 3, its
// world position), brought into model space with p3d_ModelMatrixInverse -- so
// the bolt renders correctly in the main view, the mirrors and the reflection
// alike, with no per-pass uniforms.

uniform mat4 p3d_ModelViewProjectionMatrix;   // model -> clip
uniform mat4 p3d_ModelMatrixInverse;          // world -> model
uniform mat4 p3d_ViewMatrixInverse;           // view  -> world (column 3 = eye)

uniform vec3  uA;           // core segment start, model space
uniform vec3  uB;           // core segment end,   model space
uniform float uCoreRadius;  // white-hot core radius (model units)
uniform float uGlowRadius;  // soft halo falloff radius (model units)
uniform vec3  uColor;       // halo tint (red / green / blue)

in vec3 vModelPos;
out vec4 fragColor;

// Closest distance between the view ray (ro + t*rd, t >= 0, |rd| = 1) and the
// segment [a, b]. Also returns the closest point ON THE RAY, used for depth.
// Line-line closest approach, then clamp to the segment's end caps (that clamp
// is what turns an infinite-cylinder field into a capsule).
float rayToSegment(vec3 ro, vec3 rd, vec3 a, vec3 b, out vec3 pRay) {
    vec3 v = b - a;
    vec3 w = ro - a;
    float B = dot(rd, v);
    float C = dot(v, v);
    float D = dot(rd, w);
    float E = dot(v, w);
    float denom = C - B * B;            // |v|^2 - dot(rd,v)^2, >= 0

    float s = (denom > 1e-6) ? (E - B * D) / denom : 0.0;
    s = clamp(s, 0.0, 1.0);

    vec3 pSeg = a + s * v;
    float t = max(dot(pSeg - ro, rd), 0.0);   // reproject onto the ray, t >= 0
    pRay = ro + t * rd;
    return length(pRay - pSeg);
}

void main() {
    vec3 eye = (p3d_ModelMatrixInverse * p3d_ViewMatrixInverse[3]).xyz;
    vec3 rd = normalize(vModelPos - eye);

    vec3 pRay;
    float d = rayToSegment(eye, rd, uA, uB, pRay);

    // White-hot solid core + soft coloured halo (gaussian falloff).
    float core = 1.0 - smoothstep(0.0, uCoreRadius, d);
    float glow = exp(-(d * d) / (uGlowRadius * uGlowRadius));
    vec3 col = uColor * glow + vec3(1.0) * core;

    if (max(col.r, max(col.g, col.b)) < 0.004) discard;

    // Depth of the ray point nearest the core, so OPAQUE geometry occludes the
    // bolt correctly. Depth WRITE is disabled from Python (additive glow), so
    // this value only feeds the depth TEST.
    vec4 clip = p3d_ModelViewProjectionMatrix * vec4(pRay, 1.0);
    gl_FragDepth = 0.5 * (clip.z / clip.w) + 0.5;

    // Additive blend (ONE, ONE) is set from Python: rgb is the light deposited,
    // so bolts are order-independent w.r.t. each other and translucent geometry.
    fragColor = vec4(col, 1.0);
}
