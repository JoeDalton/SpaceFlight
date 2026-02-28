import numpy as np
import pytest

from space_flight.utils import (
    low_pass_filter_first_order,
    rotate_single_vector,
    safe_angle_rad,
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
