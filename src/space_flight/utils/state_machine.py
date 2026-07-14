"""
A small, dependency-free finite state machine and a cooldown timer, shared by the
game's several FSM-shaped subsystems (tactician intent, navigator behaviour/phase,
shield lifecycle, auto-aim lock, tractor-beam grab).

The machine owns only the *mechanics* every one of those hand-rolls -- the current
state, time-in-state (reset on entry), a minimum-dwell / commitment gate, and
entry/exit hooks -- never the *policy* (how the next state is chosen), which stays
in each owner's own logic. The time source is injected, so the machine is trivially
testable without the game clock.
"""

from typing import Callable, Hashable, Optional, Union


class StateMachine:
    """
    A finite state machine with time-in-state tracking and a per-state commitment
    (minimum-dwell) gate.

    The owner decides *what* the next state should be and calls :meth:`request`;
    the machine enforces the dwell gate, tracks how long the current state has been
    held, and fires entry/exit hooks.
    """

    def __init__(
        self,
        initial_state: Hashable,
        clock: Callable[[], float],
        commit_times: Optional[Union[float, dict]] = None,
        name: str = "",
    ):
        """
        :param initial_state: the starting state key (enum / str / bool / any hashable)
        :param clock: a callable returning the current time in seconds
        :param commit_times: minimum dwell before *leaving* a state -- a scalar
            applied to every state, a {state: seconds} dict, or None for no dwell
        :param name: optional label for debugging
        """
        self._clock = clock
        self._state = initial_state
        self._previous_state: Optional[Hashable] = None
        self._entered_at_s = clock()
        self._commit_times = commit_times
        self.name = name
        self._on_enter: dict = {}
        self._on_exit: dict = {}

    @property
    def state(self) -> Hashable:
        return self._state

    @property
    def previous_state(self) -> Optional[Hashable]:
        return self._previous_state

    @property
    def time_in_state_s(self) -> float:
        """How long the current state has been held."""
        return self._clock() - self._entered_at_s

    def commit_time_s(self, state: Optional[Hashable] = None) -> float:
        """
        The minimum dwell time for *state* (the current state if omitted).

        :return: the commitment time in seconds (0 if none configured)
        """
        state = self._state if state is None else state
        commit = self._commit_times
        if commit is None:
            return 0.0
        if isinstance(commit, dict):
            return commit.get(state, 0.0)
        return commit

    def is_committed(self) -> bool:
        """Whether the current state has been held for its minimum dwell time."""
        return self.time_in_state_s >= self.commit_time_s()

    def on_enter(self, state: Hashable, callback: Callable[[], None]):
        """Register a callback fired when *state* is entered."""
        self._on_enter[state] = callback

    def on_exit(self, state: Hashable, callback: Callable[[], None]):
        """Register a callback fired when *state* is left."""
        self._on_exit[state] = callback

    def request(self, new_state: Hashable, force: bool = False) -> bool:
        """
        Request a transition to *new_state*.

        Refused (returns False) if it would leave the current state before its
        commitment time has elapsed, unless *force* is True. A request for the
        current state is always a no-op. On an accepted change it fires the exit
        hook of the old state then the enter hook of the new one, and resets
        time-in-state.

        :return: True if the state changed
        """
        if new_state == self._state:
            return False
        if not force and not self.is_committed():
            return False

        exit_callback = self._on_exit.get(self._state)
        if exit_callback is not None:
            exit_callback()
        self._previous_state = self._state
        self._state = new_state
        self._entered_at_s = self._clock()
        enter_callback = self._on_enter.get(new_state)
        if enter_callback is not None:
            enter_callback()
        return True

    def reset_timer(self):
        """
        Reset time-in-state to zero without changing state or firing hooks (e.g.
        auto-aim losing alignment restarts its lock dwell).
        """
        self._entered_at_s = self._clock()


class Cooldown:
    """
    A time-since-last-event gate, orthogonal to :class:`StateMachine` (shield regen,
    tractor re-grab).

    :meth:`trigger` stamps the clock; :meth:`ready` reports whether the duration has
    elapsed, optionally scaled by a multiplier (e.g. a shield reforms slower while
    down).
    """

    def __init__(
        self,
        duration_s: float,
        clock: Callable[[], float],
        ready_at_start: bool = True,
    ):
        """
        :param duration_s: the cooldown duration
        :param clock: a callable returning the current time in seconds
        :param ready_at_start: whether the cooldown reads ready before any trigger
        """
        self._duration_s = duration_s
        self._clock = clock
        self._last_trigger_s: Optional[float] = None if ready_at_start else clock()

    def trigger(self):
        """Stamp the current time as the last event."""
        self._last_trigger_s = self._clock()

    def elapsed_s(self) -> float:
        """Time since the last trigger (infinite if never triggered)."""
        if self._last_trigger_s is None:
            return float("inf")
        return self._clock() - self._last_trigger_s

    def ready(self, multiplier: float = 1.0) -> bool:
        """
        Whether the cooldown has elapsed.

        :param multiplier: scales the duration (e.g. >1 to lengthen it in a state)
        :return: True if ready
        """
        return self.elapsed_s() >= self._duration_s * multiplier
