import numpy as np
from direct.showbase.ShowBaseGlobal import ClockObject, aspect2d
from direct.showbase.ShowBase import ShowBase
from panda3d.core import TextNode


class HUD:
    """
    Creates an overlay of text displaying important
    simulation parameters on screen.
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
        A task that gets the relevant informations from the sim
        and updates the text displayed in the HUD.
        """
        frame_rate = ClockObject.getGlobalClock().getAverageFrameRate()

        self.hud.setText(""
            # f"Cam Position = {self.app.camera.get_pos()}\n"
            # f"Cam Orientation = {self.app.camera.get_hpr()}\n"
            # f"Player Position = {self.app.player.ship.state[0:3]}\n"
            # f"Player Orientation = {self.app.player.ship.state[3:7]}\n"
            # f"Player Speed = {np.linalg.norm(self.app.player.ship.state[7:10])}\n"
            # f"Player Rot. rate = {np.rad2deg(self.app.player.ship.pqr)}\n"
            # f"Player Thrust = {self.app.player.ship.scalar_thrust}\n"
            

        )

        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        return task.cont
