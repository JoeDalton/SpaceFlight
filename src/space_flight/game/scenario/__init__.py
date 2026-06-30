"""
Data-driven scenario scripting: a level declares its events in a YAML file, and
the engine here turns that into triggers (when -> then) that run each frame.

- :func:`load_scenario` builds a :class:`Scenario` from a YAML file.
- :class:`Scenario` runs the triggers, owns group membership, and resolves group
  names to live actors.
- :class:`Trigger` is one ``when condition: then action`` rule.

Conditions live in :mod:`space_flight.game.scenario.conditions` and actions in
:mod:`space_flight.game.scenario.actions`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Iterable, Iterator, Optional

from space_flight.actors.bot import spawn_bot

if TYPE_CHECKING:
    from uuid import UUID

    from space_flight.actors.bot import Bot
    from space_flight.ai.formation import Formation
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()

#: A condition callable, evaluated every frame: ``condition(game) -> bool``.
Condition = Callable[["FlightState"], bool]
#: An action callable, run when a trigger fires: ``action(game) -> None``.
Action = Callable[["FlightState"], None]
#: A live, targetable game object — a ship pawn or a waypoint marker.
Actor = Any


class Trigger:
    """
    A single mission rule: when ``condition`` becomes true, run ``action``.

    The trigger owns its one-shot state (:attr:`_fired`), so a rule fires its
    action only once by default. Set ``once=False`` for a rule that should fire
    every frame its condition holds.

    :param condition: Called each frame; the action runs when it returns ``True``
    :param action: Run when the condition is met
    :param once: Whether the action fires only the first time the condition holds
    :param name: Optional label, used for logging and by the ``fired`` condition
    """

    def __init__(
        self,
        condition: Condition,
        action: Action,
        once: bool = True,
        name: Optional[str] = None,
    ) -> None:
        self.condition = condition
        self.action = action
        self.once = once
        self.name = name
        self._fired = False

    def maybe_fire(self, game: FlightState) -> None:
        """
        Evaluate the condition and run the action if it is met.

        :param game: The game/flight state
        """
        if self._fired and self.once:
            return
        if self.condition(game):
            if self.name is not None:
                LOGGER.debug("Trigger fired: %s", self.name)
            self.action(game)
            self._fired = True


class Scenario:
    """
    Runs a level's scripted events and owns group membership.

    One instance lives on ``game.scenario`` for the duration of a level. Each
    frame it fires every due :class:`Trigger` and advances any running jobs. It
    also creates actors while recording their group membership (:meth:`spawn`),
    and resolves a symbolic group name to its live actors (:meth:`resolve`).

    :param triggers: The level's mission rules
    """

    def __init__(self, triggers: Iterable[Trigger] = ()) -> None:
        self.triggers: list[Trigger] = list(triggers)
        # Named triggers, for conditions that depend on another trigger having
        # fired (see :meth:`has_fired` and the ``fired`` condition).
        self.triggers_by_name: dict[str, Trigger] = {
            t.name: t for t in self.triggers if t.name
        }
        # Identity groups: name -> pawn ids spawned into that group. Append-only
        # and level-scoped; dead ids are filtered out at resolve time rather
        # than removed here, so death handling stays decoupled.
        self.groups: dict[str, list[UUID]] = {}
        # Identity group names that have actually spawned at least one member.
        # Updated by :meth:`spawn`. Lets :meth:`is_destroyed` tell "wiped out"
        # apart from "not spawned yet" and from "scheduled but not yet spawned"
        # (a wave spawns over several frames).
        self.spawned: set[str] = set()
        # Identity group names whose spawn has been scheduled this run. Used only
        # to dedupe spawn requests; kept separate from :attr:`spawned` so a wave
        # mid-spawn is not mistaken for one that finished and was destroyed.
        self.scheduled: set[str] = set()
        # Query groups: name -> predicate over a live actor, evaluated on demand.
        self.queries: dict[str, Callable[[Actor], bool]] = {}
        # Formations are kept alive here so they are not garbage collected once
        # the spawning job that built them returns.
        self.formations: list[Formation] = []
        # Active jobs: generators advanced one step per frame, letting an action
        # spread heavy work (e.g. spawning a wave) across frames.
        self.jobs: list[Iterator] = []

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, game: FlightState) -> None:
        """
        Advance the scenario by one frame.

        Fires every due trigger, then advances every running job by one step.
        Called once per unpaused frame by the game's scenario task.

        :param game: The game/flight state
        """
        for trigger in self.triggers:
            trigger.maybe_fire(game)
        self._step_jobs()

    def schedule(self, job: Iterator) -> None:
        """
        Register a generator to be advanced one step per frame.

        The job runs to its next ``yield`` on each :meth:`update`, and is dropped
        once it raises ``StopIteration``. Use this for work an action wants to
        spread over several frames.

        :param job: A generator that yields once per frame of work
        """
        self.jobs.append(job)

    def _step_jobs(self) -> None:
        """
        Advance every running job by one step, dropping finished ones.
        """
        if not self.jobs:
            return
        still_running: list[Iterator] = []
        for job in self.jobs:  # snapshot: jobs scheduled this step run next frame
            try:
                next(job)
                still_running.append(job)
            except StopIteration:
                pass
        self.jobs = still_running

    def has_fired(self, name: str) -> bool:
        """
        Whether the trigger called ``name`` has already fired.

        Lets one trigger depend on another having run (see the ``fired``
        condition). An unknown name warns and reports ``False``.

        :param name: The trigger name
        :return: ``True`` once that trigger's action has run
        """
        trigger = self.triggers_by_name.get(name)
        if trigger is None:
            LOGGER.warning("Scenario.has_fired: unknown trigger '%s'", name)
            return False
        return trigger._fired

    # ------------------------------------------------------------------
    # Membership assignment
    # ------------------------------------------------------------------

    def spawn(
        self, game: FlightState, *, groups: Iterable[str] = (), **bot_kwargs: Any
    ) -> Bot:
        """
        Create a bot and record its group membership in a single call.

        This is the only sanctioned way to add a member to an identity group:
        because creation and registration happen together, the registry can
        never drift out of sync with what actually exists.

        :param game: The game/flight state
        :param groups: Names of identity groups this bot belongs to
        :param bot_kwargs: Forwarded verbatim to :func:`spawn_bot`
        :return: The spawned :class:`Bot`
        """
        bot = spawn_bot(game=game, **bot_kwargs)
        for name in groups:
            self.groups.setdefault(name, []).append(bot.pawn.id)
            self.spawned.add(name)
        return bot

    def register(self, name: str, bots: Iterable[Bot]) -> None:
        """
        Register already-spawned bots as an identity group.

        For standing groups built directly in a level (e.g. the convoy and its
        escort) rather than through a spawn action.

        :param name: The group name
        :param bots: The bots to add to the group
        """
        ids = self.groups.setdefault(name, [])
        for bot in bots:
            ids.append(bot.pawn.id)
        self.spawned.add(name)

    def register_query(self, name: str, predicate: Callable[[Actor], bool]) -> None:
        """
        Register a derived group computed live from a predicate.

        :param name: The group name (e.g. ``"enemies"``)
        :param predicate: Tested against each live actor to decide membership
        """
        self.queries[name] = predicate

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, game: FlightState, name: str) -> list[Actor]:
        """
        Resolve a group name to the actors currently alive in it.

        Handles both kinds of group behind one call: a registered query is
        evaluated against the live actors; otherwise the name is an identity
        group and its stored ids are filtered through the live-actor registry.

        :param game: The game/flight state
        :param name: The group name
        :return: The live actors in the group; empty if unknown or all dead
        """
        if name in self.queries:
            predicate = self.queries[name]
            return [a for a in game.interactions.live_actors if predicate(a)]

        ids = self.groups.get(name)
        if ids is None:
            LOGGER.warning("Scenario.resolve: unknown group '%s'", name)
            return []

        id_dict = game.interactions.actors_id_dict
        actors = game.interactions.actors
        return [actors[id_dict[i]] for i in ids if i in id_dict]

    def resolve_one(self, game: FlightState, name: str) -> Optional[Actor]:
        """
        Resolve to the first live actor in a group, or ``None``.

        :param game: The game/flight state
        :param name: The group name
        :return: A single live actor, or ``None`` if the group has none
        """
        actors = self.resolve(game, name)
        return actors[0] if actors else None

    def is_alive(self, game: FlightState, name: str) -> bool:
        """
        Whether any member of the group is currently alive.

        :param game: The game/flight state
        :param name: The group name
        :return: ``True`` if at least one member is alive
        """
        return bool(self.resolve(game, name))

    def is_destroyed(self, game: FlightState, name: str) -> bool:
        """
        Whether an identity group has spawned and now has no live members.

        Returns ``False`` for a group that has not spawned yet, so a chained
        ``all_destroyed`` event cannot fire before its target ever existed. For a
        query group, reports whether the query is currently empty.

        :param game: The game/flight state
        :param name: The group name
        :return: ``True`` once a spawned group has lost every member
        """
        if name in self.queries:
            return not self.resolve(game, name)
        return name in self.spawned and not self.resolve(game, name)
