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
