"""
Unit tests for the procedural capsule mesh used by tubular shields.
"""

import pytest

from space_flight.actors.capital_ship.shield_model import make_capsule


def test_capsule_bounds_match_tube_extent():
    """
    A capsule between two points spans, on the axis, from point_a - radius to
    point_b + radius, and by the radius on the perpendicular axes.
    """
    node = make_capsule(point_a=[0.0, 0.0, -5.0], point_b=[0.0, 0.0, 5.0], radius=3.0)

    low, high = node.getTightBounds()
    assert low.x == pytest.approx(-3.0, abs=1e-3)
    assert high.x == pytest.approx(3.0, abs=1e-3)
    assert low.z == pytest.approx(-8.0, abs=1e-3)  # -5 - 3
    assert high.z == pytest.approx(8.0, abs=1e-3)  # 5 + 3


def test_capsule_off_axis_orientation():
    """
    A capsule laid along the Y axis stretches on Y and is bounded by the radius
    on X and Z.
    """
    node = make_capsule(point_a=[0.0, -4.0, 0.0], point_b=[0.0, 4.0, 0.0], radius=2.0)

    low, high = node.getTightBounds()
    assert low.y == pytest.approx(-6.0, abs=1e-3)
    assert high.y == pytest.approx(6.0, abs=1e-3)
    assert low.x == pytest.approx(-2.0, abs=1e-3)
    assert high.x == pytest.approx(2.0, abs=1e-3)


def test_degenerate_capsule_is_a_sphere():
    """
    With coincident end points the capsule degenerates to a sphere of the radius.
    """
    node = make_capsule(point_a=[0.0, 0.0, 0.0], point_b=[0.0, 0.0, 0.0], radius=4.0)

    low, high = node.getTightBounds()
    for lo, hi in zip(low, high):
        assert lo == pytest.approx(-4.0, abs=1e-3)
        assert hi == pytest.approx(4.0, abs=1e-3)


def test_capsule_geometry_is_non_empty():
    """
    The generated node actually holds renderable geometry.
    """
    node = make_capsule(point_a=[0.0, 0.0, -1.0], point_b=[0.0, 0.0, 1.0], radius=1.0)

    assert not node.isEmpty()
    assert not node.node().isGeomNode() or node.node().getNumGeoms() > 0
