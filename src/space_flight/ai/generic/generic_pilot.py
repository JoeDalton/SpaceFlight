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
