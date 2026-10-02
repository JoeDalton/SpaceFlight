"""
Scanning: the player identifies a ship by locking it as their target, closing
within range and holding it ahead of them for a few seconds.

A scan's progress lives on the scanned pawn itself, as a :class:`ScanState`
under ``pawn.scan``. The targeting HUD reads nothing else, so it draws the
progress bar for any scanned pawn without knowing about missions.
:class:`ScanHandle` (returned by :meth:`Mission.scan`) runs the scans of every
pawn of a wave and exposes their state as conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Optional

import numpy as np

from space_flight.game.scenario.conditions import Condition, pawns_of

if TYPE_CHECKING:
    from space_flight.actors.pawn import Pawn
    from space_flight.game.scenario.mission import Mission

SCAN_DURATION_S = 15.0
SCAN_RANGE_M = 1000.0
SCAN_CONE_DEG = 10.0
# Progress drains at this fraction of the fill rate while the scan is broken.
SCAN_DECAY_RATIO = 0.5


@dataclass
class ScanState:
    """
    One pawn's scan, attached as ``pawn.scan``.

    :param contraband: What the scan reveals once complete
    :param progress: From 0 (not started) to 1 (complete)
    :param result: None until complete, then "clear" or "contraband"
    """

    contraband: bool = False
    progress: float = 0.0
    result: Optional[str] = None

    @property
    def complete(self) -> bool:
        return self.result is not None

    @property
    def status_text(self) -> str:
        """A short status shown by the targeting HUD ("" before any progress)."""
        if self.result == "clear":
            return "CLEAR"
        if self.result == "contraband":
            return "CONTRABAND"
        if self.progress > 0.0:
            return f"SCANNING {self.progress * 100:.0f}%"
        return ""


class ScanHandle:
    """
    The scans of every pawn of who, advanced once per frame by a mission job.

    A pawn's scan progresses while it is the player's target, within range_m
    and within cone_deg of the player's nose; otherwise it drains at
    decay_ratio times the fill rate. Once complete, it is frozen.

    Its state methods (:meth:`complete`, :meth:`started`) return bools and
    can be passed uncalled as conditions.

    :param mission: The owning mission
    :param who: The pawns to scan (see :func:`pawns_of`); a wave may still be
        spawning, its members are picked up as they appear
    :param contraband: What the scan of each pawn reveals
    :param duration_s: Uninterrupted time needed to complete a scan
    :param range_m: Maximum scanning distance
    :param cone_deg: Maximum angle between the player's nose and the target
    :param decay_ratio: Drain rate while the scan is broken, relative to the
        fill rate
    """

    def __init__(
        self,
        mission: Mission,
        who: Any,
        contraband: bool = False,
        duration_s: float = SCAN_DURATION_S,
        range_m: float = SCAN_RANGE_M,
        cone_deg: float = SCAN_CONE_DEG,
        decay_ratio: float = SCAN_DECAY_RATIO,
    ):
        self.mission = mission
        self.who = who
        self.contraband = contraband
        self.duration_s = duration_s
        self.range_m = range_m
        self.cos_cone = float(np.cos(np.radians(cone_deg)))
        self.decay_ratio = decay_ratio
        mission.schedule(self._scan_job())

    # ------------------------------------------------------------------
    # State, read live
    # ------------------------------------------------------------------

    def states(self) -> list[ScanState]:
        """The scan states of who's live pawns (once picked up by the job)."""
        return [p.scan for p in pawns_of(self.who) if getattr(p, "scan", None)]

    def complete(self) -> bool:
        """Every live pawn of who has been scanned (False before any exists)."""
        states = self.states()
        return bool(states) and all(s.complete for s in states)

    def started(self) -> bool:
        """Any live pawn of who has some scan progress."""
        return any(s.progress > 0.0 for s in self.states())

    def progress_at_least(self, fraction: float) -> Condition:
        """A condition: any live pawn of who is scanned to at least fraction."""
        return lambda: any(s.progress >= fraction for s in self.states())

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def _is_held(self, pawn: Pawn) -> bool:
        """Whether the player holds pawn as a scannable target this frame."""
        player_pawn = self.mission.game.player.pawn
        if getattr(player_pawn, "target", None) is not pawn:
            return False
        interactions = self.mission.game.interactions
        try:
            player_idx = interactions.get_actor_index_from_id(player_pawn.id)
            pawn_idx = interactions.get_actor_index_from_id(pawn.id)
        except ValueError:
            return False  # the player or the pawn has just been removed
        distance = interactions.distances[player_idx, pawn_idx]
        if distance > self.range_m:
            return False
        if distance == 0.0:
            return True
        return interactions.alignments[player_idx, pawn_idx] >= self.cos_cone

    def _scan_job(self) -> Iterator[None]:
        last_time = self.mission.now()
        seen = False
        while True:
            yield
            now = self.mission.now()
            step = (now - last_time) / self.duration_s
            last_time = now

            pawns = pawns_of(self.who)
            seen = seen or bool(pawns)
            if seen and not pawns:
                return  # everyone died
            for pawn in pawns:
                state = getattr(pawn, "scan", None)
                if state is None:
                    state = pawn.scan = ScanState(contraband=self.contraband)
                if state.complete:
                    continue
                if self._is_held(pawn):
                    state.progress = min(1.0, state.progress + step)
                else:
                    state.progress = max(0.0, state.progress - self.decay_ratio * step)
                if state.progress >= 1.0:
                    state.result = "contraband" if state.contraband else "clear"
            if pawns and all(p.scan.complete for p in pawns):
                return
