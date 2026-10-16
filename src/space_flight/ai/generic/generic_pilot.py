from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from simple_pid import PID

from space_flight import DEBUG_DELETION
from space_flight.actors.pawn import Pawn
from space_flight.ai import Personality
from space_flight.utils import safe_angle_rad

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class GenericPilot:
    """
    A generic class for automatic pilots
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
    ):
        self.game = game
        self.pawn: Pawn = pawn
        self.personality: dict = personality
        # Every PID of the pilot (see _make_pid)
        self.pids: list[PID] = []

    def _make_pid(self, axis: str, angular: bool = True) -> PID:
        """
        Build one of the pilot's PIDs, on the personality's gains for its axis,
        with a normalised [-1, 1] output.

        :param axis: The axis whose gains to use ("yaw" reads yaw_kp, yaw_ki...)
        :param angular: Whether its error is an angle, wrapped to [-pi, pi]
        :return: The PID, also added to :attr:`pids`
        """
        pilot = self.personality["pilot"]
        pid = PID(
            Kp=pilot[f"{axis}_kp"],
            Ki=pilot[f"{axis}_ki"],
            Kd=pilot[f"{axis}_kd"],
            setpoint=0.0,
            starting_output=0.0,
            sample_time=pilot["sample_time_s"],
            error_map=safe_angle_rad if angular else None,
            time_fn=self.game.game_time.get_current_time,
            output_limits=(-1.0, 1.0),
        )
        self.pids.append(pid)
        return pid

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
        for pid in self.pids:
            pid.sample_time = None

    def set_on(
        self,
        **kwargs: Any,
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
        **kwargs: Any,
    ) -> tuple[float, ...]:
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
