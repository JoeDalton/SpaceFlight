"""
Tests for the procedural radial menu overlay and its ring-sector geometry.
"""

import math

import pytest
from panda3d.core import GeomVertexReader

from space_flight.menus.radial_menu_state import (
    _INNER_RADIUS,
    _OUTER_RADIUS,
    _SELECTED_SLICE_COLOR,
    _SELECTED_SLICE_SCALE,
    _SLICE_COLOR,
    RadialMenuVisual,
)
from space_flight.ui.utils import make_ring_sector_geom

LABELS = ["a", "b", "c", "d", "e"]


@pytest.fixture
def visual(spaceflight_app):
    v = RadialMenuVisual(spaceflight_app, LABELS)
    yield v
    if v.root is not None:
        v.destroy()


def test_ring_sector_geom_vertices_stay_between_the_radii():
    """
    Every vertex of a ring sector must lie on the inner or outer radius, in
    the XZ plane, within the requested angular span.
    """
    geom = make_ring_sector_geom(0.3, 0.7, 0.2, 1.0, n_steps=4)
    reader = GeomVertexReader(geom.getVertexData(), "vertex")
    points = []
    while not reader.isAtEnd():
        points.append(reader.getData3())
    assert len(points) == 2 * (4 + 1)
    for p in points:
        assert p.y == pytest.approx(0.0)
        assert math.hypot(p.x, p.z) == pytest.approx(0.3) or math.hypot(
            p.x, p.z
        ) == pytest.approx(0.7)
        assert 0.2 - 1e-6 <= math.atan2(p.z, p.x) <= 1.0 + 1e-6
    assert geom.getNumPrimitives() == 1


def radii(slice_np):
    """
    :return: (min, max) vertex distance from the menu centre of a slice
    """
    reader = GeomVertexReader(slice_np.node().getGeom(0).getVertexData(), "vertex")
    distances = []
    while not reader.isAtEnd():
        p = reader.getData3()
        distances.append(math.hypot(p.x, p.z))
    return min(distances), max(distances)


def test_one_slice_and_label_per_entry(visual):
    assert len(visual.slices) == len(LABELS)
    assert len(visual.labels) == len(LABELS)


def test_slices_are_separated_and_leave_the_centre_empty(visual):
    """
    Slice bounds must stay inside the ring, so the centre is empty.
    """
    for slice_np in visual.slices:
        lo, hi = slice_np.getTightBounds()
        corners = [(x, z) for x in (lo.x, hi.x) for z in (lo.z, hi.z)]
        assert max(math.hypot(x, z) for x, z in corners) >= _INNER_RADIUS
        assert max(abs(c) for c in (lo.x, hi.x, lo.z, hi.z)) <= _OUTER_RADIUS + 1e-6
    # Slice 0 is centred on the top: it must straddle x = 0 above the centre
    lo, hi = visual.slices[0].getTightBounds()
    assert lo.x < 0 < hi.x
    assert lo.z > 0


def test_selected_slice_is_lit_bigger_and_in_front(visual):
    visual.update(2)
    selected = visual.slices[2]
    assert radii(selected) == pytest.approx(
        (
            _INNER_RADIUS / _SELECTED_SLICE_SCALE,
            _OUTER_RADIUS * _SELECTED_SLICE_SCALE,
        )
    )
    assert tuple(selected.getColor()) == pytest.approx(_SELECTED_SLICE_COLOR, abs=1e-2)
    assert selected.getBinDrawOrder() == 1
    for i, other in enumerate(visual.slices):
        if i == 2:
            continue
        assert radii(other) == pytest.approx((_INNER_RADIUS, _OUTER_RADIUS))
        assert tuple(other.getColor()) == pytest.approx(_SLICE_COLOR, abs=1e-2)
        assert other.getBinDrawOrder() == 0


def test_update_none_resets_every_slice(visual):
    visual.update(1)
    visual.update(None)
    for slice_np in visual.slices:
        assert radii(slice_np) == pytest.approx((_INNER_RADIUS, _OUTER_RADIUS))
        assert slice_np.getBinDrawOrder() == 0


def test_destroy_removes_the_overlay(visual, spaceflight_app):
    root = visual.root
    visual.destroy()
    assert root.isEmpty()
    assert visual.root is None
