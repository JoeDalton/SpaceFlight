from space_flight.actors.destructibles import Destructible


class SubSystem(Destructible):
    """
    A generic class for subsystems
    """

    def __init__(self, game, parent):
        super().__init__(game=game)
