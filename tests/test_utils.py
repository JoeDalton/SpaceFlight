import numpy as np
import pytest
import quaternion

from space_flight.utils import (
    build_axis_billboard_quat,
    build_orthogonal_basis,
    compute_next_power_of_2,
    cross3,
    low_pass_filter_first_order,
    magnitude,
    normalize,
    rotate_single_vector,
    rotation_matrix_coefficients,
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


@pytest.mark.parametrize(
    "quat, vector",
    [
        # Identity
        (np.quaternion(1, 0, 0, 0), np.array([1.0, 2.0, 3.0])),
        # 90 degrees around each axis
        (
            np.quaternion(np.cos(np.pi / 4), np.sin(np.pi / 4), 0, 0),
            np.array([0.0, 1.0, 0.0]),
        ),
        (
            np.quaternion(np.cos(np.pi / 4), 0, np.sin(np.pi / 4), 0),
            np.array([1.0, 0.0, 0.0]),
        ),
        (
            np.quaternion(np.cos(np.pi / 4), 0, 0, np.sin(np.pi / 4)),
            np.array([1.0, 0.0, 0.0]),
        ),
        # 180 degrees around an arbitrary axis
        (
            np.quaternion(0, 1, 2, 3) / np.sqrt(14),
            np.array([-1.5, 4.0, 2.0]),
        ),
        # A non-axis-aligned rotation
        (
            quaternion.from_euler_angles(0.3, 0.5, 0.7),
            np.array([1.0, 2.0, 3.0]),
        ),
        # Vector not axis-aligned, quaternion not normalized to 1 exactly
        (
            quaternion.from_euler_angles(-1.2, 2.4, -0.6),
            np.array([-5.0, 0.25, 7.5]),
        ),
        # Zero vector
        (quaternion.from_euler_angles(0.1, 0.2, 0.3), np.array([0.0, 0.0, 0.0])),
        # Vector already aligned with the rotation axis
        (
            np.quaternion(np.cos(0.4), np.sin(0.4), 0, 0),
            np.array([5.0, 0.0, 0.0]),
        ),
    ],
)
def test_rotate_single_vector_matches_quaternion_rotate_vectors(quat, vector):
    """
    rotate_single_vector must agree with the generic quaternion.rotate_vectors
    for a variety of quaternions and vectors.
    """
    result = rotate_single_vector(quat, vector)
    expected = quaternion.rotate_vectors(quat, vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_rotate_single_vector_matches_quaternion_rotate_vectors_random(seed):
    rng = np.random.default_rng(seed)
    quat = quaternion.from_euler_angles(*rng.uniform(-np.pi, np.pi, size=3))
    vector = rng.uniform(-10, 10, size=3)

    result = rotate_single_vector(quat, vector)
    expected = quaternion.rotate_vectors(quat, vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)


# ---------------------------
# rotation_matrix_coefficients
# ---------------------------


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("norm", [1.0, 0.98, 1.03])  # unit, and drifted off unit
def test_rotation_matrix_matches_rotate_single_vector(seed, norm):
    """
    R @ v equals rotate_single_vector(q, v), including for a quaternion that is
    not exactly unit (the integrated orientation is not renormalized), and Rᵀ
    rotates by the conjugate quaternion.
    """
    rng = np.random.default_rng(seed)
    q_array = rng.normal(size=4)
    q_array *= norm / np.linalg.norm(q_array)
    quat = np.quaternion(*q_array)
    matrix = np.array(rotation_matrix_coefficients(*q_array)).reshape(3, 3)
    vector = rng.uniform(-10, 10, size=3)

    np.testing.assert_allclose(
        matrix @ vector, rotate_single_vector(quat, vector), atol=1e-12
    )
    np.testing.assert_allclose(
        matrix.T @ vector, rotate_single_vector(quat.conjugate(), vector), atol=1e-12
    )


# ---------------------------
# cross3
# ---------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        # Axis-aligned basis vectors
        (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])),
        (np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
        (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])),
        # Parallel vectors (cross product is zero)
        (np.array([2.0, 4.0, 6.0]), np.array([1.0, 2.0, 3.0])),
        # Anti-parallel vectors
        (np.array([1.0, 0.0, 0.0]), np.array([-3.0, 0.0, 0.0])),
        # Arbitrary vectors
        (np.array([1.0, 2.0, 3.0]), np.array([-2.0, 0.5, 4.0])),
        (np.array([-5.0, 7.5, -0.25]), np.array([3.0, -1.0, 2.0])),
        # Zero vector
        (np.array([0.0, 0.0, 0.0]), np.array([1.0, 2.0, 3.0])),
        # A vector crossed with itself
        (np.array([1.5, -2.5, 3.5]), np.array([1.5, -2.5, 3.5])),
    ],
)
def test_cross3_matches_np_cross(a, b):
    """cross3 must agree with np.cross for a variety of vector pairs."""
    result = cross3(a, b)
    expected = np.cross(a, b)
    np.testing.assert_allclose(result, expected, atol=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_cross3_matches_np_cross_random(seed):
    rng = np.random.default_rng(seed)
    a = rng.uniform(-10, 10, size=3)
    b = rng.uniform(-10, 10, size=3)

    result = cross3(a, b)
    expected = np.cross(a, b)
    np.testing.assert_allclose(result, expected, atol=1e-9)


# ---------------------------
# normalize
# ---------------------------


@pytest.mark.parametrize(
    "vector",
    [
        # Already unit length
        np.array([1.0, 0.0, 0.0]),
        # 3D, close to unit length (the common "renormalize after drift" case)
        np.array([0.267, 0.534, -0.802]) * 1.001,
        np.array([0.267, 0.534, -0.802]) * 0.999,
        # 3D, far from unit length
        np.array([0.001, 0.002, -0.0015]),
        np.array([1234.5, -876.2, 45.6]),
        np.array([-1.0, -2.0, -3.0]),
        # 4D (quaternion raw components), close to unit length
        np.array([0.9986, 0.03, -0.02, 0.01]),
        # 4D, far from unit length
        np.array([2.0, 0.5, -0.3, 0.1]),
        # 5D, exercises the generic fallback path
        np.array([1.0, 2.0, -3.0, 4.0, -5.0]),
    ],
)
def test_normalize_matches_np_linalg_norm(vector):
    """normalize must agree with v / np.linalg.norm(v) for vectors near and far
    from unit length, in 3D, 4D (quaternions) and beyond."""
    result = normalize(vector)
    expected = vector / np.linalg.norm(vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)
    np.testing.assert_allclose(np.linalg.norm(result), 1.0, atol=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_normalize_matches_np_linalg_norm_random(seed):
    rng = np.random.default_rng(seed)
    vector = rng.uniform(-10, 10, size=3)

    result = normalize(vector)
    expected = vector / np.linalg.norm(vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)


# ---------------------------
# magnitude
# ---------------------------


@pytest.mark.parametrize(
    "vector",
    [
        # Zero vector
        np.array([0.0, 0.0, 0.0]),
        # Unit length
        np.array([1.0, 0.0, 0.0]),
        # 2D (screen-space direction)
        np.array([0.3, -0.7]),
        np.array([0.0, 0.0]),
        # 3D, near-zero
        np.array([1e-8, -2e-8, 3e-8]),
        # 3D, large
        np.array([1234.5, -876.2, 45.6]),
        # 3D, negative components
        np.array([-1.0, -2.0, -3.0]),
        # 4D (quaternion raw components)
        np.array([0.9986, 0.03, -0.02, 0.01]),
        np.array([2.0, 0.5, -0.3, 0.1]),
        # 5D, exercises the generic fallback path
        np.array([1.0, 2.0, -3.0, 4.0, -5.0]),
    ],
)
def test_magnitude_matches_np_linalg_norm(vector):
    """magnitude must agree with np.linalg.norm for 2D, 3D, 4D (quaternions)
    and larger vectors, zero, near-zero and large."""
    result = magnitude(vector)
    expected = np.linalg.norm(vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)


@pytest.mark.parametrize("seed", range(10))
def test_magnitude_matches_np_linalg_norm_random(seed):
    rng = np.random.default_rng(seed)
    vector = rng.uniform(-10, 10, size=3)

    result = magnitude(vector)
    expected = np.linalg.norm(vector)
    np.testing.assert_allclose(result, expected, atol=1e-9)


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
