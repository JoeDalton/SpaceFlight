from __future__ import annotations

from space_flight.actors.major_ship.major_ship import MajorShip
from space_flight.ai import Personality


class CapitalShip(MajorShip):
    """
    A true capital ship (e.g. an Imperial-class Star Destroyer): too big to
    manoeuver, it is scripted.

    Its bot has no tactician, so it is always in patrol mode, flying the
    waypoints the mission gives it, and it does not steer around obstacles.
    Its pilot remains, and its mounted turrets still fight on their own.
    """

    #: Tuning of its bot's navigator (patrol only) and pilot
    personality = Personality.CAPITAL_SHIP_DEFAULT
    #: No tactician: its bot always patrols
    has_tactician = False
    #: Its bot does not steer around obstacles
    collision_avoidance = False
