"""LevelFrame: the chart of a WorldBuilder level file placed in the world."""

import numpy as np
import pytest
from world_builder import parse_world

from space_flight.scenes.level_frame import LevelFrame
from space_flight.scenes.scenes import SceneThreePlanets
from space_flight.utils import rotation_matrix_coefficients


@pytest.fixture(scope="module")
def frame() -> LevelFrame:
    return SceneThreePlanets.level_frame()


def test_the_reference_point_is_on_the_planets_sea_level(frame):
    reference = frame.position(0, 0, 0)
    assert np.linalg.norm(reference - frame.centre) == pytest.approx(frame.radius)
    assert frame.position(0, 0, 250) == pytest.approx(reference + 250 * frame.up)


def test_the_planet_may_be_anywhere():
    spec = parse_world(SceneThreePlanets.WORLD_PATH).bodies[0].spec
    shifted = LevelFrame(spec, centre=(1e6, -2e6, 3e6))
    base = LevelFrame(spec, centre=(0, 0, 0))
    assert shifted.position(300, 400, 50) == pytest.approx(
        base.position(300, 400, 50) + [1e6, -2e6, 3e6]
    )
    assert shifted.up_at(shifted.position(300, 400, 50)) == pytest.approx(
        base.up_at(base.position(300, 400, 50))
    )


def test_the_frame_is_made_of_the_planets_body():
    """Radius and chart origin come from the planet, the centre from where the
    world file puts the body: another body, another chart."""
    world = parse_world(SceneThreePlanets.WORLD_PATH)
    planet, moon, _ = world.bodies
    for body in (planet, moon):
        frame = LevelFrame.of(body)
        assert frame.radius == body.spec.radius
        assert frame.centre == pytest.approx(body.position)
        reference = frame.position(0, 0, 0)
        assert np.linalg.norm(reference - frame.centre) == pytest.approx(
            body.spec.radius
        )
    # The moon is another sphere in another place: the same chart position
    # is not the same world position
    assert not np.allclose(
        LevelFrame.of(planet).position(100, 200, 0),
        LevelFrame.of(moon).position(100, 200, 0),
    )


def test_axes_are_orthonormal(frame):
    axes = np.array([frame.east, frame.north, frame.up])
    assert axes @ axes.T == pytest.approx(np.eye(3))


def test_chart_distances_follow_the_surface(frame):
    # 10 km along the chart is 10 km of arc: the point is on the sphere
    point = frame.position(6000, 8000, 0)
    assert np.linalg.norm(point - frame.centre) == pytest.approx(frame.radius)
    angle = np.arccos(frame.up_at(point) @ frame.up)
    assert angle * frame.radius == pytest.approx(10_000, rel=1e-6)
    # and it lies toward north-east
    assert (point @ frame.north) > 0 and (point @ frame.east) > 0


def test_altitude_is_along_the_local_vertical(frame):
    low, high = frame.position(3000, 2000, 0), frame.position(3000, 2000, 1200)
    assert np.linalg.norm(high - low) == pytest.approx(1200)
    assert (high - low) / 1200 == pytest.approx(frame.up_at(low))


def test_orientation_is_level_and_faces_the_target(frame):
    start = frame.position(0, -4000, 1300)
    quat = frame.orientation(start, frame.position(0, -3000, 1300))
    r = np.array(rotation_matrix_coefficients(*quat)).reshape(3, 3)
    right, forward, up = r[:, 0], r[:, 1], r[:, 2]
    assert up == pytest.approx(frame.up_at(start))
    assert forward @ up == pytest.approx(0, abs=1e-9)
    assert np.cross(right, forward) == pytest.approx(up)
    # chart north at the start point
    ahead = frame.position(0, -3999, 1300) - start
    assert forward @ ahead > 0
    assert forward @ frame.east == pytest.approx(0, abs=1e-3)
