"""
Hyperspace transits: a ship dropping out of hyperspace into the level, or
jumping out of it.

The transit is cosmetic. The ship's physics is pinned at the transit pose (the
spawn point for an arrival), keeping its velocity without moving, while only
its render node travels along its heading: it rushes in from far behind and
brakes hard down to its spawn speed, or speeds up from its speed and streaks
away. Meanwhile every collider under the ship's node is
muted and the ship is flagged in_hyperspace, which keeps it out of every
hostile interaction (it cannot be targeted, nor target anything).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

import numpy as np
from panda3d.core import BitMask32

if TYPE_CHECKING:
    from space_flight.actors.ship import Ship

#: How sharply an arrival decelerates: the ship covers most of the distance
#: in the first instants of the transit, then brakes hard to its own speed
TRANSIT_SHARPNESS = 15.0
#: Distance (m) the transit covers and its duration (s), per bot type
TRANSIT_DISTANCE_M = {"fighter": 4000.0, "major_ship": 15000.0}
TRANSIT_DURATION_S = {"fighter": 0.5, "major_ship": 1.0}
#: How long (s) a ship flies straight, spooling up its hyperdrive, before it
#: jumps out
JUMP_SPOOL_S = 2.0
#: Up to this random delay (s) before each wave member drops in, so a
#: formation does not land in lockstep
ARRIVAL_STAGGER_S = 0.8


def transit_offset_fraction(
    progress: float,
    arriving: bool,
    speed_fraction: float = 0.0,
    sharpness: float = TRANSIT_SHARPNESS,
) -> float:
    """
    How far along its heading the ship is drawn from the transit pose, as a
    fraction of the transit distance.

    An arrival starts at 1 (far behind) and decays to exactly 0: very fast at
    first, then a hard brake, landing at the ship's own speed. It blends an
    exponential decay, flattened to end with a zero slope, with a constant
    motion at the ship's speed, weighted by speed_fraction. A departure is the
    same motion played backwards, from 0 (the transit pose) to 1 (far ahead):
    it leaves at the ship's speed, then streaks away.

    :param progress: Elapsed fraction of the transit, clamped to [0, 1]
    :param arriving: Whether the ship arrives (else it departs)
    :param speed_fraction: The ship's speed times the transit duration over
        the transit distance (clamped to [0, 1]): the share of the distance
        covered at the ship's own speed
    :param sharpness: How sharply the motion brakes
    :return: The offset fraction in [0, 1]
    """
    progress = min(max(progress, 0.0), 1.0)
    if not arriving:
        return transit_offset_fraction(1.0 - progress, True, speed_fraction, sharpness)
    speed_fraction = min(max(speed_fraction, 0.0), 1.0)
    floor = math.exp(-sharpness)
    # From 1 to 0, with a zero slope at the end
    decay = (
        math.exp(-sharpness * progress) - floor * (1.0 + sharpness * (1.0 - progress))
    ) / (1.0 - floor * (1.0 + sharpness))
    return (1.0 - speed_fraction) * decay + speed_fraction * (1.0 - progress)


class HyperspaceTransit:
    """
    Drives one ship's transit, one frame at a time (see :meth:`step`).

    :param ship: The transiting ship
    :param arriving: Whether it drops in (else it jumps out)
    :param distance_m: The distance its render node travels
    :param duration_s: How long the transit lasts
    :param clock: The (pause-aware) game clock
    :param delay_s: Time to wait, hidden and pinned, before an arrival starts
    """

    def __init__(
        self,
        ship: Ship,
        arriving: bool,
        distance_m: float,
        duration_s: float,
        clock: Callable[[], float],
        delay_s: float = 0.0,
    ):
        self.ship = ship
        self.arriving = arriving
        self.distance_m = distance_m
        self.duration_s = duration_s
        self.clock = clock
        self.delay_s = delay_s
        self.position = None
        self.orientation = None
        self.velocity = None
        self.speed_fraction = 0.0
        self.start_s = None
        self._muted_colliders = []

    def begin(self):
        """
        Pin the ship at its current pose and velocity, mute its colliders and
        flag it in hyperspace. An arrival waiting out its delay is hidden.
        """
        ship = self.ship
        self.position = np.array(ship.position, dtype=float)
        self.orientation = np.array(ship.orientation, dtype=float)
        self.velocity = np.array(ship.speed, dtype=float)
        if self.distance_m > 0.0:
            speed_mps = float(np.linalg.norm(self.velocity))
            self.speed_fraction = speed_mps * self.duration_s / self.distance_m
        self.start_s = self.clock() + self.delay_s
        ship.in_hyperspace = True
        self._mute_colliders()
        if self.arriving and self.delay_s > 0.0:
            ship.node.hide()

    def step(self) -> bool:
        """
        Advance the transit by one frame: hold the ship's physics and draw its
        render node along its heading.

        :return: True once the transit is over
        """
        elapsed_s = self.clock() - self.start_s
        if elapsed_s < 0.0:
            progress = 0.0
        else:
            progress = elapsed_s / self.duration_s if self.duration_s > 0.0 else 1.0
            self.ship.node.show()
        fraction = transit_offset_fraction(
            progress, self.arriving, speed_fraction=self.speed_fraction
        )
        # An arrival comes from behind, a departure streaks away ahead
        direction = -1.0 if self.arriving else 1.0
        offset_m = direction * fraction * self.distance_m
        self.ship.hold_step(
            position=self.position,
            orientation=self.orientation,
            speed=self.velocity,
            offset_m=offset_m,
        )
        return progress >= 1.0

    def end(self):
        """Restore the ship's colliders and bring it back into the fight."""
        self._restore_colliders()
        self.ship.in_hyperspace = False
        if self.ship.node is not None:
            self.ship.node.show()

    def _mute_colliders(self):
        """
        Mute every collider under the ship's node (hull, subsystems, shield,
        sensors), remembering their masks to restore them.
        """
        for collider in self.ship.node.findAllMatches("**/+CollisionNode"):
            node = collider.node()
            self._muted_colliders.append(
                (collider, node.getFromCollideMask(), node.getIntoCollideMask())
            )
            node.setFromCollideMask(BitMask32.allOff())
            node.setIntoCollideMask(BitMask32.allOff())

    def _restore_colliders(self):
        """Restore the masks of the colliders muted by :meth:`begin`."""
        for collider, from_mask, into_mask in self._muted_colliders:
            if collider.isEmpty():
                continue
            node = collider.node()
            node.setFromCollideMask(from_mask)
            node.setIntoCollideMask(into_mask)
        self._muted_colliders = []
