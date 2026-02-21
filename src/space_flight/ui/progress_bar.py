import random

from direct.gui.DirectGui import DirectFrame, DirectLabel
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject
from panda3d.core import TextNode


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
        blurb_update_delay_s: float = 1.5,
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
            print("updating_blurb")
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
