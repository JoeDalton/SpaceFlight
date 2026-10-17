"""
Keep the screen saver and display sleep off while the game runs.
"""

import logging
import os
import subprocess
import sys

LOGGER = logging.getLogger()

_APP_NAME = "SpaceFlight"
_REASON = "Playing"

# Windows SetThreadExecutionState flags
_ES_CONTINUOUS = 0x80000000
_ES_DISPLAY_REQUIRED = 0x00000002


class IdleInhibitor:
    """
    Platform-specific screen-saver inhibition:

    - Linux: ``org.freedesktop.ScreenSaver.Inhibit`` over the D-Bus session
      bus (via jeepney). The daemon drops the inhibition when the connection
      closes, so a crash cannot leave it stuck.
    - Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED)``.
    - macOS: a ``caffeinate -d -w <pid>`` child, which also exits on its own
      when the game process ends.
    - Anything else: no-op.
    """

    def __init__(self):
        self._active = False
        # Linux
        self._connection = None
        self._address = None
        self._cookie = None
        # macOS
        self._caffeinate = None

    @property
    def active(self) -> bool:
        return self._active

    def acquire(self):
        """Start inhibiting the screen saver (no-op if already active)."""
        if self._active:
            return
        try:
            if sys.platform.startswith("linux"):
                self._acquire_linux()
            elif sys.platform == "win32":
                self._acquire_windows()
            elif sys.platform == "darwin":
                self._acquire_macos()
            else:
                return
        except Exception as error:  # noqa: BLE001 - must never break the game
            LOGGER.warning("Could not inhibit the screen saver: %s", error)
            self._close_linux_connection()
            return
        self._active = True

    def release(self):
        """Stop inhibiting the screen saver (no-op if not active)."""
        if not self._active:
            return
        self._active = False
        try:
            if sys.platform.startswith("linux"):
                self._release_linux()
            elif sys.platform == "win32":
                self._release_windows()
            elif sys.platform == "darwin":
                self._release_macos()
        except Exception as error:  # noqa: BLE001 - called at exit
            LOGGER.warning("Could not release the screen-saver inhibition: %s", error)
        finally:
            self._close_linux_connection()

    # -- Linux ---------------------------------------------------------------

    def _call_linux(self, method: str, signature: str, body: tuple):
        from jeepney import new_method_call
        from jeepney.wrappers import unwrap_msg

        reply = self._connection.send_and_get_reply(
            new_method_call(self._address, method, signature, body), timeout=2
        )
        return unwrap_msg(reply)

    def _acquire_linux(self):
        from jeepney import DBusAddress
        from jeepney.io.blocking import open_dbus_connection

        self._connection = open_dbus_connection(bus="SESSION")
        self._address = DBusAddress(
            "/org/freedesktop/ScreenSaver",
            bus_name="org.freedesktop.ScreenSaver",
            interface="org.freedesktop.ScreenSaver",
        )
        (self._cookie,) = self._call_linux("Inhibit", "ss", (_APP_NAME, _REASON))

    def _release_linux(self):
        self._call_linux("UnInhibit", "u", (self._cookie,))

    def _close_linux_connection(self):
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:  # noqa: BLE001
                pass
        self._connection = None
        self._address = None
        self._cookie = None

    # -- Windows -------------------------------------------------------------

    @staticmethod
    def _set_execution_state(flags: int):
        # Best effort: the return value (previous state, 0 on failure) is
        # not checked, as there is nothing useful to do if it fails.
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(flags)

    def _acquire_windows(self):
        self._set_execution_state(_ES_CONTINUOUS | _ES_DISPLAY_REQUIRED)

    def _release_windows(self):
        self._set_execution_state(_ES_CONTINUOUS)

    # -- macOS ---------------------------------------------------------------

    def _acquire_macos(self):
        self._caffeinate = subprocess.Popen(
            ["caffeinate", "-d", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _release_macos(self):
        caffeinate, self._caffeinate = self._caffeinate, None
        if caffeinate is not None:
            caffeinate.terminate()
            caffeinate.wait(timeout=2)
