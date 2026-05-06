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

    def clean(self):
        raise NotImplementedError
