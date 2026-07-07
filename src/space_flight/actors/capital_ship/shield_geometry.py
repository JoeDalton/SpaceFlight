"""
Procedural mesh helpers for shield geometry.

A shield's visible bubble must coincide with its collision solid. For the tube
shape there is no stock model, so :func:`make_capsule` builds a capsule mesh
(a cylinder capped by two hemispheres) whose surface matches a ``CollisionTube``
with the same end centres and radius.
"""

import numpy as np
from panda3d.core import (
    Geom,
    GeomNode,
    GeomTriangles,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    NodePath,
)


def make_capsule(
    point_a,
    point_b,
    radius: float,
    num_segments: int = 24,
    num_rings: int = 8,
) -> NodePath:
    """
    Build a capsule mesh matching a ``CollisionTube``.

    The capsule is a cylinder between ``point_a`` and ``point_b`` capped by a
    hemisphere of ``radius`` at each end, i.e. the exact surface of the tube whose
    hemisphere centres are ``point_a`` and ``point_b``.

    :param point_a: Centre of the first end hemisphere (x, y, z)
    :param point_b: Centre of the second end hemisphere (x, y, z)
    :param radius: The capsule radius
    :param num_segments: Longitudinal subdivisions (around the axis)
    :param num_rings: Latitude subdivisions per hemisphere
    :return: A NodePath holding the generated capsule geometry
    """
    a = np.asarray(point_a, dtype=float)
    b = np.asarray(point_b, dtype=float)
    axis = b - a
    length = np.linalg.norm(axis)
    axis_dir = axis / length if length > 1e-9 else np.array([0.0, 0.0, 1.0])

    # Two unit vectors perpendicular to the axis, to sweep each ring around it
    reference = (
        np.array([1.0, 0.0, 0.0])
        if abs(axis_dir[0]) < 0.9
        else np.array([0.0, 1.0, 0.0])
    )
    u = np.cross(axis_dir, reference)
    u /= np.linalg.norm(u)
    v = np.cross(axis_dir, u)

    vdata = GeomVertexData("capsule", GeomVertexFormat.getV3n3(), Geom.UHStatic)
    vertex_writer = GeomVertexWriter(vdata, "vertex")
    normal_writer = GeomVertexWriter(vdata, "normal")

    # Latitude rings run from the bottom pole (phi = -pi/2) to the top pole
    # (phi = +pi/2). The lower half belongs to the hemisphere centred at a, the
    # upper half to the one centred at b; the jump of centre at the equator is
    # exactly the cylinder body.
    total_latitude = 2 * num_rings
    rings = []
    index = 0
    for i in range(total_latitude + 1):
        phi = -np.pi / 2.0 + np.pi * (i / total_latitude)
        center = a if phi <= 0.0 else b
        ring = []
        for j in range(num_segments + 1):
            theta = 2.0 * np.pi * (j / num_segments)
            radial = np.cos(theta) * u + np.sin(theta) * v
            outward = np.cos(phi) * radial + np.sin(phi) * axis_dir
            position = center + radius * outward
            vertex_writer.addData3(*position)
            normal_writer.addData3(*outward)
            ring.append(index)
            index += 1
        rings.append(ring)

    triangles = GeomTriangles(Geom.UHStatic)
    for i in range(total_latitude):
        lower = rings[i]
        upper = rings[i + 1]
        for j in range(num_segments):
            triangles.addVertices(lower[j], upper[j], lower[j + 1])
            triangles.addVertices(lower[j + 1], upper[j], upper[j + 1])

    geom = Geom(vdata)
    geom.addPrimitive(triangles)
    node = GeomNode("capsule")
    node.addGeom(geom)
    return NodePath(node)
