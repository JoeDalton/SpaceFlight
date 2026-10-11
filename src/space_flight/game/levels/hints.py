"""
Tutorial hints shared by the levels, naming the player's own key bindings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.ui.input_context import InputContext

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator


def power_hint(app: SpaceFlightSimulator, system: str) -> str:
    """
    How to divert power to a system, with the last used device's binding:
    its direct key if it has one (the keyboard's), or the power-cycling one.

    :param app: The simulator app (its bindings and input reader)
    :param system: ENGINES or LASERS (see space_flight.actors.energy)
    :return: The hint
    """
    direct = InputContext.key_label(app, "flight", f"energy_{system}")
    if direct:
        return f"Press [{direct}] to divert power to your {system}."
    cycle = InputContext.key_label(
        app, "flight", "cycle_energy", "the power-cycling key"
    )
    return f"Press [{cycle}] to cycle power until your {system} gauge brightens."
