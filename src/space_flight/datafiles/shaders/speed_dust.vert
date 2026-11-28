#version 140
// Speed dust (fx/speed_dust_cloud.py): every mote placed from the distance
// the ship has travelled, in the dust's frame (the ship's). A mote drifts
// back from its spawn depth; once behind the ship it starts again a depth
// ahead, at a new random place across (a hash of its seed and its lap).

in vec4  p3d_Vertex;  // (x, y, z) where the mote starts, dust frame
in vec2  corner;      // billboard corner, one of (+-1, +-1)
in float size;        // the mote's half-size, metres
in float seed;        // the mote's own random seed

uniform mat4  p3d_ModelViewMatrix;
uniform mat4  p3d_ProjectionMatrix;
uniform float uTravel;  // metres flown (kept modulo a whole number of depths)
uniform float uDepth;   // the dust's depth ahead of the ship, metres
uniform float uSpread;  // its half-width across, metres

out vec2 vUV;
out float vDistance; // from the camera, metres (the clouds in front)

float hash(float n) {
    return fract(sin(n) * 43758.5453);
}

void main() {
    float y = p3d_Vertex.y - uTravel;
    float lap = floor(y / uDepth);
    y -= lap * uDepth;
    vec2 across = p3d_Vertex.xz;
    if (lap != 0.0) {
        across = (vec2(hash(seed * 12.9898 + lap * 78.233),
                       hash(seed * 39.3468 + lap * 11.135)) * 2.0 - 1.0)
                 * uSpread;
    }
    vec4 centre = p3d_ModelViewMatrix * vec4(across.x, y, across.y, 1.0);
    // Facing the eye: the corner offset in view space
    centre.xy += corner * size;
    vDistance = length(centre.xyz);
    gl_Position = p3d_ProjectionMatrix * centre;
    vUV = corner * 0.5 + 0.5;
}
