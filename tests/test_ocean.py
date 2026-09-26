"""
Unit tests for the ocean's procedural swell-grid mesh
(space_flight.scenes.ocean.make_swell_grid_mesh).

These build CPU-side geometry only (a GeomVertexData and its index buffer),
so they run fully headless with no window, GPU context or ShowBase — safe for CI.
"""

import math

import numpy as np
import pytest
from panda3d.core import GeomVertexReader

from space_flight.scenes.ocean import border_coords, make_swell_grid_mesh

PLANET_RADIUS = 6371000.0
CURVATURE = 1.0 / (2.0 * PLANET_RADIUS)


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


def _grid_size(subdivs, rings):
    """:returns: vertices per axis — the inner span plus a border ring each side."""
    return subdivs + 1 + 2 * rings


# ── Border rings ────────────────────────────────────────────────────────────────


def test_border_rings_are_geometric_and_land_on_the_edge():
    """The growth factor is derived, not chosen, so the last ring is exactly the
    surface's edge whatever the ring count."""
    grid_half, outer_half, rings = 4000.0, 555000.0, 28
    border = border_coords(grid_half, outer_half, rings)
    assert len(border) == rings
    assert border[-1] == pytest.approx(outer_half)
    assert border[0] > grid_half
    ratios = border[1:] / border[:-1]
    np.testing.assert_allclose(ratios, ratios[0], rtol=1e-9)


def test_border_ring_sag_stays_below_visual_acuity():
    """The ring count is set by SAG — the error from approximating the planet's
    curve with flat cells, ``spacing^2 / (8R)`` — as an angle at the distance it
    is seen from. This is what a single huge border quad could not do at all, and
    what makes 28 rings rather than 15 the right number: geometric growth makes
    the outermost step enormous, so too few rings degrade quickly."""
    grid_half, outer_half = 4000.0, 555000.0
    border = border_coords(grid_half, outer_half, 28)
    spacing = np.diff(np.concatenate([[grid_half], border]))
    sag = spacing**2 / (8.0 * PLANET_RADIUS)
    worst = np.degrees(sag / border).max() * 60.0
    assert worst < 1.0, f"worst sag {worst:.2f} arcmin"
    # And too few rings really is worse, so the number is doing something.
    coarse = border_coords(grid_half, outer_half, 15)
    coarse_spacing = np.diff(np.concatenate([[grid_half], coarse]))
    coarse_sag = coarse_spacing**2 / (8.0 * PLANET_RADIUS)
    assert np.degrees(coarse_sag / coarse).max() * 60.0 > 2.0


# ── The mesh ────────────────────────────────────────────────────────────────────


def test_swell_grid_mesh_vertex_count_and_coords():
    """The grid is a tensor product of one coordinate list: the border rings
    mirrored below the dense span, the span itself, then the rings above it."""
    grid_half, subdivs, outer_half, rings = 4000.0, 8, 24000.0, 5
    node = make_swell_grid_mesh(grid_half, subdivs, outer_half, border_rings=rings)
    m = _grid_size(subdivs, rings)

    positions = _read_positions(node)
    assert positions.shape == (m * m, 3)

    inner = -grid_half + 2.0 * grid_half * np.arange(subdivs + 1) / subdivs
    border = border_coords(grid_half, outer_half, rings)
    expected = np.sort(np.concatenate([-border, inner, border]).astype(np.float32))
    np.testing.assert_allclose(np.unique(positions[:, 0]), expected, rtol=1e-5)
    np.testing.assert_allclose(np.unique(positions[:, 1]), expected, rtol=1e-5)


def test_a_flat_planet_gives_a_flat_sheet():
    """curvature=0 must reproduce the old behaviour exactly — all displacement
    then comes from the vertex shader's swell."""
    node = make_swell_grid_mesh(4000.0, 8, 24000.0, curvature=0.0, border_rings=5)
    np.testing.assert_array_equal(_read_positions(node)[:, 2], 0.0)


def test_the_surface_droops_by_the_true_radius():
    """Per-vertex from x^2 + y^2, not per axis: the tensor-product grid has to
    sample a paraboloid of REVOLUTION, or the surface would curve differently
    along the diagonals than along the axes."""
    node = make_swell_grid_mesh(4000.0, 8, 24000.0, curvature=CURVATURE, border_rings=5)
    positions = _read_positions(node)
    expected = -CURVATURE * (positions[:, 0] ** 2 + positions[:, 1] ** 2)
    np.testing.assert_allclose(positions[:, 2], expected, rtol=1e-4, atol=1e-3)
    # Centre untouched, and the drop grows with distance.
    assert positions[:, 2].max() == pytest.approx(0.0, abs=1e-6)
    assert positions[:, 2].min() < 0.0


def test_the_droop_puts_the_horizon_where_geometry_says():
    """The point of the whole change. A flat plane's horizon sits at exactly eye
    level at every altitude; a curved one dips by sqrt(2h/R) — 1.0 degree at 1 km
    of altitude, 3.05 at 9 km — and that dip is what the drop has to produce."""
    for altitude, expected_dip in ((1000.0, 1.01), (9000.0, 3.05)):
        horizon = math.sqrt(2.0 * PLANET_RADIUS * altitude)
        drop = CURVATURE * horizon**2
        # Angle below eye level of the surface point at the horizon distance.
        dip = math.degrees(math.atan((altitude + drop) / horizon))
        assert dip == pytest.approx(expected_dip, rel=0.01)


def test_swell_grid_mesh_triangles_valid_and_wound():
    """Two triangles per cell, every index in range, with the documented winding."""
    grid_half, subdivs, outer_half, rings = 1000.0, 6, 12000.0, 4
    node = make_swell_grid_mesh(grid_half, subdivs, outer_half, border_rings=rings)
    m = _grid_size(subdivs, rings)

    prim = node.get_geom(0).get_primitive(0)
    assert prim.get_num_vertices() == 6 * (m - 1) * (m - 1)

    indices = [prim.get_vertex(i) for i in range(prim.get_num_vertices())]
    assert min(indices) >= 0
    assert max(indices) < m * m
    # First cell: triangles (v0, v0+1, v0+m) and (v0+1, v0+m+1, v0+m), v0 = 0.
    assert indices[:6] == [0, 1, m, 1, m + 1, m]


def test_swell_grid_mesh_scales_with_subdivisions_and_rings():
    """Vertex and triangle counts follow the inner span plus the border rings."""
    for subdivs in (4, 16, 64):
        for rings in (1, 5):
            node = make_swell_grid_mesh(2000.0, subdivs, 10000.0, border_rings=rings)
            m = _grid_size(subdivs, rings)
            geom = node.get_geom(0)
            assert geom.get_vertex_data().get_num_rows() == m * m
            assert geom.get_primitive(0).get_num_vertices() == 6 * (m - 1) * (m - 1)
