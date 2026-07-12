import logging

import numpy as np

LOGGER = logging.getLogger(__name__)


class Integrator:
    def __init__(self, game, max_state_size: int = 2000):
        """
        Initializes the integrator with pre-allocated state vectors.

        All arrays are allocated once at construction and reused across frames.
        step() zeroes only the live portion in-place instead of allocating new arrays.

        :param game: The game object, used to retrieve the current time step
        :param max_state_size: Upper bound on the total number of state variables
        :param debug: When True, step() asserts that the registered variable count
            matches the previous frame.  This assertion fires on actor spawn/death;
            use only in fixed-actor-count scenarios such as unit tests.
        """
        self.game = game
        self.x = np.zeros(max_state_size)
        self.x_new = np.zeros(max_state_size)
        self.x_dot = np.zeros(max_state_size)
        self.x_dot_previous = np.zeros(max_state_size)
        self.dt_previous = None
        self.next_idx = 0
        self.max_state_size = max_state_size

    def set_state_variables(
        self,
        partial_x: np.ndarray,
        partial_x_dot: np.ndarray,
        partial_x_dot_previous: np.ndarray,
    ):
        """
        Sets consecutive state variables and returns the index at which they
        should be retrieved after the next step.

        All three arguments must be numpy vectors of the same length.

        :param partial_x: Current state values
        :param partial_x_dot: Current state derivative
        :param partial_x_dot_previous: State derivative from the previous step.
            Pass the same value as partial_x_dot on the first registration.
        :return: Start index for use with get_state_variables in the same frame
        """
        # Check input sizes
        n_new_var = len(partial_x)
        assert n_new_var == len(partial_x_dot)
        assert n_new_var == len(partial_x_dot_previous)

        # Check that there is enough room left to add those new variables
        current_idx = self.next_idx
        if current_idx + n_new_var > self.max_state_size:
            raise RuntimeError(
                f"Cannot register {n_new_var} variables at index {current_idx}: "
                f"max_state_size is {self.max_state_size}"
            )

        # Update next_idx
        self.next_idx += n_new_var

        # Set variables
        self.x[current_idx : self.next_idx] = partial_x
        self.x_dot[current_idx : self.next_idx] = partial_x_dot
        self.x_dot_previous[current_idx : self.next_idx] = partial_x_dot_previous

        # Return retrieving index
        return current_idx

    def get_state_variables(self, first_idx: int, n_var: int) -> np.ndarray:
        """
        Returns the integrated state variables produced by the last step.

        :param first_idx: The start index returned by set_state_variables
        :param n_var: Number of variables to retrieve
        :return: Integrated state as a numpy vector of length n_var
        """
        return self.x_new[first_idx : first_idx + n_var].copy()

    def step(self):
        """
        A 2nd order Adams-Bashforth integrator.
        For the first step, a 1st order forward Euler (=AB1) is used.

        Integration is computed in-place on the live slice [:next_idx] only.
        x and x_dot are zeroed in-place after the step; x_dot_previous
        is left untouched because every actor overwrites it during re-registration
        before the next step reads it.

        For any new state variable at runtime, set x_dot_previous equal to x_dot
        to get an AB1 initialisation of that variable.
        """
        # Get the timespan of the current step
        dt = self.game.game_time.get_time_step()

        if (self.dt_previous is None) or (self.dt_previous == 0.0):
            self.x_new[: self.next_idx] = (
                self.x[: self.next_idx] + dt * self.x_dot[: self.next_idx]
            )
        else:
            self.x_new[: self.next_idx] = self.x[
                : self.next_idx
            ] + 0.5 * dt / self.dt_previous * (
                (2 * self.dt_previous + dt) * self.x_dot[: self.next_idx]
                - dt * self.x_dot_previous[: self.next_idx]
            )

        # Prepare the next step by wiping the inputs
        # We don't set x_dot_previous to x_dot because the number of state variables
        # can change from one step to the other (objects appearing/disappearing)
        self.dt_previous = dt
        # Zero the live portion in-place
        self.x[: self.next_idx] = 0.0
        self.x_dot[: self.next_idx] = 0.0
        self.x_dot_previous[: self.next_idx] = 0.0
        self.next_idx = 0

    def first_order_euler_step(
        self, state_derivative: np.ndarray, state: np.ndarray
    ) -> np.ndarray:
        """
        A simple explicit first order integrator for low-precision movements.

        :param state_derivative: The state vector's derivative
        :param state: The state vector
        :return: The state vector one step further
        """
        # Get the timespan of the current step
        dt = self.game.game_time.get_time_step()
        return state + state_derivative * dt

    def clean(self):
        """
        Cleans the integrator object.
        """
        self.game = None
        self.x = None
        self.x_new = None
        self.x_dot = None
        self.x_dot_previous = None
        self.dt_previous = None
        self.next_idx = None
        self.max_state_size = None
