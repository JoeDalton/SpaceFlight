import random
from collections.abc import Callable

from direct.gui.DirectGui import (
    DGG,
    DirectButton,
    DirectCheckButton,
    DirectEntry,
    DirectFrame,
    DirectLabel,
    DirectSlider,
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject
from panda3d.core import TextNode

from space_flight import DATAFILES_PATH


class ProgressBar:
    """
    A progress bar that attaches to the bottom of a parent node and cycles
    through short hint strings ("blurbs") above it while loading progresses.

    "Lean" here means the bar is a plain white DirectFrame with no border or
    background — just a thin filled rectangle that grows from left to right.
    Blurbs are arbitrary strings chosen at random from the supplied list and
    swapped out on a fixed time interval so the player has something to read
    during long loading screens.
    """

    def __init__(
        self,
        app: ShowBase,
        parent,
        blurbs: list[str] = [""],
        blurb_update_delay_s: float = 2.0,
        bar_height: float = 0.01,
    ):
        """
        Build the bar and blurb label, then call update(0) to initialise sizes.

        :param app: The running ShowBase application; used to attach the bar
            frame to aspect2d.
        :param parent: The Panda3D node the bar should sit beneath. Its tight
            bounds are queried to determine the bar width and left edge.
        :param blurbs: List of hint strings shown above the bar. A random entry
            is displayed at construction time and rotated every
            *blurb_update_delay_s* seconds.
        :param blurb_update_delay_s: Minimum number of seconds between blurb
            changes.
        :param bar_height: Vertical extent of the filled bar rectangle in
            aspect2d units.
        """
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
        Resize the bar to reflect the current progress and, if enough time has
        elapsed since the last change, swap the blurb for a new random entry.

        :param value: Fractional progress in the range [0, 1]. A value of 0
            renders an empty bar; 1 renders a bar that spans the full width of
            the parent node.
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
        Remove the bar frame and the blurb label from the scene graph and free
        their resources.
        """
        self.bar.destroy()
        self.blurb_label.destroy()


class MenuModels:
    """
    Container for Panda3D egg models shared across all menu screens.

    On construction it loads four egg files (button, thumb, inc, dec) from the
    data directory and stores their named sub-nodes as geometry tuples in the
    standard Panda3D (ready, click, hover, disabled) order expected by
    DirectButton and DirectScrollBar. It also sets the global default dialog
    background geometry via DGG.setDefaultDialogGeom so that every
    DirectDialog in the session uses the game's custom dialog texture.
    """

    def __init__(
        self,
        app: ShowBase,
    ):
        """
        Load all menu egg models and register the default dialog geometry.

        :param app: The running ShowBase application; used to access the
            asset manager and the Panda3D loader.
        """
        # Dialog box background
        dialog_geom = app.asset_manager.get_asset(
            "texture", DATAFILES_PATH / "menus/dialog.png"
        ).get_texture()
        DGG.setDefaultDialogGeom(dialog_geom)
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


class CustomButton:
    """
    A styled DirectButton wrapper that uses the game's button egg model for its
    four visual states (ready, click, hover, disabled).

    Wrapping DirectButton keeps callers free of Panda3D-specific keyword
    arguments and ensures every button in the game shares the same geometry,
    colours, and relief settings.
    """

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
        """
        Create and configure the underlying DirectButton.

        :param app: The running ShowBase application; used to retrieve shared
            button geometry from app.menu_models.
        :param pos: 3-tuple (x, y, z) giving the button's position in its
            parent's coordinate space.
        :param command: Callable invoked when the button is clicked.
        :param text: Label string rendered on the button face.
        :param scale: Uniform scale applied to the whole button node.
        :param text_scale: Scale of the text relative to the button geometry.
            Defaults to 0.25.
        :param layout: Controls text alignment and horizontal anchor.
            ``"left"`` aligns text to the left edge, ``"center"`` centres it,
            and ``"right"`` aligns it to the right edge. Raises
            ``NotImplementedError`` for any other value.
        :param extraArgs: Additional positional arguments forwarded to
            *command* when the button is clicked.
        :param parent: Panda3D node to attach the button to. Defaults to the
            global aspect2d when ``None``.
        """
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
        """
        Remove the button from the scene graph and free its resources.
        """
        self.button.destroy()

    def hide(self):
        """
        Hide the button without removing it from the scene graph.
        """
        self.button.hide()

    def show(self):
        """
        Make the button visible after it has been hidden.
        """
        self.button.show()

    def set_pressed(self):
        """
        Lock the button into its "click" visual state regardless of mouse
        interaction, so the caller can signal that the associated option is
        currently active.
        """
        self.button["geom"] = self.app.menu_models.button_geom[1]

    def reset(self):
        """
        Restore the full four-state geometry tuple so the button cycles through
        ready, click, hover, and disabled states normally again.
        """
        self.button["geom"] = self.app.menu_models.button_geom


class CustomEntry:
    """
    A styled single-line text entry widget backed by a DirectEntry.

    Applies a dark semi-transparent background and warm off-white text colour
    consistent with the game's UI palette, and restricts the entry to a single
    line of input.
    """

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float],
        initial_text: str = "",
        width: float = 14,
        scale: float = 0.05,
        parent=None,
    ):
        """
        Create the underlying DirectEntry with game-standard styling.

        :param app: The running ShowBase application (currently unused but
            accepted for API consistency with other custom widgets).
        :param pos: 3-tuple (x, y, z) giving the entry's position in its
            parent's coordinate space.
        :param initial_text: String pre-filled in the entry on creation.
        :param width: Visible width of the entry field in character units.
        :param scale: Uniform scale applied to the entry node.
        :param parent: Panda3D node to attach the entry to. Defaults to the
            global aspect2d when ``None``.
        """
        self.entry = DirectEntry(
            parent=parent,
            pos=pos,
            scale=scale,
            initialText=initial_text,
            width=width,
            numLines=1,
            frameColor=(0.12, 0.12, 0.18, 0.92),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            relief=DGG.FLAT,
        )

    def get(self) -> str:
        """
        Return the current contents of the entry field.

        :return: The string currently typed in the entry.
        """
        return self.entry.get()

    def set(self, text: str) -> None:
        """
        Replace the entry field's contents with the given string.

        :param text: The new string to display in the entry.
        """
        self.entry.set(text)

    def destroy(self) -> None:
        """Remove the entry widget from the scene graph and free its resources."""
        self.entry.destroy()


class CustomSlider:
    """
    A styled horizontal :class:`DirectSlider` wrapper using the game's thumb
    geometry, consistent with the scrollbar in the input settings menu.

    The caller supplies a value range and a command invoked on every change;
    read the live value with :meth:`get_value`.
    """

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float],
        value: float,
        value_range: tuple[float, float],
        command: Callable,
        extraArgs: list = [],
        parent=None,
        scale: float = 0.4,
    ):
        """
        Create the underlying DirectSlider with game-standard styling.

        :param app: The running ShowBase application; used to retrieve the
            shared thumb geometry from ``app.menu_models``.
        :param pos: 3-tuple (x, y, z) of the slider's position.
        :param value: Initial value of the slider.
        :param value_range: ``(min, max)`` range of the slider.
        :param command: Callable invoked (with *extraArgs*) on every change.
        :param extraArgs: Additional positional arguments forwarded to *command*.
        :param parent: Panda3D node to attach to. Defaults to aspect2d.
        :param scale: Uniform scale applied to the slider node.
        """
        self.app = app
        self.slider = DirectSlider(
            parent=parent,
            pos=pos,
            scale=scale,
            range=value_range,
            value=value,
            pageSize=(value_range[1] - value_range[0]) / 10.0,
            command=command,
            extraArgs=extraArgs,
            relief=DGG.FLAT,
            frameColor=(0.12, 0.12, 0.18, 0.92),
            frameSize=(-1, 1, -0.06, 0.06),
            thumb_relief=1,
            thumb_geom=app.menu_models.thumb_geom,
            thumb_geom_scale=(1, 1, 0.4),
            thumb_frameSize=(-0.06, 0.06, -0.14, 0.14),
            thumb_frameColor=(0, 0, 0, 0),
            thumb_pressEffect=True,
        )
        self.slider.setTransparency(True)

    def get_value(self) -> float:
        """Return the slider's current value."""
        return self.slider["value"]

    def set_value(self, value: float) -> None:
        """Set the slider's value (does not fire the command)."""
        self.slider["value"] = value

    def destroy(self) -> None:
        """Remove the slider from the scene graph and free its resources."""
        self.slider.destroy()


class CustomCheckButton:
    """
    A styled :class:`DirectCheckButton` wrapper rendering a simple on/off box.

    The command is invoked with the new boolean state (followed by *extraArgs*)
    on every toggle.
    """

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float],
        value: bool,
        command: Callable,
        extraArgs: list = [],
        parent=None,
        scale: float = 0.07,
    ):
        """
        Create the underlying DirectCheckButton with game-standard styling.

        :param app: The running ShowBase application (accepted for API
            consistency with the other custom widgets).
        :param pos: 3-tuple (x, y, z) of the checkbox position.
        :param value: Initial checked state.
        :param command: Callable invoked as ``command(status, *extraArgs)`` on
            toggle, where *status* is ``1`` (checked) or ``0`` (unchecked).
        :param extraArgs: Additional positional arguments forwarded to *command*.
        :param parent: Panda3D node to attach to. Defaults to aspect2d.
        :param scale: Uniform scale applied to the checkbox node.
        """
        self.checkbox = DirectCheckButton(
            parent=parent,
            pos=pos,
            scale=scale,
            command=command,
            extraArgs=extraArgs,
            indicatorValue=1 if value else 0,
            text="",
            relief=DGG.FLAT,
            frameColor=(0, 0, 0, 0),
            boxRelief=DGG.FLAT,
            boxBorder=0.04,
            boxImageColor=(0.12, 0.12, 0.18, 0.92),
            indicator_text_fg=(0.65, 0.82, 1.0, 1.0),
        )
        self.checkbox.setTransparency(True)

    def get_value(self) -> bool:
        """Return the current checked state."""
        return bool(self.checkbox["indicatorValue"])

    def destroy(self) -> None:
        """Remove the checkbox from the scene graph and free its resources."""
        self.checkbox.destroy()
