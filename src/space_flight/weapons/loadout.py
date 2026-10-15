"""
Fighter loadouts: what a fighter's cannons fire, and the ordnance it carries.

Every fighter's configuration holds its default loadout::

    loadout:
      lasers: physical  # or ion
      ordnance:  # name: stock, in secondary weapon cycling order
        proton_torpedo: 4
        flare: 10

A level can give a fighter another one, built from the default::

    from dataclasses import replace

    ion_x_wing = replace(default_loadout("x-wing"), lasers=ION)
    ion_x_wing = ion_x_wing.with_ordnance(proton_torpedo=0, ion_torpedo=4)
    Player(game, ship_type="x-wing", loadout=ion_x_wing)
    WaveSpec(..., ship_model="x-wing", loadouts={"x-wing": ion_x_wing})
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from space_flight.actors.ship import load_ship_configuration
from space_flight.weapons import DAMAGE_TYPES, PHYSICAL
from space_flight.weapons.ordnance_launcher import load_ordnance_configuration


@dataclass(frozen=True)
class Loadout:
    """
    A fighter's weapons.

    :param lasers: The cannons' damage type: PHYSICAL or ION
    :param ordnance: Stock of each ordnance carried, by name (its configuration
        directory), in secondary weapon cycling order
    :raises ValueError: for an unknown damage type or a negative stock
    :raises FileNotFoundError: for an ordnance without a configuration
    """

    lasers: str = PHYSICAL
    ordnance: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.lasers not in DAMAGE_TYPES:
            raise ValueError(f"Loadout: unknown laser damage type {self.lasers!r}")
        for name, stock in self.ordnance.items():
            if stock < 0:
                raise ValueError(f"Loadout: negative stock of {name!r}")
            load_ordnance_configuration(name)
        # A copy of its own, so the caller's dictionary can change freely
        object.__setattr__(self, "ordnance", dict(self.ordnance))

    @classmethod
    def from_conf(cls, conf: Mapping) -> Loadout:
        """
        :param conf: A ship configuration's loadout block
        :return: The loadout it describes (physical lasers if unspecified)
        """
        return cls(
            lasers=conf.get("lasers", PHYSICAL), ordnance=conf.get("ordnance", {})
        )

    def with_ordnance(self, **stocks: int) -> Loadout:
        """
        :param stocks: New stocks by ordnance name: replacing the current one,
            in place, or added last; 0 removes that ordnance
        :return: A copy of this loadout with these stocks
        """
        ordnance = {**self.ordnance, **stocks}
        return replace(
            self,
            ordnance={name: stock for name, stock in ordnance.items() if stock > 0},
        )


def default_loadout(ship_type: str) -> Loadout:
    """
    :param ship_type: A fighter model
    :return: Its loadout, as configured
    """
    return Loadout.from_conf(load_ship_configuration(ship_type).get("loadout", {}))
