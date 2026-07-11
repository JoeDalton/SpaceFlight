"""
Unit tests for CapitalShip._setup_shield: a capital ship may have no shield
generators, and without generators it gets no shield (even if a shield spec is
present in its config).

Instances bypass __init__ so only the shield-wiring guard is exercised, with no
loader or scene graph.
"""

from space_flight.actors.capital_ship import CapitalShip


def make_capital_ship_without_init(shield_generators) -> CapitalShip:
    ship = object.__new__(CapitalShip)
    ship.shield_generators = shield_generators
    return ship


def test_no_generators_yields_no_shield():
    """A ship with no shield generators gets no shield."""
    ship = make_capital_ship_without_init(shield_generators=[])

    ship._setup_shield(sub_systems_conf={})

    assert ship.shield is None


def test_shield_spec_without_generators_is_ignored():
    """
    A shield spec on a ship with no generators is ignored -- there is nothing to
    project the bubble, so no shield is built.
    """
    ship = make_capital_ship_without_init(shield_generators=[])

    ship._setup_shield(
        sub_systems_conf={"shield": {"health": 5000.0, "regen_rate": 25.0}}
    )

    assert ship.shield is None
