class BaseState:
    def __init__(self, app):
        self.app = app

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
        Called when leaving the state
        """
        raise NotImplementedError

    def pause(self):
        """
        Called when leaving the state
        """
        raise NotImplementedError

    def force_render(self):
        """
        Forces panda3d to render to avoid being stuck on ugly scene
        while the next one is loading
        """
        self.app.graphicsEngine.renderFrame()
        self.app.graphicsEngine.renderFrame()
