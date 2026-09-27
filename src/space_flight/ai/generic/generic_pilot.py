import logging

from space_flight import DEBUG_DELETION
from space_flight.actors.pawn import Pawn
from space_flight.ai import Personality

LOGGER = logging.getLogger()


class GenericPilot:
    """
    A generic class for automatic pilots
    """

    def __init__(
        self, game, pawn: Pawn, personality: dict = Personality.FIGHTER_DEFAULT
    ):
        self.game = game
        self.pawn: Pawn = pawn
        self.personality: dict = personality

    @property
    def sample_period_s(self) -> float:
        """How often the pilot's PIDs compute new commands."""
        return self.personality["pilot"]["sample_time_s"]

    def sample_externally(self):
        """
        Make the PIDs compute on every call, for a caller (a bot's think
        scheduler) that already calls pilot() once per sample_period_s. Left to
        the PIDs' own sample time, clock jitter (dt = 0.0999... < 0.1) could make
        them skip a scheduled call and hold their output a whole extra period.
        """
        raise NotImplementedError

    def set_on(
        self,
        **kwargs,
    ):
        """
        Sets the Auto pilot on
        """
        raise NotImplementedError

    def set_off(self):
        """
        Sets the Auto pilot off
        """
        raise NotImplementedError

    def pilot(
        self,
        **kwargs,
    ):
        """
        Compute the pawn's inputs
        """
        raise NotImplementedError

    def clean(self):
        self.pawn = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autopilot")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autopilot")
