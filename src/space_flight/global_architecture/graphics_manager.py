"""
Central owner of all graphics/display options.

Responsibilities:

* **Window mode** — fullscreen vs windowed, and window size. Applied when the
  real game window opens after the splash screen (:meth:`open_game_window`),
  and to the live window when the settings menu saves
  (:meth:`apply_window_settings`).
The world's render pipeline is handled by WorldBuilder's.
The 2D layers (render2d / aspect2d — HUD, menus) are drawn straight into the
window, at its resolution.
"""

from __future__ import annotations

import logging
import sys
from time import sleep
from typing import TYPE_CHECKING

from panda3d.core import WindowProperties

from space_flight.utils import get_primary_monitor

if TYPE_CHECKING:
    from direct.task import Task

    from space_flight.global_architecture.simulator import SpaceFlightSimulator

LOGGER = logging.getLogger()


class GraphicsManager:
    """
    Applies the graphics settings to the running engine.
    """

    def __init__(self, app: SpaceFlightSimulator):
        self.app = app

    @property
    def settings(self) -> dict:
        """The current sanitised settings dict (owned by GraphicsSettings)."""
        return self.app.graphics_settings.config

    # ------------------------------------------------------------------
    # Window mode
    # ------------------------------------------------------------------

    def open_game_window(self):
        """
        Close the current window and open the real game window honouring the
        saved display mode/size.

        Called from :meth:`SplashState.exit`. The brief sleep gives a clean
        cut between the splash and game windows rather than a flicker.
        """
        old_win = self.app.win
        self.app.closeWindow(old_win)
        sleep(0.3)
        self.app.openDefaultWindow(props=self._build_window_props())
        self.app.set_background_color(0, 0, 0)

    def apply_window_settings(self):
        """
        Apply the saved display mode/size to the live window without recreating
        it. Used by the graphics settings menu on save; the world's settings
        (render scale and anti-aliasing among them) wait for the next level
        load.
        """
        self.app.win.requestProperties(self._build_window_props())

    def _build_window_props(self) -> WindowProperties:
        """
        Build :class:`WindowProperties` from the saved display settings.
        """
        props = WindowProperties()
        props.setUndecorated(False)
        props.setFullscreen(False)

        # Get the proper monitor to display on
        monitor = get_primary_monitor()

        # Set window size
        if self.settings["display"]["mode"] != "fullscreen":
            w, h = self.settings["display"]["windowed_size"]
            width, height = int(w), int(h)
        else:
            width, height = monitor.width, monitor.height
            # We wait 0.5 seconds to give the window manager time to process step 1
            # and position the window. If we send the EWMH hint and go fullscreen
            # too quickly, the WM might not have the window where we expect it yet.
            self.app.taskMgr.doMethodLater(
                0.5, self.go_full_screen_task, "fs", appendTask=True
            )
        props.setSize(width, height)

        # Center window on primary monitor
        x = monitor.x + (monitor.width - width) // 2
        y = monitor.y + (monitor.height - height) // 2
        props.setOrigin(x, y)

        return props

    def go_full_screen_task(self, task: Task):
        """
        Delayed fullscreen change for special linux treatment

        Args:
            task: The Panda3D task object (returned as task.done to signal completion).
        """

        # Send a hint to the windows manager, naming the target monitor.
        # This must happen before we request fullscreen.
        # Linux only.
        if sys.platform.startswith("linux"):
            self.set_fullscreen_monitor_linux(idx=0)  # Always the primary monitor

        # Now request fullscreen
        props = WindowProperties()
        props.setFullscreen(True)
        self.app.win.requestProperties(props)

        # Don't repeat
        return task.done

    def set_fullscreen_monitor_linux(self, idx: int = 0):
        """
        Send a hint to the windows manager, naming the target monitor.
        This must happen before we request fullscreen.
        Linux only.

        How it works:
            - Opens a connection to the X11 display.
            - Creates a ClientMessage event with the _NET_WM_FULLSCREEN_MONITORS atom.
            - The data payload is [index, index, index, index, 1]:
                * First four values: top, bottom, left, right monitor indices.
                All set to the same `index` because we want one monitor.
                * Final value: 1 = "this request comes from the application"
                (vs. from the user; needed for the WM to honor it).
            - Sends the event to the root window with SubstructureRedirect.
            - Flushes to ensure the X server receives it immediately.

        :param idx: The index of the monitor to use for fullscreen (0 is primary)
        """
        # Get the window's X11 ID (needed for the EWMH hint).
        xid = self.app.win.getWindowHandle().getIntHandle()
        from Xlib import X, display, protocol

        d = display.Display()
        try:
            # Create a ClientMessage event targeting the specific window.
            event = protocol.event.ClientMessage(
                window=d.create_resource_object("window", xid),
                client_type=d.intern_atom("_NET_WM_FULLSCREEN_MONITORS"),
                # data=(32, [top, bottom, left, right, source])
                # Using the same index for all four sides means
                # "fullscreen on this monitor".
                # The 1 at the end means "application" (vs. "user"),
                # so the WM takes us seriously.
                data=(32, [idx] * 4 + [1]),
            )
            # Send the message to the root window (required for EWMH)
            # SubstructureRedirectMask lets us send it even though we don't own the root
            # SubstructureNotifyMask ensures the WM hears about structure changes
            d.screen().root.send_event(
                event, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask
            )
            # Flush to make sure the X server processes it now, not later.
            d.flush()
        finally:
            # Always close the display connection to avoid resource leaks.
            d.close()

    def force_render(self):
        """
        Immediately render two frames so the display updates before heavy
        loading starts.

        Typically called at the end of :meth:`exit`, so the old scene does not
        linger on screen while the next state loads its assets.
        """
        self.app.graphicsEngine.renderFrame()
        self.app.graphicsEngine.renderFrame()
