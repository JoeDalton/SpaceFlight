import numpy as np
from direct.showbase.ShowBaseGlobal import ClockObject, aspect2d
from direct.task import Task
from direct.showbase.ShowBase import ShowBase
from panda3d.core import TextNode


class HUD:
    """
    Defines the Heads-up display for KUI

    Creates an overlay of text displaying important
    flight parameters on screen.
    """

    def __init__(self, app: ShowBase):
        self.app = app

        self.hud = TextNode("HUD")
        self.hud.setSmallCaps(True)
        self.hud.setShadow(0.05, 0.05)
        self.hud.setShadowColor(0, 0, 0, 1)
        self.hud_textNodePath = aspect2d.attachNewNode(self.hud)
        self.hud_textNodePath.setScale(0.07)

        self.hud_textNodePath.reparentTo(self.app.a2dTopLeft)
        self.hud_textNodePath.setPos(0.05, 0, -0.1)

        self.fps_counter = TextNode("HUD")
        self.fps_counter.setSmallCaps(True)
        self.fps_counter.setShadow(0.05, 0.05)
        self.fps_counter.setShadowColor(0, 0, 0, 1)
        self.fps_textNodePath = aspect2d.attachNewNode(self.fps_counter)
        self.fps_textNodePath.setScale(0.07)

        self.fps_textNodePath.reparentTo(self.app.a2dTopRight)
        self.fps_textNodePath.setPos(-0.4, 0, -0.1)

        app.taskMgr.add(self.hud_update_task, "hud_update_task")

    def hud_update_task(self, task):
        """
        A task that gets the relevant informations from the dataflow
        and updates the text displayed in the HUD.
        """
        frame_rate = ClockObject.getGlobalClock().getAverageFrameRate()
        pos = self.app.camera.get_pos()   # in world coordinates
        hpr = self.app.camera.get_hpr()   # in world coordinates

        self.hud.setText(
            f"Position = {pos}\n"
            f"Orientation = {hpr}\n"
        )

        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        return Task.cont
