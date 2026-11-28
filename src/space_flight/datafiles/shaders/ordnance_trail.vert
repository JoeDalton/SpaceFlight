#version 140
// Ordnance engine trail (fx/ordnance_trail.py): a ribbon through the ordnance's
// past positions, expanded across its direction in view space (so it faces
// whatever camera draws the pass). The CPU writes each point's direction (a
// point ahead of it toward the head, always the same way round: a direction
// that flipped would swap the ribbon's sides and twist it), side, half-width
// and alpha (they follow its age).

in vec4 p3d_Vertex;  // the point, relative to the trail's node
in vec3 other;       // a point ahead of this one along the trail, same frame
in vec3 ribbon;      // (side +-1, half-width in metres, alpha)

uniform mat4 p3d_ModelViewMatrix;
uniform mat4 p3d_ProjectionMatrix;

out float vSide;      // -1 .. 1 across the ribbon
out float vAlpha;
out float vDistance;  // from the camera, metres (the clouds in front)

void main() {
    vec4 p = p3d_ModelViewMatrix * p3d_Vertex;
    vec3 q = (p3d_ModelViewMatrix * vec4(other, 1.0)).xyz;
    vec2 along = q.xy - p.xy;
    // Seen end-on (or no direction yet): any across direction will do
    vec2 perp = length(along) > 1e-6 ? normalize(vec2(-along.y, along.x))
                                     : vec2(1.0, 0.0);
    vDistance = length(p.xyz);
    p.xy += perp * ribbon.x * ribbon.y;
    gl_Position = p3d_ProjectionMatrix * p;
    vSide = ribbon.x;
    vAlpha = ribbon.z;
}
