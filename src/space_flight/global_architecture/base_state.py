from direct.showbase.ShowBase import ShowBase


class BaseState:
    """
    Abstract base class for all application states.

    The :class:`~space_flight.global_architecture.simulator.StateManager`
    maintains a stack of :class:`BaseState` instances.  The topmost entry is
    the *active* state; the entries below it are either paused or running
    depending on :attr:`PAUSES_BELOW`.

    Concrete subclasses must implement :meth:`enter` and :meth:`exit`, and
    may override :meth:`pause` and :meth:`resume`.
    """

    # Set to False on subclasses that should not pause the state below them when pushed.
    PAUSES_BELOW: bool = True

    def __init__(self, app: ShowBase):
        self.app: ShowBase = app

    def enter(self):
        """
        Called by the state manager when this state becomes the active state.

        Create all UI elements, start tasks, and register event handlers here.
        """
        raise NotImplementedError

    def exit(self):
        """
        Called by the state manager when this state is popped off the stack.

        Destroy all UI elements, remove tasks, and unregister event handlers
        here to avoid resource leaks.
        """
        raise NotImplementedError

    def resume(self):
        """
        Called when this state returns to the top of the stack after the
        state above it was popped.

        Override to re-enable elements that were suppressed during
        :meth:`pause`.
        """
        pass

    def pause(self):
        """
        Called when a new state with PAUSES_BELOW = True is pushed on
        top of this one.

        Override to hide UI or stop tasks that should not run while the
        state is inactive.
        """
        pass

    def force_render(self):
        """
        Immediately render two frames so the display updates before the next
        state's assets begin loading.

        Call this at the end of :meth:`exit` to avoid flickering the old
        scene on screen while heavy resources are loaded.
        """
        self.app.graphicsEngine.renderFrame()
        self.app.graphicsEngine.renderFrame()
