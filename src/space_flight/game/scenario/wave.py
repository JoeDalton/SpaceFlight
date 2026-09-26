"""
Waves: a static description of a group of bots (:class:`WaveSpec`, declared
as a constant in a level module) and its live counterpart for one run of the
mission (:class:`WaveHandle`, returned by :meth:`Mission.wave` /
:meth:`Mission.spawn`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Optional, Sequence, Union

import numpy as np

from space_flight.actors.bot import spawn_bot
from space_flight.ai.formation import Formation
from space_flight.game.scenario.conditions import pawns_of

if TYPE_CHECKING:
    from space_flight.actors.bot import Bot
    from space_flight.game.scenario.mission import Mission


@dataclass(frozen=True)
class WaveSpec:
    """
    A group of bots to spawn, declared as a constant in a level module.

    :param name: Used to name the spawned bots (``<name>_<i>``) and in logs
    :param ship_model: A pawn model, or a sequence of (model, count) pairs
        for a mixed-composition wave
    :param size: Number of ships; required for a single model, inferred from
        the counts for a mixed wave
    :param spawn_point: World position of the leader; may instead be given
        at spawn time (e.g. when it depends on the player's position)
    :param bot_type: "fighter" or "capital_ship"
    :param team: The bots' team
    :param spawn_orientation: Quaternion (w, x, y, z), passed straight to
        Panda3D; the default is a 180 degree turn about z, not the identity
    :param formation: "arrowhead", "diamond", "around_diamond", or None to
        spawn in a centred line
    :param formation_scale_m: Spacing of the formation slots
    :param waypoints: Patrol route given to every ship
    :param loop: Whether the route loops back to its first waypoint
    :param record: Step-by-step-record every bot of the wave (game.record)
    """

    name: str
    ship_model: Union[str, Sequence[tuple[str, int]]]
    size: Optional[int] = None
    spawn_point: Optional[Sequence[float]] = None
    bot_type: str = "fighter"
    team: int = 2
    spawn_orientation: Sequence[float] = (0, 0, 0, 1)
    formation: Optional[str] = None
    formation_scale_m: float = Formation.FIGHTER_SCALE_M
    waypoints: Sequence[Sequence[float]] = ()
    loop: bool = True
    record: bool = False

    def __post_init__(self) -> None:
        single = isinstance(self.ship_model, str)
        if single and self.size is None:
            raise ValueError(f"wave '{self.name}': size is required")
        if not single and self.size is not None:
            raise ValueError(
                f"wave '{self.name}': size is inferred for a mixed-composition wave"
            )

    def ship_models(self) -> list[str]:
        """One pawn model per ship, in spawn order."""
        if isinstance(self.ship_model, str):
            return [self.ship_model] * self.size
        return [model for model, count in self.ship_model for _ in range(count)]


class WaveHandle:
    """
    The live side of a wave for one run of the mission.

    Created (not yet spawned) by :meth:`Mission.wave`, so rules can refer to
    a wave before it exists; :meth:`spawn` then creates its ships, one per
    frame. Its state methods (:meth:`alive`, :meth:`all_destroyed`,
    :meth:`any_destroyed`) return bools and can be passed uncalled as
    conditions.

    :param mission: The owning mission
    :param spec: What to spawn
    """

    def __init__(self, mission: Mission, spec: WaveSpec) -> None:
        self.mission = mission
        self.spec = spec
        #: Pawn ids of every ship spawned so far, in spawn order (the
        #: formation leader first). Dead ids are filtered out by pawns().
        self.ids: list = []
        #: The wave's formation, once spawned (None if it has none).
        self.formation: Optional[Formation] = None

    @property
    def name(self) -> str:
        return self.spec.name

    # ------------------------------------------------------------------
    # State, read live
    # ------------------------------------------------------------------

    def pawns(self) -> list:
        """The wave's live pawns, in spawn order."""
        interactions = self.mission.game.interactions
        id_dict = interactions.actors_id_dict
        return [interactions.actors[id_dict[i]] for i in self.ids if i in id_dict]

    def alive(self) -> bool:
        """At least one member is alive."""
        return bool(self.pawns())

    def all_destroyed(self) -> bool:
        """The wave has spawned and every member is dead (False before spawn)."""
        return bool(self.ids) and not self.pawns()

    def any_destroyed(self) -> bool:
        """The wave has spawned and lost at least one member (stays True after a
        total wipe)."""
        return bool(self.ids) and len(self.pawns()) < len(self.ids)

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def spawn(
        self,
        spawn_point: Optional[Sequence[float]] = None,
        target: Any = None,
        join: Optional[Formation] = None,
    ) -> WaveHandle:
        """
        Spawn the wave's ships, one per frame.

        Calling it again spawns the same composition again into this wave.

        :param spawn_point: Overrides the spec's spawn point
        :param target: Who the ships attack (see :func:`pawns_of`), resolved
            as each ship spawns
        :param join: A live formation to attach to, continuing from its next
            free slot, instead of creating the spec's own formation
        :return: self
        """
        point = spawn_point if spawn_point is not None else self.spec.spawn_point
        if point is None:
            raise ValueError(f"wave '{self.name}': no spawn point")
        self.mission.schedule(
            self._spawn_job(np.array(point, dtype=float), target, join)
        )
        return self

    def _spawn_job(
        self, spawn_point: np.ndarray, target: Any, join: Optional[Formation]
    ) -> Iterator[None]:
        spec = self.spec
        models = spec.ship_models()
        size = len(models)
        orientation = np.array(spec.spawn_orientation)
        waypoints = [np.array(w) for w in spec.waypoints]

        formation = join
        if formation is None and spec.formation is not None:
            formation = Formation(scale_m=spec.formation_scale_m, shape=spec.formation)
        if formation is not None:
            self.formation = formation
        offsets = formation.relative_positions if formation is not None else None

        for i, model in enumerate(models):
            # Each ship takes the formation's next free slot at the moment it
            # spawns, so waves spawning into the same formation concurrently
            # (a join while the host wave is still spawning) never share one.
            slot = len(formation.ship_ids) if formation is not None else i
            bot = spawn_bot(
                game=self.mission.game,
                name=f"{spec.name}_{i}",
                bot_type=spec.bot_type,
                pawn_model=model,
                ini_position=spawn_point + _wave_offset(offsets, slot, size),
                ini_orientation=orientation,
                team=spec.team,
                debug_decisions=False,
                record=spec.record,
            )
            self.ids.append(bot.pawn.id)
            if formation is not None:
                formation.add_ship(ship=bot.pawn)
            if waypoints:
                bot.navigator.set_waypoints(waypoints=waypoints, is_loop=spec.loop)
            if target is not None:
                _add_targets(bot, target)
            yield  # only one ship per frame

    # ------------------------------------------------------------------
    # Mutating every live member
    # ------------------------------------------------------------------

    def set_targets(self, who: Any) -> None:
        """Every live member attacks every live pawn of who."""
        for pawn in self.pawns():
            _add_targets(pawn.parent, who)

    def set_team(self, team: int) -> None:
        """Reassign every live member's team, cascading for capital ships."""
        for pawn in self.pawns():
            pawn.parent.set_team(team)

    def set_waypoints(
        self, points: Sequence[Sequence[float]], loop: bool = True
    ) -> None:
        """Give every live member a new route."""
        waypoints = [np.array(p) for p in points]
        for pawn in self.pawns():
            pawn.parent.navigator.set_waypoints(waypoints=waypoints, is_loop=loop)


def _add_targets(bot: Bot, who: Any) -> None:
    """Make every live pawn of who a primary target of bot."""
    bot.tactician.primary_target_ids.extend(pawn.id for pawn in pawns_of(who))


def _wave_offset(offsets: Optional[list[np.ndarray]], i: int, size: int) -> np.ndarray:
    """
    Spawn offset of the i-th ship relative to the spawn point: its formation
    slot (the leader's is zero), or a centred line without a formation or
    past its capacity.
    """
    if offsets is not None and i < len(offsets):
        return offsets[i]
    return np.array([-(size // 2) * 50 + 50 * i, 0, 0], dtype=float)
