"""
Unit tests for TurretTactician (space_flight.ai.turret.turret_tactician).

TurretTactician can be instantiated directly since its __init__ delegates to
GenericTactician which only stores plain references.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np

from space_flight.ai import Intent, Personality
from space_flight.ai.turret.turret_tactician import TurretTactician


def make_turret_tactician(mock_game) -> TurretTactician:
    """
    Build a TurretTactician with a mocked game and pawn.

    :param mock_game: the mocked game object
    :return: a TurretTactician ready for testing
    """
    pawn = MagicMock()
    pawn.team = 1
    pawn.formation = None
    return TurretTactician(
        game=mock_game, pawn=pawn, personality=Personality.TURRET_DEFAULT
    )


def _configure_interactions_for_prey(
    mock_game,
    actor_index: int,
    prey_index: int,
    distance: float,
    interaction_active: bool = True,
    alignment: float = 1.0,
) -> None:
    """
    Configure mock game interactions so that evaluate_preys returns a
    meaningful score.

    :param mock_game: the mock game object to configure
    :param actor_index: slot index for the tactician's pawn
    :param prey_index: slot index for the potential prey actor
    :param distance: distance from actor to prey
    :param interaction_active: whether the pair is in the interact mask
    :param alignment: cos angle from actor forward to prey direction
    """
    n_slots = 4
    interact_mask = np.zeros(n_slots)
    interact_mask[prey_index] = 1.0 if interaction_active else 0.0

    distances = np.zeros(n_slots)
    distances[prey_index] = distance

    alignments = np.zeros(n_slots)
    alignments[prey_index] = alignment

    mock_game.interactions.get_actor_index_from_id.return_value = actor_index
    mock_game.interactions.interact.__getitem__ = MagicMock(return_value=interact_mask)
    mock_game.interactions.distances.__getitem__ = MagicMock(return_value=distances)
    mock_game.interactions.alignments.__getitem__ = MagicMock(return_value=alignments)

    prey_actor = MagicMock()
    prey_actor.id = uuid.uuid4()

    actors = [None] * n_slots
    actors[prey_index] = prey_actor
    mock_game.interactions.actors = actors


# ---------------------------------------------------------------------------
# update_intent — best prey found
# ---------------------------------------------------------------------------


def test_turret_tactician_high_score_prey_returns_engage():
    """
    When the highest-scoring prey exceeds min_engagement_score, update_intent
    must return ENGAGE with the prey's id.
    """
    mock_game = MagicMock()
    tactician = make_turret_tactician(mock_game)

    _configure_interactions_for_prey(
        mock_game,
        actor_index=0,
        prey_index=1,
        distance=200.0,  # well inside hunter_cutoff_distance of 900 m
        interaction_active=True,
        alignment=1.0,
    )

    intent, target_dict = tactician.update_intent()

    assert intent == Intent.ENGAGE
    assert "target_id" in target_dict


# ---------------------------------------------------------------------------
# update_intent — no prey
# ---------------------------------------------------------------------------


def test_turret_tactician_no_prey_returns_idle():
    """
    When no actor reaches the minimum engagement score, update_intent must
    return IDLE with an empty target dict.
    """
    mock_game = MagicMock()
    tactician = make_turret_tactician(mock_game)

    _configure_interactions_for_prey(
        mock_game,
        actor_index=0,
        prey_index=1,
        distance=200.0,
        interaction_active=False,  # no interaction → score stays at zero
        alignment=1.0,
    )

    intent, target_dict = tactician.update_intent()

    assert intent == Intent.IDLE
    assert target_dict == {}
