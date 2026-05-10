from space_flight.actors.capital_ship.sub_system import SubSystem


class TractorBeamProjector(SubSystem):
    """
    A class for capital ships tractor beam projectors
    """

    def __init__(self, game, parent):
        super().__init__(game=game, parent=parent)
