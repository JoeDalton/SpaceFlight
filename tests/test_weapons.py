"""
Unit tests for the weapons package helpers (space_flight.weapons).
"""

from types import SimpleNamespace

import pytest

from space_flight.weapons import is_ion_vulnerable


def fighter(shield: float, engines: float, lasers: float) -> SimpleNamespace:
    """A fighter stand-in with these gauge levels."""
    return SimpleNamespace(
        category="fighter",
        shield_level=shield,
        energy=SimpleNamespace(engines=engines, lasers=lasers),
    )


@pytest.mark.parametrize(
    "target, vulnerable",
    [
        (fighter(100.0, 1.0, 1.0), True),
        (fighter(0.0, 0.0, 0.3), True),
        (fighter(0.0, 0.0, 0.0), False),
        (
            SimpleNamespace(
                category="capital_ship", shield=SimpleNamespace(is_enabled=True)
            ),
            True,
        ),
        (
            SimpleNamespace(
                category="capital_ship", shield=SimpleNamespace(is_enabled=False)
            ),
            False,
        ),
        (SimpleNamespace(category="capital_ship", shield=None), False),
        (SimpleNamespace(category="sub_system", is_disabled=False), True),
        (SimpleNamespace(category="sub_system", is_disabled=True), False),
        (SimpleNamespace(category="missile"), False),
        (SimpleNamespace(), False),
    ],
    ids=[
        "fighter_full",
        "fighter_lasers_left",
        "fighter_drained",
        "capital_shield_up",
        "capital_shield_down",
        "capital_unshielded",
        "subsystem_working",
        "subsystem_disabled",
        "ordnance",
        "unknown",
    ],
)
def test_is_ion_vulnerable(target, vulnerable):
    """
    Ion hits still work on a fighter with any gauge left, a capital ship whose
    bubble is up, and a working subsystem; never on anything else.
    """
    assert is_ion_vulnerable(target) is vulnerable
