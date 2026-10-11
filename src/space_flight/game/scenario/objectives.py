"""
Mission objectives: the checklist the player sees on the HUD.

An objective is display state only: it is ticked or failed by its own rules
(or by the mission body calling :meth:`Objective.complete` /
:meth:`Objective.fail`), but never ends the level by itself. The level still
calls :meth:`Mission.victory <space_flight.game.scenario.mission.Mission.victory>`
or ``defeat`` for that, typically on the same conditions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from space_flight.game.scenario.mission import Mission, Trigger

ACTIVE = "active"
COMPLETE = "complete"
FAILED = "failed"


def reaches(progress: Callable[[], int], goal: int) -> Callable[[], bool]:
    """A condition: true once progress counts up to goal."""
    return lambda: progress() >= goal


def summarize(objectives: list[Objective]) -> dict:
    """
    :param objectives: A mission's objectives
    :return: ``{"total": n, "complete": n, "failed": n}``
    """
    return {
        "total": len(objectives),
        "complete": sum(1 for objective in objectives if objective.done()),
        "failed": sum(1 for objective in objectives if objective.failed()),
    }


class Objective:
    """
    One line of the mission's objectives, made by :meth:`Mission.objective
    <space_flight.game.scenario.mission.Mission.objective>`.

    Its state methods (:meth:`done`, :meth:`failed`) return bools and can be
    passed uncalled as conditions.

    :param mission: The owning mission
    :param text: What to do, kept short
    :param progress: A live count towards goal, shown as "(n/goal)"
    :param goal: The count that completes it
    """

    def __init__(
        self,
        mission: Mission,
        text: str,
        progress: Optional[Callable[[], int]] = None,
        goal: Optional[int] = None,
    ):
        self.mission = mission
        self.text = text
        self.progress = progress
        self.goal = goal
        self.state = ACTIVE
        #: Game time of the last change (added, completed, failed), for the
        #: HUD to flash the line
        self.changed_at_s = mission.now()
        #: The rules completing / failing it, retired once it is settled
        self.rules: list[Trigger] = []
        # The progress shown once settled, frozen then
        self._final_progress: Optional[int] = None

    def label(self) -> str:
        """The line's text, with its progress if counted."""
        if self.progress is None or self.goal is None:
            return self.text
        count = self._final_progress
        if count is None:
            count = self.progress()
        return f"{self.text} ({min(count, self.goal)}/{self.goal})"

    # ------------------------------------------------------------------
    # State, read live (conditions)
    # ------------------------------------------------------------------

    def active(self) -> bool:
        return self.state == ACTIVE

    def done(self) -> bool:
        return self.state == COMPLETE

    def failed(self) -> bool:
        return self.state == FAILED

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def complete(self):
        """Tick it (a no-op once settled)."""
        self._settle(COMPLETE)

    def fail(self):
        """Fail it (a no-op once settled)."""
        self._settle(FAILED)

    def finalize(self):
        """
        Fix its final state, as the level ends: its rules due this very frame
        still fire (they may come after the one ending the level), then retire.
        """
        for rule in list(self.rules):
            rule.maybe_fire()
        self._retire_rules()

    def remove(self):
        """Take it off the list, settled or not."""
        self._retire_rules()
        if self in self.mission.objectives:
            self.mission.objectives.remove(self)

    def _settle(self, state: str):
        if self.state != ACTIVE:
            return
        if self.progress is not None:
            self._final_progress = self.progress()
        self.state = state
        self.changed_at_s = self.mission.now()
        self._retire_rules()

    def _retire_rules(self):
        for rule in self.rules:
            rule.cancel()
        self.rules = []
