import numpy as np
from direct.showbase.ShowBaseGlobal import ClockObject, aspect2d, globalClock, render2d
from direct.showbase.ShowBase import ShowBase

from panda3d.core import TextNode, Vec3, Point2, Point3, NodePath, CardMaker, TransparencyAttrib
from direct.gui.DirectGui import DirectFrame, DirectLabel

EDGE_DEFAULT = 0.94
EDGE_LOW = 0.88
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
            f"Player Speed = {np.linalg.norm(self.app.player.ship.state[7:10]):.1f}m/s\n"
            # f"Player Rot. rate = {np.rad2deg(self.app.player.ship.pqr)}\n"
            # f"Player Thrust = {self.app.player.ship.scalar_thrust}\n"
            f"Time = {globalClock.getFrameTime()}\n"
            f"Bot mode = {self.app.bot.mode}\n"
            f"Bot angle to target = {self.app.bot.autopilot.angle_to_target_deg:.1f}°\n"
            # f"Bot target_x = {self.app.bot.autopilot.target_x}\n"
            # f"Bot target_y = {self.app.bot.autopilot.target_y}\n"
            # f"Bot target_z = {self.app.bot.autopilot.target_z}\n"
            # f"Yaw_error_deg = {self.app.bot.autopilot.yaw_error}\n"
            # f"Pitch_error_deg = {self.app.bot.autopilot.pitch_error}\n"
            # f"Roll_error_deg = {self.app.bot.autopilot.roll_error}\n"
            # f"yaw_rate_command = {self.app.bot.autopilot.yaw_rate_command}\n"
            # f"pitch_rate_command = {self.app.bot.autopilot.pitch_rate_command}\n"
            # f"roll_rate_command = {self.app.bot.autopilot.roll_rate_command}\n"
            # f"yaw_rate = {self.app.bot.autopilot.yaw_rate}\n"
            # f"pitch_rate = {self.app.bot.autopilot.pitch_rate}\n"
            # f"roll_rate = {self.app.bot.autopilot.roll_rate}\n"
            f"Bot throttle = {self.app.bot.autopilot.throttle:.4f}\n"
            #f"Next waypoint idx = {self.app.bot.next_waypoint_idx}\n"
            f"Bot Speed = {np.linalg.norm(self.app.bot.ship.state[7:10]):.1f}m/s\n"
            #f"Distance to waypoint = {self.app.bot.distance_to_waypoint:.1f}m\n"
            #f"Next waypoint = {self.app.bot.waypoints[min(len(self.app.bot.waypoints)-1, self.app.bot.next_waypoint_idx)]}\n"
            # f"Bot position = {self.app.bot.ship.state[:3]}\n"

        )

        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        return task.cont

class TargetHUD:
    def __init__(self, app: ShowBase):

        self.app = app

        # Prepare target indicator atachment and aspect ratio correction
        self.root = NodePath("targetHudRoot")
        self.root.reparentTo(render2d)

        self.aspect = NodePath("aspectFix")
        self.aspect.reparentTo(self.root)

        # Define target indicator
        cm = CardMaker("targetBox")
        cm.setFrame(-0.038, 0.038, -0.03, 0.03)

        self.square = NodePath(cm.generate())
        self.square.setTexture(self.app.loader.loadTexture("models/UI/target_indicator_white.png"))
        self.square.setTransparency(TransparencyAttrib.MAlpha)
        self.square.reparentTo(self.aspect)

        # Define distance label
        self.label = DirectLabel(
            text="",
            scale=0.04,
            pos=(0, 0, -0.06),
            parent=self.aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1)
        )

        app.taskMgr.add(self.target_hud_update_task, "target_hud_update_task")

    def set_target(self, target):
        self.target = target

    def target_hud_update_task(self, task):
        cam = self.app.cam
        lens = self.app.camLens

        aspect = self.app.getAspectRatio()
        self.aspect.setScale(1, 1, aspect)

        # World position of target
        target_pos = self.target.state[:3]
        world_pos = Point3(*target_pos)

        # Convert to camera space
        cam_space_pos = cam.getRelativePoint(self.app.render, world_pos)
        screen_pos = Point2()
        lens.project(cam_space_pos, screen_pos)

        
        # Default case: target is ahead, just take the projection
        indic_x = screen_pos.x
        indic_z = screen_pos.y
        if cam_space_pos.y <= 0:
            # Target is behind, so the projection could fall inside the screen,
            # but we want the indicator to stay clamped to the edges of the screen
            norm = np.sqrt(indic_x**2 + indic_z**2)
            if norm > 1e-5:
                two_norm_inv = 2 / norm
                indic_x *= two_norm_inv
                indic_z *= two_norm_inv
            else:
                indic_x = EDGE_DEFAULT
                indic_z = 0.0         
            # TODO: This does not work as I want it. the indicator changes edges 3 times
            # in one loop, when it should change only once.
            # To be investigated, although it's not absolutely critical

        # Clamp to edges of screen
        indic_x = max(min(indic_x, EDGE_DEFAULT), -EDGE_DEFAULT)
        indic_z = max(min(indic_z, EDGE_DEFAULT), -EDGE_LOW)

        self.root.setPos(indic_x, 0, indic_z)

        # Find distance and write it below the box
        distance = (world_pos - self.app.camera.getPos(self.app.render)).length()
        self.label["text"] = f"{int(distance)} m"

        return task.cont