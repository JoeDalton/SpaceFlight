import numpy as np


class Pawn:
    """
    A generic class for controlable game elements
    """

    def __init__(self):
        self.right = np.zeros(3)
        self.forward = np.zeros(3)
        self.up = np.zeros(3)
        self.speed = np.zeros(3)
        self.position = np.zeros(3)
        self.id = None
        self.formation = None
