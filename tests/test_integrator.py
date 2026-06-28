import numpy as np
import pytest

from space_flight.game.integrator import Integrator


class MockGameTime:
    """
    Minimal stand-in for GameTimeManager that returns a fixed time step.
    """

    def __init__(self, dt: float = 0.1):
        """
        :param dt: Time step in seconds returned on every call to get_time_step
        """
        self.dt = dt

    def get_time_step(self) -> float:
        """
        :return: The fixed time step set at construction
        """
        return self.dt


class MockGame:
    """
    Minimal stand-in for FlightState that provides only the game_time attribute.
    """

    def __init__(self, dt: float = 0.1):
        """
        :param dt: Time step forwarded to the internal MockGameTime instance
        """
        self.game_time = MockGameTime(dt)


@pytest.fixture
def ig():
    """
    Returns a fresh Integrator with 100-variable capacity and dt=0.1.
    """
    return Integrator(game=MockGame(dt=0.1), max_state_size=100)


@pytest.fixture
def ig_debug():
    """
    Returns a fresh Integrator with debug mode enabled and 100-variable capacity.
    """
    return Integrator(game=MockGame(dt=0.1), max_state_size=100, debug=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _z(n):
    """Return a zero vector of length n."""
    return np.zeros(n)


def _register(integrator, x, x_dot, x_dot_prev=None):
    """Register a single actor and return the start index."""
    if x_dot_prev is None:
        x_dot_prev = x_dot.copy()
    return integrator.set_state_variables(x, x_dot, x_dot_prev)


# ------------------------------------------------------------------
# Initialisation
# ------------------------------------------------------------------


def test_state_arrays_are_zero_on_init(ig):
    """
    All four state arrays must be zero-initialised so no stale values
    affect the first integration step.
    """
    np.testing.assert_array_equal(ig.x, 0)
    np.testing.assert_array_equal(ig.x_dot, 0)
    np.testing.assert_array_equal(ig.x_dot_previous, 0)
    np.testing.assert_array_equal(ig.x_new, 0)


def test_next_idx_is_zero_on_init(ig):
    """
    No variables are registered at construction, so next_idx must be zero.
    """
    assert ig.next_idx == 0


def test_dt_previous_is_none_on_init(ig):
    """
    dt_previous must be None on construction so the first step falls back to
    forward Euler rather than trying to divide by an uninitialised value.
    """
    assert ig.dt_previous is None


# ------------------------------------------------------------------
# set_state_variables
# ------------------------------------------------------------------


def test_set_returns_zero_for_first_registration(ig):
    """
    The first registration must return index 0 so the actor retrieves its
    result from the start of x_new.
    """
    idx = _register(ig, np.array([1.0, 2.0, 3.0]), _z(3))
    assert idx == 0


def test_set_sequential_registrations_return_correct_offsets(ig):
    """
    Each successive registration must start immediately after the previous one
    with no gaps or overlaps.
    """
    idx0 = _register(ig, _z(2), _z(2))
    idx1 = _register(ig, _z(5), _z(5))
    assert idx0 == 0
    assert idx1 == 2


def test_set_writes_values_to_x(ig):
    """
    The values passed as partial_x must appear verbatim in integrator.x at the
    returned slice.
    """
    x = np.array([4.0, 5.0, 6.0])
    idx = _register(ig, x, _z(3))
    np.testing.assert_array_equal(ig.x[idx : idx + 3], x)


def test_set_writes_values_to_x_dot(ig):
    """
    The values passed as partial_x_dot must appear verbatim in integrator.x_dot
    at the returned slice.
    """
    x_dot = np.array([7.0, 8.0])
    idx = ig.set_state_variables(_z(2), x_dot, _z(2))
    np.testing.assert_array_equal(ig.x_dot[idx : idx + 2], x_dot)


def test_set_writes_values_to_x_dot_previous(ig):
    """
    The values passed as partial_x_dot_previous must appear verbatim in
    integrator.x_dot_previous at the returned slice.
    """
    x_dot_prev = np.array([9.0, 10.0])
    idx = ig.set_state_variables(_z(2), _z(2), x_dot_prev)
    np.testing.assert_array_equal(ig.x_dot_previous[idx : idx + 2], x_dot_prev)


def test_set_overflow_raises_runtime_error(ig):
    """
    Registering more variables than max_state_size in total must raise
    RuntimeError before any state is mutated.
    """
    too_big = np.zeros(ig.max_state_size + 1)
    with pytest.raises(RuntimeError):
        ig.set_state_variables(too_big, too_big.copy(), too_big.copy())


def test_set_exact_capacity_does_not_raise(ig):
    """
    Registering exactly max_state_size variables must succeed without raising.
    """
    full = np.zeros(ig.max_state_size)
    ig.set_state_variables(full, full.copy(), full.copy())  # must not raise


def test_set_size_mismatch_raises_assertion(ig):
    """
    Passing arrays of different lengths must raise AssertionError immediately.
    """
    with pytest.raises(AssertionError):
        ig.set_state_variables(np.zeros(3), np.zeros(2), np.zeros(3))


# ------------------------------------------------------------------
# step — forward Euler (first step)
# ------------------------------------------------------------------


def test_first_step_uses_forward_euler(ig):
    """
    When dt_previous is None the integrator must use forward Euler:
    x_new = x + dt * x_dot.
    """
    x = np.array([0.0, 1.0])
    x_dot = np.array([2.0, 3.0])
    idx = _register(ig, x, x_dot)
    ig.step()
    result = ig.get_state_variables(idx, 2)
    np.testing.assert_allclose(result, x + 0.1 * x_dot)


def test_step_sets_dt_previous(ig):
    """
    After the first step, dt_previous must equal the dt used so the next step
    can apply the AB2 formula.
    """
    _register(ig, _z(1), _z(1))
    ig.step()
    assert ig.dt_previous == pytest.approx(0.1)


def test_step_resets_next_idx_to_zero(ig):
    """
    step() must reset next_idx to zero so the next frame's registrations start
    from the beginning of the flat state vector.
    """
    _register(ig, _z(5), _z(5))
    ig.step()
    assert ig.next_idx == 0


# ------------------------------------------------------------------
# step — Adams-Bashforth 2nd order
# ------------------------------------------------------------------


def test_second_step_applies_ab2_formula():
    """
    The second step must apply the AB2 formula.  For known x, x_dot, and
    x_dot_previous, the result must match
    x_new = x + 0.5 * dt/dt_prev * ((2*dt_prev + dt)*x_dot - dt*x_dot_prev).
    """
    dt = 0.1
    ig = Integrator(game=MockGame(dt=dt), max_state_size=10)

    x = np.array([1.0, 2.0])
    x_dot = np.array([3.0, 4.0])
    x_dot_prev = np.array([1.0, 2.0])

    # Frame 1 — Euler, establishes dt_previous
    idx = ig.set_state_variables(x, x_dot, x_dot_prev)
    ig.step()
    x1 = ig.get_state_variables(idx, 2)

    # Frame 2 — AB2 with known derivatives
    x_dot2 = np.array([3.0, 4.0])
    x_dot_prev2 = np.array([1.0, 2.0])
    idx = ig.set_state_variables(x1, x_dot2, x_dot_prev2)
    ig.step()
    x2 = ig.get_state_variables(idx, 2)

    expected = x1 + 0.5 * dt / dt * ((2 * dt + dt) * x_dot2 - dt * x_dot_prev2)
    np.testing.assert_allclose(x2, expected)


def test_ab2_constant_velocity_advances_by_dt():
    """
    For constant velocity v, AB2 must advance position by exactly dt*v regardless
    of dt_previous.
    """
    dt = 0.1
    ig = Integrator(game=MockGame(dt=dt), max_state_size=10)
    v = 5.0

    # Frame 1
    idx = ig.set_state_variables(np.array([0.0]), np.array([v]), np.array([v]))
    ig.step()
    x1 = ig.get_state_variables(idx, 1)

    # Frame 2
    idx = ig.set_state_variables(x1, np.array([v]), np.array([v]))
    ig.step()
    x2 = ig.get_state_variables(idx, 1)

    assert x2[0] == pytest.approx(x1[0] + dt * v)


# ------------------------------------------------------------------
# step — in-place behaviour (no allocation)
# ------------------------------------------------------------------


def test_step_does_not_reallocate_x(ig):
    """
    step() must zero x in-place; the Python object identity of integrator.x
    must be preserved across frames.
    """
    _register(ig, _z(3), _z(3))
    x_before = ig.x
    ig.step()
    assert ig.x is x_before


def test_step_does_not_reallocate_x_dot(ig):
    """
    step() must zero x_dot in-place; the Python object identity of
    integrator.x_dot must be preserved across frames.
    """
    _register(ig, _z(3), _z(3))
    x_dot_before = ig.x_dot
    ig.step()
    assert ig.x_dot is x_dot_before


def test_step_does_not_reallocate_x_new(ig):
    """
    step() must write into x_new in-place; the Python object identity of
    integrator.x_new must be preserved across frames.
    """
    _register(ig, _z(3), _z(3))
    x_new_before = ig.x_new
    ig.step()
    assert ig.x_new is x_new_before


def test_step_zeroes_live_x_portion(ig):
    """
    After step(), the live portion x[:n] must be all zeros so the next
    frame's re-registrations start from a clean slate.
    """
    n = 5
    _register(ig, np.ones(n), np.ones(n))
    ig.step()
    np.testing.assert_array_equal(ig.x[:n], 0)


def test_step_zeroes_live_x_dot_portion(ig):
    """
    After step(), the live portion x_dot[:n] must be all zeros so stale
    derivatives never carry over to the next step.
    """
    n = 5
    _register(ig, np.ones(n), np.ones(n))
    ig.step()
    np.testing.assert_array_equal(ig.x_dot[:n], 0)


def test_step_does_not_touch_x_dot_previous(ig):
    """
    step() must not modify x_dot_previous at all: the region is always
    overwritten by set_state_variables before the next step reads it, so
    zeroing it would be wasted work.
    """
    sentinel = 42.0
    ig.x_dot_previous[50] = sentinel
    _register(ig, _z(3), _z(3))
    ig.step()
    assert ig.x_dot_previous[50] == sentinel


# ------------------------------------------------------------------
# step — only the live portion is integrated
# ------------------------------------------------------------------


def test_step_integrates_only_live_portion(ig):
    """
    Variables beyond next_idx must remain zero in x_new after step(); the
    integration range is [:next_idx], not [:max_state_size].
    """
    n = 4
    _register(ig, np.ones(n), np.ones(n))
    ig.step()
    np.testing.assert_array_equal(ig.x_new[n:], 0)


# ------------------------------------------------------------------
# first_order_euler_step
# ------------------------------------------------------------------


def test_first_order_euler_step_computes_correctly():
    """
    first_order_euler_step must return state + dt * derivative and must not
    modify any of the integrator's flat state arrays.
    """
    ig = Integrator(game=MockGame(dt=0.2), max_state_size=10)
    state = np.array([1.0, 2.0])
    deriv = np.array([3.0, 4.0])
    result = ig.first_order_euler_step(deriv, state)
    np.testing.assert_allclose(result, np.array([1.6, 2.8]))
    # Flat arrays must be untouched
    np.testing.assert_array_equal(ig.x, 0)
    np.testing.assert_array_equal(ig.x_dot, 0)


# ------------------------------------------------------------------
# clean
# ------------------------------------------------------------------


def test_clean_nulls_all_references(ig):
    """
    clean() must set every array and scalar attribute to None so that
    reference cycles are broken and memory can be reclaimed.
    """
    ig.clean()
    assert ig.x is None
    assert ig.x_new is None
    assert ig.x_dot is None
    assert ig.x_dot_previous is None
    assert ig.game is None
    assert ig.dt_previous is None
