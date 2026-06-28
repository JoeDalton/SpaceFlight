"""
Session-level Panda3D configuration shared by all actor tests.

Setting ``window-type none`` and ``audio-library-name null`` before any
ShowBase is ever constructed keeps the test suite headless (no window,
no audio device) while still giving full access to the scene-graph API,
loaders, and math types from panda3d.core.
"""

from panda3d.core import loadPrcFileData

# Must be applied before the first ShowBase construction.
loadPrcFileData("", "window-type none")
loadPrcFileData("", "audio-library-name null")
