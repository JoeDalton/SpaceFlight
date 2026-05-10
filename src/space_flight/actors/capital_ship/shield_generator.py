from space_flight.actors.capital_ship.sub_system import SubSystem


class ShieldGenerator(SubSystem):
    """
    A class for external shield generators
    """

    def __init__(self, game, parent):
        super().__init__(game=game, parent=parent)
