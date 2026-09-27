"""
Mission scripting: a level's events written as a Python generator run by a
:class:`Mission`, spawning :class:`WaveSpec` groups of bots and reacting to
conditions (see :mod:`space_flight.game.scenario.conditions`).

Scanning lives in :mod:`space_flight.actors.scan`.
"""

from space_flight.game.scenario.mission import Mission, Trigger
from space_flight.game.scenario.wave import WaveHandle, WaveSpec

__all__ = ["Mission", "Trigger", "WaveHandle", "WaveSpec"]
