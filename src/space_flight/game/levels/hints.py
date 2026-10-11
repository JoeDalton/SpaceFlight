"""
Tutorial hints shared by the levels, naming the player's own key bindings.

Each helper returns a hint's text, for :meth:`Mission.hint
<space_flight.game.scenario.mission.Mission.hint>`. The HUD wraps it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.actors.energy import ENGINES, LASERS
from space_flight.actors.scan import SCAN_DURATION_S, SCAN_RANGE_M
from space_flight.ui.input_context import InputContext

if TYPE_CHECKING:
    from space_flight.global_architecture.simulator import SpaceFlightSimulator


def target_menu_hint(app: SpaceFlightSimulator, filter_name: str, purpose: str) -> str:
    """
    How to lock a target through the radial target menu.

    :param app: The simulator app (its bindings and input reader)
    :param filter_name: The menu's filter to point at, e.g. "Fighters"
    :param purpose: What locking does, e.g. "lock onto the formation leader"
    :return: The hint
    """
    radial_key = InputContext.key_label(
        app, "flight", "radial_menu", "the target-menu key"
    )
    loop_key = InputContext.key_label(
        app, "flight", "loop_target", "the cycle-target key"
    )
    return (
        f"Hold [{radial_key}] to open the target menu, point at {filter_name}, "
        f"then press [{loop_key}] to {purpose}."
    )


def waypoint_hint(app: SpaceFlightSimulator) -> str:
    """How to lock the next waypoint."""
    return target_menu_hint(app, "Waypoints", "lock onto your next waypoint")


def formation_hint(app: SpaceFlightSimulator) -> str:
    """How to lock an allied formation's leader, as it arrives."""
    return "Allied formation inbound! " + target_menu_hint(
        app, "Fighters", "lock onto the formation leader"
    )


def stay_close_hint(radius_m: float, who: str) -> str:
    """
    :param radius_m: How close to stay
    :param who: Whom to stay close to, e.g. "Blue squadron"
    :return: The hint
    """
    return f"Stay within {radius_m:.0f}m of any {who} ship."


def scan_hint(app: SpaceFlightSimulator) -> str:
    """How to scan a capital ship (see space_flight.actors.scan)."""
    return (
        target_menu_hint(app, "Capital ships", "lock a transport")
        + f" Close to {SCAN_RANGE_M:.0f}m and keep it ahead of you for "
        f"{SCAN_DURATION_S:.0f} seconds to scan it."
    )


def subsystem_hint(app: SpaceFlightSimulator, purpose: str) -> str:
    """
    How to target a ship's subsystems.

    :param purpose: What to target, e.g. "target the shield generators"
    """
    return target_menu_hint(app, "Subsystems", purpose)


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


def engine_power_hint(app: SpaceFlightSimulator) -> str:
    """Divert power to the engines, for speed."""
    return f"{power_hint(app, ENGINES)} More power, more speed."


def laser_power_hint(app: SpaceFlightSimulator) -> str:
    """Divert power to the lasers, for a fight."""
    return f"{power_hint(app, LASERS)} You'll need the firepower."
