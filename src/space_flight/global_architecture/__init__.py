from enum import Enum, auto


class GameStates(Enum):
    """
    Definition of the possile game states
    """

    SPLASH = auto()
    LOADING = auto()
    PLAYING = auto()
    PAUSED = auto()
