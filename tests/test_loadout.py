"""
Unit tests for fighter loadouts (space_flight.weapons.loadout).
"""

from dataclasses import replace

import pytest

from space_flight.actors.ship import load_ship_configuration
from space_flight.weapons import ION, PHYSICAL
from space_flight.weapons.loadout import Loadout, default_loadout


def test_from_conf_reads_lasers_and_ordnance():
    """
    A configuration's loadout block gives the lasers' damage type and the
    ordnance stocks, in order.
    """
    loadout = Loadout.from_conf(
        {"lasers": ION, "ordnance": {"ion_torpedo": 2, "flare": 10}}
    )

    assert loadout.lasers == ION
    assert list(loadout.ordnance.items()) == [("ion_torpedo", 2), ("flare", 10)]


def test_from_conf_defaults_to_physical_lasers_and_no_ordnance():
    """
    An empty loadout block: physical lasers and nothing else.
    """
    assert Loadout.from_conf({}) == Loadout(lasers=PHYSICAL, ordnance={})


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"lasers": "plasma"}, ValueError),
        ({"ordnance": {"rocket": -1}}, ValueError),
        ({"ordnance": {"photon_torpedo": 1}}, FileNotFoundError),
    ],
)
def test_invalid_loadouts_are_rejected(kwargs, error):
    """
    Unknown damage types, negative stocks and unknown ordnance are refused.
    """
    with pytest.raises(error):
        Loadout(**kwargs)


def test_loadout_keeps_its_own_copy_of_the_stocks():
    """
    Changing the dictionary a loadout was built from does not change it.
    """
    stocks = {"rocket": 2}
    loadout = Loadout(ordnance=stocks)
    stocks["rocket"] = 5

    assert loadout.ordnance == {"rocket": 2}


def test_with_ordnance_replaces_adds_and_removes():
    """
    with_ordnance replaces a stock in place, adds new ordnance last and removes
    ordnance given a zero stock, leaving the original untouched.
    """
    loadout = Loadout(ordnance={"proton_torpedo": 4, "rocket": 2, "flare": 10})

    changed = loadout.with_ordnance(rocket=6, proton_torpedo=0, ion_torpedo=4)

    assert list(changed.ordnance.items()) == [
        ("rocket", 6),
        ("flare", 10),
        ("ion_torpedo", 4),
    ]
    assert loadout.ordnance == {"proton_torpedo": 4, "rocket": 2, "flare": 10}


def test_default_loadout_is_the_configured_one():
    """
    default_loadout reads the ship configuration, and replace() derives an
    ion-armed variant from it.
    """
    conf = load_ship_configuration("x-wing")["loadout"]

    loadout = default_loadout("x-wing")
    ion_loadout = replace(loadout, lasers=ION)

    assert loadout.lasers == conf["lasers"] == PHYSICAL
    assert loadout.ordnance == conf["ordnance"]
    assert ion_loadout.lasers == ION
    assert ion_loadout.ordnance == loadout.ordnance
