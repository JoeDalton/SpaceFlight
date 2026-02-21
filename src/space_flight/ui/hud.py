import numpy as np
from direct.gui.DirectGui import DirectLabel
from direct.showbase.ShowBaseGlobal import aspect2d, render2d
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

    def __init__(self, game):
        self.game = game

        self.hud = TextNode("HUD")
        self.hud.setSmallCaps(True)
        self.hud.setShadow(0.05, 0.05)
        self.hud.setShadowColor(0, 0, 0, 1)
        self.hud_textNodePath = aspect2d.attachNewNode(self.hud)
        self.hud_textNodePath.setScale(0.07)

        self.hud_textNodePath.reparentTo(self.game.app.a2dTopLeft)
        self.hud_textNodePath.setPos(0.05, 0, -0.1)

        self.fps_counter = TextNode("HUD")
        self.fps_counter.setSmallCaps(True)
        self.fps_counter.setShadow(0.05, 0.05)
        self.fps_counter.setShadowColor(0, 0, 0, 1)
        self.fps_textNodePath = aspect2d.attachNewNode(self.fps_counter)
        self.fps_textNodePath.setScale(0.07)

        self.fps_textNodePath.reparentTo(self.game.app.a2dTopRight)
        self.fps_textNodePath.setPos(-0.4, 0, -0.1)

        game.app.taskMgr.add(self.hud_update_task, "hud_update_task")

    def hud_update_task(self, task):
        """
        A task that gets the relevant informations from the sim
        and updates the text displayed in the HUD.
        """
        frame_rate = self.game.game_time.get_average_frame_rate()

        player_text = (
            ""
            "Player Speed = "
            f"{np.linalg.norm(self.game.player.ship.state[7:10]):.1f}m/s\n"
            f"Player health = {self.game.player.ship.health:.1f}\n"
            f"Player shield = {self.game.player.ship.shield:.1f}\n"
            f"Time = {self.game.game_time.get_current_time():.0f}\n"
        )
        try:
            bot_text = (
                "Lead Bot angle to target = "
                f"{self.game.lead_bot.pilot.angle_to_target_deg:.1f}°\n"
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
                "Lead Bot health = "
                f"{self.game.lead_bot.ship.health:.1f}\n"
                "Lead Bot shield = "
                f"{self.game.lead_bot.ship.shield:.1f}\n"
                "Lead Bot throttle = "
                f"{self.game.lead_bot.pilot.throttle:.4f}\n"
                "Lead Bot Speed = "
                f"{np.linalg.norm(self.game.lead_bot.ship.state[7:10]):.1f}m/s\n"
                "\n"
                # "Chase Bot angle to target = "
                # f"{self.game.chase_bot.pilot.angle_to_target_deg:.1f}°\n"
                # "Chase Bot throttle = "
                # f"{self.game.chase_bot.pilot.throttle:.4f}\n"
                # "Chase Bot Speed = "
                # f"{np.linalg.norm(self.game.chase_bot.ship.state[7:10]):.1f}m/s\n"
            )
        except AttributeError:
            bot_text = ""
        hud_text = player_text + bot_text

        self.hud.setText(hud_text)

        self.fps_counter.setText(f"FPS = {frame_rate:.0f}")

        return task.cont


class TargetHUD:
    def __init__(self, game):
        # TODO use Interactions instead of a player target list.
        # Allow filtering on team
        self.game = game
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
            self.game.app.loader.loadTexture(
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

        # TODO: This should be in "input_system"
        game.app.taskMgr.add(self.target_hud_update_task, "target_hud_update_task")

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

        # TODO: This should be in "input_system"
        self.game.app.accept(
            self.game.key_bindings["switch_target"], self.switch_target
        )

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

            cam = self.game.app.cam
            lens = self.game.app.camLens

            aspect = self.game.app.getAspectRatio()
            self.aspect.setScale(1, 1, aspect)

            # World position of target
            target_pos = self.target.state[:3]
            world_pos = Point3(*target_pos)

            # Convert to camera space
            cam_space_pos = cam.getRelativePoint(self.game.app.render, world_pos)
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
            distance = (
                world_pos - self.game.app.camera.getPos(self.game.app.render)
            ).length()
            self.distance_label["text"] = f"{int(distance/10)*10} m"

        return task.cont

    def switch_target(self):
        self.target_idx = (self.target_idx + 1) % len(
            self.game.player.available_targets
        )
        target_dict = self.game.player.available_targets[self.target_idx]
        target, target_name = list(target_dict.items())[0]
        self.set_target(target=target, target_name=target_name)

    def set_target(self, target, target_name: str = ""):
        self.target = target
        self.name_label["text"] = target_name
