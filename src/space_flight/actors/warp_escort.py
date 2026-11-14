"""
Wingmen escorting the player through a local warp (see WarpDrive).

Only the wingmen of a formation the player leads follow; every other ship is
left where it is. Each frame the player feeds its warp drive's state, after
the drive's update, and the escort reacts to its changes:

    IDLE -> CHARGING     the live wingmen fly along the player's heading,
                         weapons cold (see Bot.begin_warp_alignment)
    CHARGING -> IDLE     the jump was called off: back to the fight
    CHARGING -> INSIDE   they jump out after the player and wait, hidden and
                         untouchable, in hyperspace (see Bot.jump_to_warp)
    ... -> IDLE          once the player has dropped out, they drop back in on
                         their formation slots around it, a little scattered,
                         at its heading and velocity (see Bot.arrive_from_warp)

The wingmen are never torn down: they stay alive, in their wave and formation
(and keep their damage) throughout. A wingman killed or ordered out of the
level while the jump charges is left out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight import WARP_ESCORT_SLOT_JITTER
from space_flight.actors.hyperspace import ARRIVAL_STAGGER_S
from space_flight.actors.warp_drive import WarpState
from space_flight.ai.formation import Formation

if TYPE_CHECKING:
    from space_flight.actors.bot import Bot
    from space_flight.actors.player import Player


class WarpEscort:
    """The player's wingmen, following it through its local warps."""

    def __init__(self, player: Player, rng: np.random.Generator | None = None):
        """
        :param player: The player, leading (or not) a formation
        :param rng: Random generator for the landing scatter and stagger
        """
        self.player = player
        self.rng = rng if rng is not None else np.random.default_rng()
        self._previous_state = WarpState.IDLE
        # The escorting wingmen and their formation slot index, from the
        # start of the charge to the drop back in
        self._escorts: list[tuple[Bot, int]] = []

    def update(self, state: WarpState):
        """
        React to the warp drive's state. Call it every frame, after the
        drive's update.

        :param state: The drive's current state
        """
        previous, self._previous_state = self._previous_state, state
        if state is previous:
            return
        if previous is WarpState.IDLE and state is WarpState.CHARGING:
            self._escorts = self._wingmen()
            for bot, _ in self._escorts:
                bot.begin_warp_alignment(self.player.pawn)
        elif previous is WarpState.CHARGING and state is WarpState.IDLE:
            self._release()
        elif state is WarpState.INSIDE:
            for bot, _ in self._escorts:
                bot.jump_to_warp()
        elif state is WarpState.IDLE:
            self._land()

    def player_lost(self):
        """The player is dying: wingmen still aligning go back to the fight;
        those in hyperspace stay there."""
        self._release()
        self._previous_state = WarpState.IDLE

    def clean(self):
        self._escorts = []
        self.player = None

    # -- internals -----------------------------------------------------------

    def _wingmen(self) -> list[tuple[Bot, int]]:
        """The bots flying in the formation the player leads, with their slot
        index; none if the player leads none."""
        pawn = self.player.pawn
        formation = getattr(pawn, "formation", None)
        if formation is None or not formation.ship_ids:
            return []
        if formation.ship_ids[0] != pawn.id:
            return []
        interactions = self.player.game.interactions
        wingmen = []
        for index, ship_id in enumerate(formation.ship_ids[1:], start=1):
            wingman = interactions.find_actor(ship_id)
            bot = getattr(wingman, "parent", None)
            if bot is not None and getattr(bot, "can_escort_warp", False):
                wingmen.append((bot, index))
        return wingmen

    def _release(self):
        """Send the escorts still aligning back to the fight."""
        for bot, _ in self._escorts:
            bot.cancel_warp_alignment()
        self._escorts = []

    def _land(self):
        """Drop the escorts in on their slots around the player."""
        escorts, self._escorts = self._escorts, []
        leader = self.player.pawn
        formation = getattr(leader, "formation", None)
        for bot, index in escorts:
            if formation is not None:
                # Its slot may have shifted (a wingman lost on the way)
                current = formation.get_ship_index(bot.pawn.id)
                if current is not None:
                    index = current
            bot.arrive_from_warp(
                position=self._slot_position(index),
                orientation=np.array(leader.orientation, dtype=float),
                velocity=np.array(leader.speed, dtype=float),
                delay_s=float(self.rng.uniform(0.0, ARRIVAL_STAGGER_S)),
            )

    def _slot_position(self, index: int) -> np.ndarray:
        """
        Where a wingman lands: its formation slot around the player (as the
        formation navigator reckons it), scattered a little.

        :param index: The wingman's slot index in the formation
        """
        leader = self.player.pawn
        formation = leader.formation
        if formation is not None and index < len(formation.relative_positions):
            slot = formation.relative_positions[index]
            spacing_m = formation.scale_m
        else:
            # Out of the formation since: behind the player
            spacing_m = Formation.FIGHTER_SCALE_M
            slot = np.array([0.0, -2.0 * spacing_m * index, 0.0])
        jitter = self.rng.uniform(-1.0, 1.0, 3) * WARP_ESCORT_SLOT_JITTER * spacing_m
        offset = slot + jitter
        return (
            np.array(leader.position, dtype=float)
            + np.array(leader.right) * offset[0]
            + np.array(leader.forward) * offset[1]
            + np.array(leader.up) * offset[2]
        )
