"""
Unit tests for the TargetingSystem subsystem.

A targeting system is a thin SubSystem that carries a fire-rate multiplier and a
placeholder model; the boosts it grants are exercised from the turret side (see
tests/test_turret.py). Here we only check it builds as a proper, targetable
subsystem of its ship and exposes its multiplier.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
from panda3d.core import NodePath

from space_flight.actors.capital_ship.sub_system import SubSystem
from space_flight.actors.capital_ship.targeting_system import TargetingSystem


def make_game_and_ship(team: int = 2):
    """
    Build a mock game and parent ship sufficient to run TargetingSystem.__init__.
    """
    game = MagicMock()
    game.destructibles.alive_objects = []
    game.method_lists = {}
    game.root_node = NodePath("root")
    ship = SimpleNamespace(
        team=team, node=NodePath("ship"), is_dead=False, speed=np.zeros(3)
    )
    ship.node.reparentTo(game.root_node)
    return game, ship


def test_targeting_system_is_a_targetable_subsystem():
    """
    A targeting system builds as a SubSystem of its ship: it takes the ship's
    team, exposes the "sub_system" category, registers with the interaction
    actors, and joins the destructibles.
    """
    game, ship = make_game_and_ship(team=2)

    targeting_system = TargetingSystem(game=game, parent=ship, hit_box_radius_m=6.0)

    assert isinstance(targeting_system, SubSystem)
    assert targeting_system.team == 2
    assert targeting_system.category == "sub_system"
    game.interactions.add_actor.assert_called_once_with(targeting_system)
    assert targeting_system in game.destructibles.alive_objects


def test_targeting_system_exposes_fire_rate_multiplier():
    """
    The configured fire-rate multiplier is stored for the turrets to read.
    """
    game, ship = make_game_and_ship()

    targeting_system = TargetingSystem(
        game=game, parent=ship, hit_box_radius_m=6.0, fire_rate_multiplier=3.0
    )

    assert targeting_system.fire_rate_multiplier == 3.0


def test_targeting_system_exposes_auto_aim_params():
    """
    The configured auto-aim tuning is stored for the turrets to feed into
    AutoAim.configure; when omitted it defaults to an empty dict (auto-aim
    defaults).
    """
    game, ship = make_game_and_ship()
    params = {"max_assist_angle_deg": 8.0, "target_lock_delay_s": 0.5}

    tuned = TargetingSystem(
        game=game, parent=ship, hit_box_radius_m=6.0, auto_aim_params=params
    )
    default = TargetingSystem(game=game, parent=ship, hit_box_radius_m=6.0)

    assert tuned.auto_aim_params == params
    assert default.auto_aim_params == {}


def test_targeting_system_builds_a_visible_model():
    """
    A targeting system attaches a placeholder model so it can be seen and locked
    onto; that model is loaded through the game's loader.
    """
    game, ship = make_game_and_ship()

    targeting_system = TargetingSystem(game=game, parent=ship, hit_box_radius_m=6.0)

    game.app.loader.loadModel.assert_called_once()
    assert targeting_system.model is not None
