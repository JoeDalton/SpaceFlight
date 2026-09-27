"""
Spreads the bots' thinking (navigator + pilot) evenly over frames.

A bot's pilot only samples its commands once per period (its PIDs' sample
time), so the bot only needs to think on those frames. If every bot thought
on the same frames, those frames would carry the whole AI load and the ones
in between almost none: a periodic hitch. Instead, time is divided into slots
one frame long, and each bot gets the least-busy slot of its period, which
keeps the number of bots thinking in any frame within one of the average.
"""

from __future__ import annotations

import math

import numpy as np

#: Slot length: one frame at the reference 60 Hz. Slots are offsets in game
#: time, so a different real frame rate still spreads the load.
THINK_SLOT_S = 1.0 / 60.0


class ThinkSlot:
    """
    A bot's place in the schedule: it thinks every n_slots slots, at phase.

    :param scheduler: The scheduler that assigned the slot
    :param phase: Offset of the bot's think times, in slots
    :param n_slots: The bot's think period, in slots
    """

    def __init__(self, scheduler: ThinkScheduler, phase: int, n_slots: int):
        self.scheduler = scheduler
        self.phase = phase
        self.n_slots = n_slots

    @property
    def period_s(self) -> float:
        return self.n_slots * self.scheduler.slot_s

    def next_due_time_s(self, now_s: float) -> float:
        """
        The game time from which the bot's next think, after the frame at now_s,
        is due.

        Think times lie on the grid (phase + k * n_slots) * slot_s. A think is
        due half a slot early, so float drift in the game clock can't push it
        to the following frame.

        :param now_s: The current game time
        :return: The due time of the first think strictly after now_s
        """
        slot_s = self.scheduler.slot_s
        offset_s = self.phase * slot_s
        k = math.floor((now_s + 0.5 * slot_s - offset_s) / self.period_s) + 1
        return offset_s + k * self.period_s - 0.5 * slot_s


class ThinkScheduler:
    """
    Assigns each thinking bot a slot, balancing how many bots think per frame.

    :param slot_s: Slot length (one frame)
    """

    def __init__(self, slot_s: float = THINK_SLOT_S):
        self.slot_s = slot_s
        # Number of bots thinking in each slot of the hyperperiod: the least
        # common multiple of every period registered so far, in slots.
        self.load = np.zeros(1, dtype=int)

    def register(self, period_s: float) -> ThinkSlot:
        """
        Give a new bot the least-busy phase of its period.

        :param period_s: How often the bot thinks
        :return: The bot's slot
        """
        n_slots = max(1, round(period_s / self.slot_s))
        hyperperiod = math.lcm(len(self.load), n_slots)
        if hyperperiod != len(self.load):
            self.load = np.tile(self.load, hyperperiod // len(self.load))
        # Least-busy phase: lowest peak, then lowest total, over the slots it
        # would occupy (phase, phase + n_slots, ...)
        phase = min(
            range(n_slots),
            key=lambda p: (
                self.load[p::n_slots].max(),
                self.load[p::n_slots].sum(),
            ),
        )
        self.load[phase::n_slots] += 1
        return ThinkSlot(scheduler=self, phase=phase, n_slots=n_slots)

    def unregister(self, slot: ThinkSlot) -> None:
        """
        Free a bot's slot (the bot died or was cleaned up).

        :param slot: The slot returned by register
        """
        self.load[slot.phase :: slot.n_slots] -= 1
