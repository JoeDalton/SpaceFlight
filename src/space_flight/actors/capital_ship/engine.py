from space_flight.actors.capital_ship.sub_system import SubSystem


class Engine(SubSystem):
    """
    A class for capital ships engines
    """

    def __init__(self, game, parent):
        super().__init__(game=game, parent=parent)
