import numpy as np
import pytest

from space_flight.utils import (
    build_axis_billboard_quat,
    build_orthogonal_basis,
    compute_next_power_of_2,
    low_pass_filter_first_order,
    rotate_single_vector,
    safe_angle_rad,
    sample_direction_in_cone,
    sample_unit_sphere,
    smooth_step_down,
    smooth_step_up,
)

# ---------------------------
# rotate_single_vector
# ---------------------------


def test_rotate_single_vector_identity():
    q = np.quaternion(1, 0, 0, 0)  # Identity quaternion
    v = np.array([1.0, 2.0, 3.0])

    rotated = rotate_single_vector(q, v)

    np.testing.assert_allclose(rotated, v)


def test_rotate_single_vector_90deg_z():
    # 90° rotation around Z axis
    angle = np.pi / 2
    q = np.quaternion(np.cos(angle / 2), 0, 0, np.sin(angle / 2))
    v = np.array([1.0, 0.0, 0.0])

    rotated = rotate_single_vector(q, v)

    expected = np.array([0.0, 1.0, 0.0])
    np.testing.assert_allclose(rotated, expected, atol=1e-6)


# ---------------------------
# safe_angle_rad
# ---------------------------


@pytest.mark.parametrize(
    "angle, expected",
    [
        (0.0, 0.0),
        (np.pi - 1e-6, np.pi - 1e-6),
        (-np.pi + 1e-6, -np.pi + 1e-6),
        (np.pi, -np.pi),
        (3 * np.pi, -np.pi),
        (-3 * np.pi, -np.pi),
        (4 * np.pi, 0.0),
        (-4 * np.pi, 0.0),
    ],
)
def test_safe_angle_rad(angle, expected):
    result = safe_angle_rad(angle)
    np.testing.assert_allclose(result, expected, atol=1e-8)
    assert -np.pi <= result < np.pi


# ---------------------------
# low_pass_filter_first_order (float)
# ---------------------------


def test_low_pass_filter_dt_zero():
    assert low_pass_filter_first_order(1.0, 0.0, 0.0, 1.0, 1.0) == 1.0


def test_low_pass_filter_float_rise():
    value = 1.0
    previous = 0.0
    dt = 1.0
    rise_time = 1.0
    fall_time = 10.0  # irrelevant

    result = low_pass_filter_first_order(value, previous, dt, rise_time, fall_time)

    alpha = dt / (rise_time + dt)
    expected = previous + (value - previous) * alpha

    np.testing.assert_allclose(result, expected)


def test_low_pass_filter_float_fall():
    value = 0.0
    previous = 1.0
    dt = 1.0
    rise_time = 10.0  # irrelevant
    fall_time = 1.0

    result = low_pass_filter_first_order(value, previous, dt, rise_time, fall_time)

    alpha = dt / (fall_time + dt)
    expected = previous + (value - previous) * alpha

    np.testing.assert_allclose(result, expected)


def test_low_pass_filter_tau_zero():
    result = low_pass_filter_first_order(1.0, 0.0, 1.0, 0.0, 1.0)
    assert result == 1.0


# ---------------------------
# low_pass_filter_first_order (ndarray)
# ---------------------------


def test_low_pass_filter_array_mixed():
    value = np.array([1.0, 0.0])
    previous = np.array([0.0, 1.0])
    dt = 1.0
    rise_time = 1.0
    fall_time = 2.0

    result = low_pass_filter_first_order(value, previous, dt, rise_time, fall_time)

    tau = np.where(value > previous, rise_time, fall_time)
    alpha = dt / (tau + dt)
    expected = previous + (value - previous) * alpha

    np.testing.assert_allclose(result, expected)


def test_low_pass_filter_array_tau_zero():
    value = np.array([1.0, 0.0])
    previous = np.array([0.0, 1.0])
    dt = 1.0
    rise_time = 0.0
    fall_time = 1.0

    result = low_pass_filter_first_order(value, previous, dt, rise_time, fall_time)

    np.testing.assert_allclose(result, value)


# ---------------------------
# smooth_step_down
# ---------------------------


def test_smooth_step_down_center():
    x_step = 0.0
    slope = 10.0

    result = smooth_step_down(0.0, x_step, slope)

    np.testing.assert_allclose(result, 0.5)


def test_smooth_step_down_limits():
    x_step = 0.0
    slope = 10.0

    high = smooth_step_down(10.0, x_step, slope)
    low = smooth_step_down(-10.0, x_step, slope)

    assert high < 0.01
    assert low > 0.99


# ---------------------------
# smooth_step_up
# ---------------------------


def test_smooth_step_up_center():
    x_step = 0.0
    slope = 10.0

    result = smooth_step_up(0.0, x_step, slope)

    np.testing.assert_allclose(result, 0.5)


def test_smooth_step_up_complementarity():
    x = np.linspace(-5, 5, 50)
    x_step = 0.0
    slope = 5.0

    down = smooth_step_down(x, x_step, slope)
    up = smooth_step_up(x, x_step, slope)

    np.testing.assert_allclose(down + up, np.ones_like(x))


# ---------------------------
# sample_unit_sphere
# ---------------------------


def test_sample_unit_sphere_inside_sphere():
    for _ in range(20):
        point = sample_unit_sphere()
        assert np.linalg.norm(point) <= 1.0 + 1e-9


def test_sample_unit_sphere_returns_3d():
    point = sample_unit_sphere()
    assert point.shape == (3,)


def test_sample_unit_sphere_not_always_zero():
    results = [sample_unit_sphere() for _ in range(10)]
    non_zero = [r for r in results if np.linalg.norm(r) > 1e-9]
    assert len(non_zero) > 0


# ---------------------------
# build_orthogonal_basis
# ---------------------------


def test_build_orthogonal_basis_none_input():
    n, t, b = build_orthogonal_basis(None)
    assert n is None and t is None and b is None


def test_build_orthogonal_basis_near_zero_vector_fallback():
    # A non-degenerate small-magnitude vector still produces an orthonormal basis
    n, t, b = build_orthogonal_basis(np.array([0.001, 0.0, 0.0]))
    np.testing.assert_allclose(np.linalg.norm(n), 1.0, atol=1e-6)


def test_build_orthogonal_basis_orthonormality():
    normal = np.array([1.0, 2.0, 3.0])
    n, t, b = build_orthogonal_basis(normal)
    np.testing.assert_allclose(np.linalg.norm(n), 1.0, atol=1e-9)
    np.testing.assert_allclose(np.linalg.norm(t), 1.0, atol=1e-9)
    np.testing.assert_allclose(np.linalg.norm(b), 1.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(n, t), 0.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(n, b), 0.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(t, b), 0.0, atol=1e-9)


def test_build_orthogonal_basis_near_x_axis():
    # Test fallback when normal is close to [1, 0, 0]
    normal = np.array([0.99, 0.1, 0.0])
    n, t, b = build_orthogonal_basis(normal)
    np.testing.assert_allclose(np.linalg.norm(n), 1.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(n, t), 0.0, atol=1e-9)


@pytest.mark.parametrize(
    "axis",
    [
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 1, 0],
    ],
)
def test_build_orthogonal_basis_various_normals(axis):
    n, t, b = build_orthogonal_basis(np.array(axis, dtype=float))
    np.testing.assert_allclose(np.dot(n, t), 0.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(n, b), 0.0, atol=1e-9)
    np.testing.assert_allclose(np.dot(t, b), 0.0, atol=1e-9)


# ---------------------------
# sample_direction_in_cone
# ---------------------------


def test_sample_direction_in_cone_none_normal():
    result = sample_direction_in_cone(
        None, np.array([1, 0, 0]), np.array([0, 0, 1]), 0.5
    )
    np.testing.assert_array_equal(result, np.zeros(3))


def test_sample_direction_in_cone_is_unit_vector():
    normal = np.array([0.0, 0.0, 1.0])
    n, t, b = build_orthogonal_basis(normal)
    direction = sample_direction_in_cone(n, t, b, half_angle_rad=0.3)
    np.testing.assert_allclose(np.linalg.norm(direction), 1.0, atol=1e-9)


def test_sample_direction_in_cone_within_angle():
    normal = np.array([0.0, 0.0, 1.0])
    n, t, b = build_orthogonal_basis(normal)
    half_angle = 0.3
    for _ in range(20):
        direction = sample_direction_in_cone(n, t, b, half_angle_rad=half_angle)
        cos_angle = np.dot(direction, n)
        angle = np.arccos(np.clip(cos_angle, -1, 1))
        assert angle <= half_angle + 1e-9


def test_sample_direction_in_cone_zero_angle_returns_normal():
    normal = np.array([1.0, 0.0, 0.0])
    n, t, b = build_orthogonal_basis(normal)
    direction = sample_direction_in_cone(n, t, b, half_angle_rad=0.0)
    np.testing.assert_allclose(np.abs(np.dot(direction, n)), 1.0, atol=1e-9)


# ---------------------------
# build_axis_billboard_quat
# ---------------------------


def test_build_axis_billboard_quat_returns_quaternion():
    forward = np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 0.0, 1.0])
    quat = build_axis_billboard_quat(forward, up_hint=up)
    assert isinstance(quat, np.quaternion)


def test_build_axis_billboard_quat_unit_quaternion():
    forward = np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 0.0, 1.0])
    quat = build_axis_billboard_quat(forward, up_hint=up)
    norm = np.sqrt(quat.w**2 + quat.x**2 + quat.y**2 + quat.z**2)
    np.testing.assert_allclose(norm, 1.0, atol=1e-9)


def test_build_axis_billboard_quat_near_zero_forward():
    # Near-zero forward falls back to [0, 1, 0]
    forward = np.array([1e-6, 0.0, 0.0])
    up = np.array([0.0, 0.0, 1.0])
    quat = build_axis_billboard_quat(forward, up_hint=up)
    assert isinstance(quat, np.quaternion)


def test_build_axis_billboard_quat_various_directions():
    up = np.array([0.0, 0.0, 1.0])
    for forward in [[1, 0, 0], [0, 1, 0], [1, 1, 0], [-1, 0, 0]]:
        quat = build_axis_billboard_quat(np.array(forward, dtype=float), up_hint=up)
        assert isinstance(quat, np.quaternion)


# ---------------------------
# compute_next_power_of_2
# ---------------------------


@pytest.mark.parametrize(
    "x, expected",
    [
        (1.0, 1),
        (1.5, 2),
        (2.0, 2),
        (3.0, 4),
        (4.0, 4),
        (5.0, 8),
        (7.9, 8),
        (8.0, 8),
        (100.0, 128),
        (0.0, 1),  # max(x, 1) ensures minimum of 1
        (-5.0, 1),
    ],
)
def test_compute_next_power_of_2(x, expected):
    result = compute_next_power_of_2(x)
    assert result == expected
    assert result >= x
    # Verify it is actually a power of 2
    assert result & (result - 1) == 0
