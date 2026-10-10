from __future__ import annotations

from space_flight.actors.major_ship.major_ship import MajorShip
from space_flight.ai import Personality


class EscortShip(MajorShip):
    """
    A manoeuverable major ship: transport, frigate, corvette (e.g. GR-75, CR-90).

    Its bot runs the full AI stack: a tactician, so it engages, regroups,
    disengages, flies in formation and patrols on its own, and a navigator that
    steers around obstacles.
    """

    #: Tuning of its bot's tactician, navigator and pilot
    personality = Personality.ESCORT_SHIP_DEFAULT
    #: Its bot picks its own intents
    has_tactician = True
    #: Its bot steers around obstacles
    collision_avoidance = True
