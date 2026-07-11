class Trihedron:
    def __init__(self, game, parent, scale: int = 10):
        axis = game.app.loader.loadModel("zup-axis")
        # make sure it will be drawn above all other elements
        axis.setDepthTest(False)
        axis.setBin("fixed", 0)
        axis.setScale(scale)
        axis.reparentTo(parent)
        axis.setPos(0, 0, 0)
