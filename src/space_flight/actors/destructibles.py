import logging
import uuid
from typing import Callable, List

from space_flight import DEBUG_DELETION
from space_flight.utils.state_machine import DyingPhase

LOGGER = logging.getLogger()


class Destructible:
    """
    A class for destructible objects in the simulation
    """

    def __init__(self, game):
        self.game = game
        self.tasks = []
        self.id = uuid.uuid4()
        self.game.destructibles.alive_objects.append(self)
        self.game.method_lists[self.id] = []
        # Death lifecycle: an object whose health reaches zero enters a "dying"
        # phase (a spin-out, a smoke trail, ...) before it is finally reaped. The
        # phase lasts death_duration_s; a duration of 0 reaps immediately, which
        # is the legacy behaviour every destructible had before this was added.
        self.death_duration_s = 0.0
        self._dying = DyingPhase(clock=self.game.game_time.get_current_time)

    def add_task(self, method: Callable):
        """
        Add a task linked to this object

        :param method: the method to be called
        """
        self.game.method_lists[self.id].append(method)

    def clear_tasks(self):
        """
        Remove all tasks linked to this object

        Tolerates an already-torn-down object (game set to None by a prior
        clean): a bot-controlled subsystem such as a turret is a Destructible both
        as its Bot and as its pawn, so the death handler may reach the pawn after
        the Bot has already cleaned it. Clearing tasks then is a safe no-op.
        """
        if self.game is not None and self.game.method_lists:
            try:
                self.game.method_lists.pop(self.id)
            except KeyError:
                pass

    def clean(self):
        """
        Remove nodes and attributes, to be done for each subclass
        """
        raise NotImplementedError

    def get_health(self):
        """
        Find the health of the destructible object, to be done for each subclass
        """
        raise NotImplementedError

    @property
    def is_dying(self) -> bool:
        """Whether this object is playing out its (timed) death."""
        return self._dying.is_dying

    def death_elapsed_s(self) -> float:
        """
        Time in seconds since this object entered its dying phase.

        Uses the (pause-aware) game clock, so the death animation freezes with the
        game. Zero before the object starts dying.

        :return: Seconds spent dying so far
        """
        return self._dying.elapsed_s()

    def begin_death(self):
        """
        Enter the dying phase, once, when health first reaches zero.

        The default only stamps the death clock; subclasses extend it to kick off
        a death animation (disable AI, start a spin, ramp up smoke, ...). Idempotent:
        a second call while already dying is a no-op.
        """
        self._dying.begin()

    def update_death(self) -> bool:
        """
        Advance the dying phase by one frame.

        The default simply waits out death_duration_s; subclasses that animate a
        death do their per-frame work here (or in their own tasks) and may override
        the terminal condition.

        :return: True once the terminal blast should fire and the object be reaped
        """
        return self._dying.finished(self.death_duration_s)

    def finish_death(self):
        """
        Fire the terminal death effect, at the end of the dying phase.

        The default delegates to :meth:`play_death` so nothing regresses for
        objects that do not animate their death.
        """
        self.play_death()

    def play_death(self):
        """
        Plays the death animation of the destructible object,
        to be done for each subclass
        """
        raise NotImplementedError

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Destroyed destructible object: {self.name}")


class Destructibles:
    """
    A class to account for all destructible objects, and handle their deaths
    """

    def __init__(self):
        self.alive_objects: List[Destructible] = []
        # Objects that have reached zero health and are playing out their death
        # (spin-out, smoke, ...). They live here, across frames, until their dying
        # phase completes -- they are no longer "alive" but not yet reaped, so they
        # keep integrating and colliding while their animation plays.
        self.dying_objects: List[Destructible] = []

    def handle_deaths(self):
        """
        Move newly-dead destructibles into their dying phase, advance the ones
        already dying, and reap those whose death animation has finished.
        """
        # 1. Split the living from the newly dead. A newly-dead object enters its
        #    dying phase and moves to dying_objects (it is not reaped this frame).
        still_alive_objects: List[Destructible] = []
        for destructible in self.alive_objects:
            if destructible.get_health() <= 0.0:
                destructible.begin_death()
                self.dying_objects.append(destructible)
            else:
                still_alive_objects.append(destructible)
        self.alive_objects = still_alive_objects

        # 2. Advance every dying object; reap those whose animation has finished
        #    with the original terminal sequence (blast, then teardown), now
        #    deferred to the end of the dying phase.
        still_dying_objects: List[Destructible] = []
        for destructible in self.dying_objects:
            # A destructible may already have been cleaned out-of-band: a
            # bot-controlled subsystem (a turret) is a Destructible both as its Bot
            # and as its pawn, and the Bot cleans the pawn. Such an object is done.
            if getattr(destructible, "is_clean", False):
                continue
            if destructible.update_death():
                destructible.finish_death()
                destructible.clear_tasks()
                destructible.clean()
            else:
                still_dying_objects.append(destructible)
        self.dying_objects = still_dying_objects

    def clean(self):
        """
        Cleans the Destructibles object
        """
        # Clean all remaining destructible objects, alive or mid-death
        for destructible in self.alive_objects + self.dying_objects:
            if destructible is not None:
                destructible.clean()
        self.alive_objects = None
        self.dying_objects = None
