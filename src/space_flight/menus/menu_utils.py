import random
from collections.abc import Callable

from direct.gui.DirectGui import (
    DGG,
    DirectButton,
    DirectFrame,
    DirectLabel,
    OkCancelDialog,
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject
from panda3d.core import TextNode

from space_flight import DATAFILES_PATH


class ProgressBar:
    """
    A lean progress bar that attaches to the bottom of its parent and prints
    blurbs above
    """

    def __init__(
        self,
        app: ShowBase,
        parent,
        blurbs: list[str] = [""],
        blurb_update_delay_s: float = 2.0,
        bar_height: float = 0.01,
    ):
        self.app = app

        # Create the progress bar object
        bottom_left, top_right = parent.getTightBounds()
        self.bar_width = top_right.x - bottom_left.x
        self.bar_height = bar_height
        self.bar = DirectFrame(
            frameColor=(1, 1, 1, 1),
            frameSize=(0, 0, 0, self.bar_height),
            pos=(bottom_left.x, 0, bottom_left.z),
            parent=self.app.aspect2d,
        )

        # Create the blurb label
        self.blurbs = blurbs
        self.last_blurb_update = ClockObject.getGlobalClock().getFrameTime()
        self.blurb_update_delay_s = blurb_update_delay_s
        self.blurb_label = DirectLabel(
            text=random.choice(self.blurbs),
            scale=(0.08 * 544 / 1280, 0.08, 0.08),
            pos=(0, 0, -0.9),
            parent=parent,
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_align=TextNode.ACenter,
            frameSize=(0, 0, 0, 0),
        )

        self.update(value=0.0)

    def update(self, value: float):
        """
        Updates the progress bar's length and
        updates the blurb if enough time has passed

        :param value: The progress value [0,1]
        """
        if (
            ClockObject.getGlobalClock().getFrameTime() - self.last_blurb_update
            >= self.blurb_update_delay_s
        ):
            self.last_blurb_update = ClockObject.getGlobalClock().getFrameTime()
            blurb = random.choice(self.blurbs)
            self.blurb_label["text"] = blurb

        self.bar["frameSize"] = (0, self.bar_width * value, 0, self.bar_height)

    def destroy(self):
        """
        Destroys all GUI object
        """
        self.bar.destroy()
        self.blurb_label.destroy()


class MenuModels:
    """
    A class to hold the models used in menus
    """

    def __init__(
        self,
        app: ShowBase,
    ):
        # Dialog box background
        DGG.setDefaultDialogGeom(DATAFILES_PATH / "menus" / "dialog.png")
        # Button model
        button_map = app.loader.loadModel(DATAFILES_PATH / "menus" / "button_map.egg")
        self.button_geom = (
            button_map.find("**/ready"),
            button_map.find("**/click"),
            button_map.find("**/hover"),
            button_map.find("**/disabled"),
        )
        # Scroll bar models
        thumb_map = app.loader.loadModel(DATAFILES_PATH / "menus" / "thumb_map.egg")
        self.thumb_geom = (
            thumb_map.find("**/thumb_ready"),
            thumb_map.find("**/thumb_click"),
            thumb_map.find("**/thumb_hover"),
            thumb_map.find("**/thumb_disabled"),
        )
        inc_map = app.loader.loadModel(DATAFILES_PATH / "menus" / "inc_map.egg")
        self.inc_geom = (
            inc_map.find("**/inc_ready"),
            inc_map.find("**/inc_click"),
            inc_map.find("**/inc_hover"),
            inc_map.find("**/inc_disabled"),
        )
        dec_map = app.loader.loadModel(DATAFILES_PATH / "menus" / "dec_map.egg")
        self.dec_geom = (
            dec_map.find("**/dec_ready"),
            dec_map.find("**/dec_click"),
            dec_map.find("**/dec_hover"),
            dec_map.find("**/dec_disabled"),
        )


class CustomOKDialog(OkCancelDialog):
    def __init__(self, app: ShowBase, text: str, command: Callable, parent=None):
        super().__init__(parent=parent)
        # Personalizable items
        self["text"] = text
        self["command"] = command

        # Common parameters
        self["pos"] = (0, 0, 0.25)
        self["text_fg"] = (0.898, 0.839, 0.730, 1.0)
        self["text_shadow"] = (0, 0, 0, 0.75)
        self["text_shadowOffset"] = (0.05, 0.05)
        self["text_scale"] = (0.05,)
        self["text_align"] = (TextNode.ACenter,)
        self["fadeScreen"] = (0.65,)
        self["frameColor"] = ((0.3, 0.3, 0.3, 1),)
        self["button_geom"] = (app.menu_models.button_geom,)
        self["button_scale"] = (0.15,)
        self["button_text_scale"] = (0.35,)
        self["button_text_align"] = (TextNode.ALeft,)
        self["button_text_fg"] = ((0.898, 0.839, 0.730, 1.0),)
        self["button_text_pos"] = ((-0.9, -0.125),)
        self["button_relief"] = (1,)
        self["button_pad"] = ((0.01, 0.01),)
        self["button_frameColor"] = ((0, 0, 0, 0),)
        self["button_frameSize"] = ((-1.0, 1.0, -0.25, 0.25),)
        self["button_pressEffect"] = (True,)
        self.setTransparency(True)
        self.configureDialog()
        scale = self["image_scale"]
        self["image_scale"] = (scale[0] / 2.0, scale[1], scale[2] / 2.0)
        self["text_pos"] = (self["text_pos"][0], self["text_pos"][1] + 0.06)


class CustomButton:
    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float],
        command: Callable,
        text: str,
        scale: float,
        text_scale: float = 0.25,
        layout: str = "left",
        extraArgs: list = [],
        parent=None,
    ):
        self.app = app

        if layout == "left":
            text_align = TextNode.ALeft
            text_pos = (-0.9, -0.35 * text_scale)
        elif layout == "center":
            text_align = TextNode.ACenter
            text_pos = (0, -0.35 * text_scale)
        elif layout == "right":
            text_align = TextNode.ARight
            text_pos = (0.9, -0.35 * text_scale)
        else:
            raise NotImplementedError(f"Unkonwn layout: {layout}")

        self.button = DirectButton(
            # Personalizable items
            parent=parent,
            command=command,
            extraArgs=extraArgs,
            pos=pos,
            text=text,
            scale=scale,
            text_scale=text_scale,
            text_align=text_align,
            text_pos=text_pos,
            # Common parameters
            image=app.menu_models.button_geom,
            text_fg=(1, 1, 1, 1),
            relief=1,
            pad=(0.01, 0.01),
            frameColor=(0, 0, 0, 0),
            frameSize=(-1, 1, -0.25, 0.25),
            pressEffect=True,
        )
        self.button.setTransparency(True)

    def destroy(self):
        self.button.destroy()

    def hide(self):
        self.button.hide()

    def show(self):
        self.button.show()

    def set_pressed(self):
        """
        Visually register a "pressed" state
        """
        self.button["geom"] = self.app.menu_models.button_geom[1]

    def reset(self):
        """
        Resets the visual of the button
        """
        self.button["geom"] = self.app.menu_models.button_geom
