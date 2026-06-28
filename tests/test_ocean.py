"""
Unit tests for the ocean's procedural swell-grid mesh
(``space_flight.scenes.ocean.make_swell_grid_mesh``).

These build CPU-side geometry only (a ``GeomVertexData`` and its index buffer),
so they run fully headless with no window, GPU context or ShowBase — safe for CI.
"""

import numpy as np
from panda3d.core import GeomVertexReader

from space_flight.scenes.ocean import make_swell_grid_mesh


def _read_positions(node):
    """
    Read back every vertex position of a single-Geom node.

    :param node: the GeomNode returned by make_swell_grid_mesh
    :return: an (n, 3) float array of vertex positions
    """
    vdata = node.get_geom(0).get_vertex_data()
    reader = GeomVertexReader(vdata, "vertex")
    positions = []
    while not reader.is_at_end():
        positions.append(tuple(reader.get_data3()))
    return np.array(positions)


def test_swell_grid_mesh_vertex_count_and_coords():
    """The grid is (subdivs + 3)^2 flat vertices on the expected coordinate lines."""
    grid_half, subdivs, outer_half = 4000.0, 8, 24000.0
    node = make_swell_grid_mesh(grid_half, subdivs, outer_half)
    m = subdivs + 3

    positions = _read_positions(node)
    assert positions.shape == (m * m, 3)

    # Flat sheet — all displacement is added later in the vertex shader.
    np.testing.assert_array_equal(positions[:, 2], 0.0)

    # Per-axis coords: outer border, the uniform inner span, then the far border.
    inner = -grid_half + 2.0 * grid_half * np.arange(subdivs + 1) / subdivs
    expected = np.sort(
        np.concatenate([[-outer_half], inner, [outer_half]]).astype(np.float32)
    )
    np.testing.assert_allclose(np.unique(positions[:, 0]), expected, atol=1e-3)
    np.testing.assert_allclose(np.unique(positions[:, 1]), expected, atol=1e-3)


def test_swell_grid_mesh_triangles_valid_and_wound():
    """Two triangles per cell, every index in range, with the documented winding."""
    grid_half, subdivs, outer_half = 1000.0, 6, 12000.0
    node = make_swell_grid_mesh(grid_half, subdivs, outer_half)
    m = subdivs + 3

    prim = node.get_geom(0).get_primitive(0)
    assert prim.get_num_vertices() == 6 * (m - 1) * (m - 1)

    indices = [prim.get_vertex(i) for i in range(prim.get_num_vertices())]
    assert min(indices) >= 0
    assert max(indices) < m * m
    # First cell: triangles (v0, v0+1, v0+m) and (v0+1, v0+m+1, v0+m), v0 = 0.
    assert indices[:6] == [0, 1, m, 1, m + 1, m]


def test_swell_grid_mesh_scales_with_subdivisions():
    """Vertex and triangle counts follow (subdivs + 3)."""
    for subdivs in (4, 16, 64):
        node = make_swell_grid_mesh(2000.0, subdivs, 10000.0)
        m = subdivs + 3
        geom = node.get_geom(0)
        assert geom.get_vertex_data().get_num_rows() == m * m
        assert geom.get_primitive(0).get_num_vertices() == 6 * (m - 1) * (m - 1)
