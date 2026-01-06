import numpy as np
from direct.gui.DirectGui import DirectLabel
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject, aspect2d, globalClock, render2d
from panda3d.core import (
    CardMaker,
    NodePath,
    Point2,
    Point3,
    TextNode,
    TransparencyAttrib,
)

from space_flight import DATAFILES_PATH

EDGE_HORIZONTAL = 0.94
EDGE_VERTICAL = 0.88


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

        player_text = (
            ""
            # f"Cam Position = {self.app.camera.get_pos()}\n"
            # f"Cam Orientation = {self.app.camera.get_hpr()}\n"
            # f"Player Position = {self.app.player.ship.state[0:3]}\n"
            # f"Player Orientation = {self.app.player.ship.state[3:7]}\n"
            "Player Speed = "
            f"{np.linalg.norm(self.app.player.ship.state[7:10]):.1f}m/s\n"
            # f"Player Rot. rate = {np.rad2deg(self.app.player.ship.pqr)}\n"
            # f"Player Thrust = {self.app.player.ship.scalar_thrust}\n"
            f"Time = {globalClock.getFrameTime():.0f}\n"
        )
        try:
            bot_text = (
                "Bot angle to target = "
                f"{self.app.bot2.pilot.angle_to_target_deg:.1f}°\n"
                # f"Bot target_x = {self.app.bot.pilot.target_x}\n"
                # f"Bot target_y = {self.app.bot.pilot.target_y}\n"
                # f"Bot target_z = {self.app.bot.pilot.target_z}\n"
                # f"Yaw_error_deg = {self.app.bot.pilot.yaw_error}\n"
                # f"Pitch_error_deg = {self.app.bot.pilot.pitch_error}\n"
                # f"Roll_error_deg = {self.app.bot.pilot.roll_error}\n"
                # f"yaw_rate_command = {self.app.bot.pilot.yaw_rate_command}\n"
                # f"pitch_rate_command = {self.app.bot.pilot.pitch_rate_command}\n"
                # f"roll_rate_command = {self.app.bot.pilot.roll_rate_command}\n"
                # f"yaw_rate = {self.app.bot.pilot.yaw_rate}\n"
                # f"pitch_rate = {self.app.bot.pilot.pitch_rate}\n"
                # f"roll_rate = {self.app.bot.pilot.roll_rate}\n"
                f"Bot throttle = {self.app.bot2.pilot.throttle:.4f}\n"
                # f"Next waypoint idx = {self.app.bot.next_waypoint_idx}\n"
                f"Bot Speed = {np.linalg.norm(self.app.bot2.ship.state[7:10]):.1f}m/s\n"
                f"Distance to waypoint = {self.app.bot2.navigator.distance_to_waypoint_m:.1f}m\n"
                f"Next waypoint = {self.app.bot2.navigator.next_waypoint_idx}\n"
                # f"Bot position = {self.app.bot2.ship.state[:3]}\n"
            )
        except AttributeError:
            bot_text = ""
        hud_text = player_text + bot_text

        self.hud.setText(hud_text)

        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        return task.cont


class TargetHUD:
    def __init__(self, app: ShowBase):
        self.app = app
        self.target_idx = 0
        self.target = None

        # Prepare target indicator atachment and aspect ratio correction
        self.root = NodePath("targetHudRoot")
        self.root.reparentTo(render2d)

        self.aspect = NodePath("aspectFix")
        self.aspect.reparentTo(self.root)

        # Define target indicator
        cm = CardMaker("targetBox")
        cm.setFrame(-0.038, 0.038, -0.03, 0.03)

        self.square = NodePath(cm.generate())
        self.square.setTexture(
            self.app.loader.loadTexture(
                DATAFILES_PATH / "models/UI/target_indicator_white.png"
            )
        )
        self.square.setTransparency(TransparencyAttrib.MAlpha)
        self.square.reparentTo(self.aspect)

        # Define distance label
        self.distance_label = DirectLabel(
            text="",
            scale=0.04,
            pos=(0, 0, -0.06),
            parent=self.aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )
        # Define name label
        self.name_label = DirectLabel(
            text="",
            scale=0.02,
            pos=(0, 0, 0.04),
            parent=self.aspect,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
        )

        app.taskMgr.add(self.target_hud_update_task, "target_hud_update_task")

        # Make sure the targeting HUD is rendered above other UI things
        self.square.setDepthTest(False)
        self.square.setDepthWrite(False)
        self.square.setBin("fixed", 10)

        self.distance_label.setDepthTest(False)
        self.distance_label.setDepthWrite(False)
        self.distance_label.setBin("fixed", 10)

        self.name_label.setDepthTest(False)
        self.name_label.setDepthWrite(False)
        self.name_label.setBin("fixed", 10)

        self.app.accept(self.app.key_bindings["switch_target"], self.switch_target)

    def target_hud_update_task(self, task):
        if self.target is None:
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
        elif self.target.is_dead:
            self.target = None
            self.target_idx = 0
            self.distance_label.hide()
            self.name_label.hide()
            self.square.hide()
        else:
            self.distance_label.show()
            self.name_label.show()
            self.square.show()

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
                    indic_x = EDGE_HORIZONTAL
                    indic_z = 0.0
                # TODO: This does not work as I want it. the indicator changes edges
                # 3 times in one loop, when it should change only once.
                # To be investigated, although it's not absolutely critical

            # Clamp to edges of screen
            indic_x = max(min(indic_x, EDGE_HORIZONTAL), -EDGE_HORIZONTAL)
            indic_z = max(min(indic_z, EDGE_VERTICAL), -EDGE_VERTICAL)

            self.root.setPos(indic_x, 0, indic_z)

            # Find distance and write it below the box
            distance = (world_pos - self.app.camera.getPos(self.app.render)).length()
            self.distance_label["text"] = f"{int(distance/10)*10} m"

        return task.cont

    def switch_target(self):
        self.target_idx = (self.target_idx + 1) % len(self.app.player.available_targets)
        target_dict = self.app.player.available_targets[self.target_idx]
        target, target_name = list(target_dict.items())[0]
        self.set_target(target=target, target_name=target_name)

    def set_target(self, target, target_name: str = ""):
        self.target = target
        self.name_label["text"] = target_name
