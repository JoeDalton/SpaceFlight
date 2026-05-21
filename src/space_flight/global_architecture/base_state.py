from direct.showbase.ShowBase import ShowBase


class BaseState:
    def __init__(self, app: ShowBase):
        self.app: ShowBase = app

    def enter(self):
        """
        Called when state becomes active
        """
        raise NotImplementedError

    def exit(self):
        """
        Called when leaving the state
        """
        raise NotImplementedError

    def resume(self):
        """
        Called when resuming the state
        """
        raise NotImplementedError

    def pause(self):
        """
        Called when pausing the state
        """
        raise NotImplementedError

    def force_render(self):
        """
        Forces panda3d to render to avoid being stuck on ugly scene
        while the next one is loading
        """
        self.app.graphicsEngine.renderFrame()
        self.app.graphicsEngine.renderFrame()
