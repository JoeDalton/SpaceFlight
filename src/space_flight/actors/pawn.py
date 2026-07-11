import uuid
from typing import Any

import numpy as np


class Pawn:
    """
    A generic class for controllable game elements
    """

    def __init__(
        self,
        game,
        parent: Any,
        team: int = 0,
    ):
        self.game = game
        self.parent = parent
        self.is_dead = False
        self.is_clean = False
        self.id = uuid.uuid4()
        self.team = team
        self.formation = None

        self.right = np.zeros(3)
        self.forward = np.zeros(3)
        self.up = np.zeros(3)
        self.speed = np.zeros(3)
        self.position = np.zeros(3)

        # How manoeuverable this actor is, in [0, 1], precomputed once at init and
        # read by attackers' tacticians (a stationary structure is 0, an agile
        # fighter ~1). It is a strategic capability signal, NOT the instantaneous
        # speed. Ships override it from their kinematic limits; mounted subsystems
        # inherit their host's. Bare pawns/structures keep 0.
        self.mobility = 0.0

        # Initialize tactician and autoaim targets
        self.target = None
        self.target_id = None
        self.target_idx = None

    @property
    def shield_level(self) -> float:
        """
        The actor's current shield strength, as a uniform read across every
        target type (fighters keep a float shield, capital ships a Shield object,
        many actors none). Overridden by shielded actors; 0 by default.

        :return: The current shield strength (never negative)
        """
        return 0.0

    def clean(self):
        if not self.is_clean:
            self.target = None
            self.target_id = None
            self.target_idx = None
