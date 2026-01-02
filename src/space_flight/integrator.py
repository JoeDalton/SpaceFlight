import numpy as np
from direct.showbase.ShowBase import ShowBase


class Integrator:
    def __init__(self, app: ShowBase, max_state_size: int = 2000):
        """
        Initializes the app's integrator. Must be done first during app
        init so that the integrator is available for other objects to set their
        state variables.
        """
        self.app = app
        self.x = np.zeros(max_state_size)
        self.x_new = np.zeros(max_state_size)
        self.x_dot = np.zeros(max_state_size)
        self.x_dot_previous = np.zeros(max_state_size)
        self.dt_previous = None
        self.next_idx = 0
        self.max_state_size = max_state_size
        self.counter = 0

    def initialize_tasks(self):
        """
        Initializes the integrator step task. Must be done at the end of the
        all modules' initialization, but before the physics tasks initializations.
        """
        self.app.taskMgr.add(self.step, "integrator_step")

    def set_state_variables(
        self,
        partial_x: np.ndarray,
        partial_x_dot: np.ndarray,
        partial_x_dot_previous: np.ndarray,
    ):
        """
        Sets consecutive state_variables and returns the index at which they
        should be retrieved.

        All arguments should be numpy vectors of the same size.
        """
        # Check input sizes
        n_new_var = len(partial_x)
        assert n_new_var == len(partial_x_dot)
        assert n_new_var == len(partial_x_dot_previous)

        # Check that there is enough room left to add those new variables
        current_idx = self.next_idx
        if current_idx + n_new_var - 1 > self.max_state_size:
            raise RuntimeError("You're trying to set too much state variables")

        # Update next_idx
        self.next_idx += n_new_var

        # Set variables
        self.x[current_idx : self.next_idx] = partial_x.copy()
        self.x_dot[current_idx : self.next_idx] = partial_x_dot.copy()
        self.x_dot_previous[current_idx : self.next_idx] = partial_x_dot_previous.copy()

        # Return retrieving index
        return current_idx

    def get_state_variables(self, first_idx: int, n_var: int):
        """
        Gets the state variables for the objects
        """
        return self.x_new[first_idx : first_idx + n_var].copy()

    def step(self, task):
        """
        A 2nd order Admas-Bashforth integrator.
        For the first step, a 1st order forward Euler (=AB1) is used.

        For any new state variable at runtime, just set the previous
        derivative with the current derivative to get an AB1 initialization
        of that variable.

        To avoid weird oscillations, also do an AB1 step every 100 steps
        """
        # Get the timespan of the current step
        dt = self.app.clock.dt

        # Integrate and populate x_new
        if self.dt_previous is None:
            self.x_new = self.x + dt * self.x_dot
        else:
            if self.counter >= 100:
                self.counter = 0
                self.x_new = self.x + dt * self.x_dot
            else:
                self.x_new = self.x + 0.5 * dt / self.dt_previous * (
                    (2 * self.dt_previous + dt) * self.x_dot - dt * self.x_dot_previous
                )
                self.counter += 1

        # Prepare the next step by wiping the inputs
        # We don't set x_dot_previous to x_dot because the number of state variables
        # can change from one step to the other (objects appearing/disappearing)
        self.dt_previous = dt
        self.next_idx = 0
        self.x = np.zeros(self.max_state_size)
        self.x_dot = np.zeros(self.max_state_size)
        self.x_dot_previous = np.zeros(self.max_state_size)

        return task.cont
