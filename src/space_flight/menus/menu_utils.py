from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from direct.gui.DirectGui import (
    DGG,
    DirectButton,
    DirectCheckButton,
    DirectEntry,
    DirectFrame,
    DirectLabel,
    DirectScrollBar,
    DirectScrolledFrame,
    DirectSlider,
)
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import ClockObject, aspect2d
from panda3d.core import NodePath, TextNode

from space_flight import DATAFILES_PATH
from space_flight.ui.input_context import MenuInputContext


class ProgressBar:
    """
    A thin white fill bar along the bottom of a parent node, growing left to
    right, with a hint string ("blurb") above it picked at random from a list
    and swapped on a fixed interval while loading progresses.
    """

    def __init__(
        self,
        app: ShowBase,
        parent: NodePath,
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


class ScrollableList:
    """
    A vertically scrolling list of fixed-height rows inside a bordered frame.

    Wraps a :class:`DirectScrolledFrame` (used purely as a border/clip, not
    for its own scrolling) and a :class:`DirectScrollBar` that instead moves a
    "content" node directly, so the canvas never resizes as rows are added.
    :meth:`rebuild` (re)creates the frame for a given row count and returns
    the content node; callers parent their own row widgets to it, positioned
    via :meth:`row_y`.

    Shared by the input and graphics settings menus so both option lists
    scroll identically.
    """

    def __init__(
        self,
        app: ShowBase,
        row_height: float,
        frame_top: float,
        frame_bottom: float,
    ):
        """
        Store layout parameters; no widgets are created until :meth:`rebuild`.

        :param app: The running ShowBase application; used for a2dLeft /
            a2dRight and the shared scrollbar geometry in app.menu_models.
        :param row_height: Vertical space allotted to each row.
        :param frame_top: Z of the top edge of the scrollable frame.
        :param frame_bottom: Z of the bottom edge of the scrollable frame.
        """
        self.app = app
        self.row_height = row_height
        self.frame_top = frame_top
        self.frame_bottom = frame_bottom
        self.scroll_frame = None
        self.v_scrollbar: DirectScrollBar | None = None
        self.content = None

    def rebuild(self, n_rows: int) -> NodePath:
        """
        Destroy any existing frame/scrollbar and build new ones sized for
        *n_rows* rows.

        :param n_rows: Number of rows that will be laid out via :meth:`row_y`.
        :return: The content node rows should be parented to.
        """
        self.destroy()
        half_row = self.row_height / 2
        frame_h = self.frame_top - self.frame_bottom
        scrollable = max(0.0, n_rows * self.row_height - frame_h)
        left = self.app.a2dLeft
        right = self.app.a2dRight

        # Canvas height equals frame height so PGScrollFrame does not move the
        # canvas; the content node is scrolled directly by v_scrollbar instead.
        self.scroll_frame = DirectScrolledFrame(
            frameSize=(left + 0.08, right - 0.08, 0.0, frame_h),
            pos=(0, 0, self.frame_bottom),
            frameColor=(0, 0, 0, 0.25),
            canvasSize=(left + 0.12, right - 0.12, 0.0, frame_h),
            manageScrollBars=False,
            verticalScroll_relief=None,
            horizontalScroll_relief=None,
        )
        self.scroll_frame.verticalScroll.hide()
        self.scroll_frame.horizontalScroll.hide()

        canvas = self.scroll_frame.getCanvas()
        self.content = canvas.attachNewNode("content")
        self.content.setZ(frame_h - half_row)  # scroll=0: first row at frame top

        def scroll():
            self.content.setZ(frame_h - half_row + self.v_scrollbar["value"])

        self.v_scrollbar = DirectScrollBar(
            range=(0, scrollable),
            value=0,
            scrollSize=0.25 * self.row_height,
            pageSize=frame_h,
            orientation=DGG.VERTICAL,
            pos=(right - 0.12, 0, self.frame_bottom),
            frameSize=(-0.04, 0.04, 0.0, frame_h),
            frameColor=(0.02, 0.02, 0.02, 1),
            command=scroll,
            # resizeThumb=0 keeps the thumb a fixed size, so its travel is
            # identical regardless of content length (only the value->content
            # mapping differs). With it off, PGSliderBar slides the thumb
            # *node* across the whole trough; the thumb_geom is authored 1.1
            # units tall, which would overflow far past the inc/dec buttons,
            # so scale it down to a compact grip that stays within the trough.
            resizeThumb=0,
            thumb_relief=1,
            thumb_geom=self.app.menu_models.thumb_geom,
            thumb_geom_scale=(1, 1, 0.15),
            thumb_pressEffect=True,
            thumb_frameColor=(0, 0, 0, 0),
            incButton_relief=1,
            incButton_geom=self.app.menu_models.inc_geom,
            incButton_frameSize=(-0.04, 0.04, -0.04, 0.04),
            incButton_pressEffect=True,
            incButton_frameColor=(0, 0, 0, 0),
            decButton_relief=1,
            decButton_geom=self.app.menu_models.dec_geom,
            decButton_frameSize=(-0.04, 0.04, -0.04, 0.04),
            decButton_pressEffect=True,
            decButton_frameColor=(0, 0, 0, 0),
        )
        return self.content

    def row_y(self, index: int) -> float:
        """Return the content-space Z offset for row *index* (0-based)."""
        return -(index * self.row_height)

    def add_header(self, text: str, y: float) -> DirectLabel:
        """Add a blue section-header label spanning the row's width at *y*."""
        left = self.app.a2dLeft + 0.14
        scale = 0.055
        width = (self.app.a2dRight - 0.14 - left) / scale
        hdr = DirectLabel(
            parent=self.content,
            text=text,
            scale=scale,
            pos=(left, 0, y - 0.02),
            frameSize=(-0.05, width, -0.35, 0.65),
            frameColor=(0.1, 0.1, 0.3, 0.85),
            text_fg=(0.65, 0.82, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        hdr.setTransparency(True)
        return hdr

    def add_row_label(self, text: str, y: float) -> DirectLabel:
        """Add a left-aligned row label (rendered as "*text*:") at *y*."""
        label = DirectLabel(
            parent=self.content,
            text=text + ":",
            scale=0.05,
            pos=(self.app.a2dLeft + 0.2, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        )
        label.setTransparency(True)
        return label

    def add_checkbox(
        self, y: float, value: bool, command: Callable, extraArgs: list = []
    ) -> CustomCheckButton:
        """Add a boolean checkbox at the row's right edge, at *y*."""
        return CustomCheckButton(
            app=self.app,
            pos=(self.app.a2dRight - 0.3, 0, y),
            value=value,
            command=command,
            extraArgs=extraArgs,
            parent=self.content,
        )

    def wheel_scroll(self, step: float):
        """
        Scroll by *step* scroll-bar units (negative toward the top, positive
        toward the bottom). A no-op before the first :meth:`rebuild`.
        """
        if self.v_scrollbar is None:
            return
        vs = self.v_scrollbar
        lo, hi = vs["range"]
        vs["value"] = max(lo, min(hi, vs["value"] + step * vs["scrollSize"]))

    def destroy(self):
        """Destroy the scrollbar/frame if present; safe to call repeatedly."""
        if self.v_scrollbar is not None:
            self.v_scrollbar.destroy()
            self.v_scrollbar = None
        if self.scroll_frame is not None:
            self.scroll_frame.destroy()
            self.scroll_frame = None
        self.content = None


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
        pos: tuple[float, float, float],
        command: Callable,
        text: str,
        scale: float,
        text_scale: float = 0.25,
        layout: str = "left",
        width_scale: float = 1.0,
        extraArgs: list = [],
        parent: NodePath | None = None,
    ):
        """
        Create and configure the underlying DirectButton.

        :param app: The running ShowBase application; used to retrieve shared
            button geometry from app.menu_models.
        :param pos: 3-tuple (x, y, z) giving the button's position in its
            parent's coordinate space.
        :param command: Callable invoked when the button is clicked.
        :param text: Label string rendered on the button face.
        :param scale: Uniform scale applied to the whole button node
            (text included), so glyphs always keep their normal aspect
            ratio regardless of *width_scale*.
        :param text_scale: Scale of the text relative to the button geometry.
            Defaults to 0.25.
        :param layout: Controls text alignment and horizontal anchor.
            "left" aligns text to the left edge, "center" centres it,
            and "right" aligns it to the right edge. Raises
            NotImplementedError for any other value.
        :param width_scale: Extra horizontal stretch applied only to the
            button's face image and clickable frame (not to *scale*, so
            the text is never distorted). 1.0 keeps the button's normal
            square-ish proportions; e.g. 2.0 doubles its width only.
        :param extraArgs: Additional positional arguments forwarded to
            *command* when the button is clicked.
        :param parent: Panda3D node to attach the button to. Defaults to the
            global aspect2d when None.
        """
        self.app = app
        self.width_scale = width_scale
        # Shown as the selected option (set_pressed), and focused by menu
        # navigation (set_focus)
        self.is_selected = False
        self.is_focused = False

        if layout == "left":
            text_align = TextNode.ALeft
            text_pos = (-0.9 * width_scale, -0.35 * text_scale)
        elif layout == "center":
            text_align = TextNode.ACenter
            text_pos = (0, -0.35 * text_scale)
        elif layout == "right":
            text_align = TextNode.ARight
            text_pos = (0.9 * width_scale, -0.35 * text_scale)
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
            image_scale=(width_scale, 1, 1),
            text_fg=(1, 1, 1, 1),
            relief=1,
            pad=(0.01, 0.01),
            frameColor=(0, 0, 0, 0),
            frameSize=(-width_scale, width_scale, -0.25, 0.25),
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

    def is_hidden(self) -> bool:
        """
        :return: True while the button is hidden.
        """
        return self.button.isHidden()

    def set_pressed(self):
        """
        Lock the button into its "click" visual state regardless of mouse
        interaction, so the caller can signal that the associated option is
        currently active.  While focused it shows its "hover" state instead,
        the focus look.
        """
        self.is_selected = True
        self.update_selected_geom()

    def reset(self):
        """
        Restore the full four-state geometry tuple so the button cycles through
        ready, click, hover, and disabled states normally again.
        """
        self.is_selected = False
        self.button["geom"] = self.app.menu_models.button_geom
        self.stretch_geoms()

    def set_focus(self, focused: bool):
        """
        Show or clear the menu-navigation focus: the "hover" state, as if
        the mouse were over the button.

        :param focused: Whether the button has the focus.
        """
        self.is_focused = focused
        self.button.guiItem.setState(2 if focused else 0)  # rollover / ready
        if self.is_selected:
            self.update_selected_geom()

    def refresh_hover(self, region_name: str):
        """
        Show the "hover" state if the mouse is over the button.

        :param region_name: Name of the mouse region under the pointer.
        """
        if region_name == self.button.guiItem.getId():
            self.button.guiItem.setState(2)  # rollover

    def activate(self):
        """
        Run the button's command, as a click does.
        """
        self.button.commandFunc(None)

    def update_selected_geom(self):
        """
        Overlay the selected button's locked geom: "click", or "hover" while
        focused.
        """
        state = 2 if self.is_focused else 1
        self.button["geom"] = self.app.menu_models.button_geom[state]
        self.stretch_geoms()

    def stretch_geoms(self):
        """
        Apply width_scale to the per-state geom components, which are drawn
        over the (already stretched) image and would otherwise stay narrow.
        """
        for name in self.button.components():
            if name.startswith("geom"):
                self.button.component(name).setScale(self.width_scale, 1, 1)


class MenuNavigator:
    """
    Keyboard, gamepad and joystick focus over a menu's widgets, driven by a
    :class:`~space_flight.ui.input_context.MenuInputContext` pushed while the
    navigator lives.

    The widgets are laid out as rows: up/down moves between rows (wrapping
    around), left/right moves within a row of several widgets, or adjusts a
    lone one that supports it.  Hidden widgets are skipped, and a navigator
    whose widgets are all hidden (its screen covered by another) ignores
    input.

    The focus only shows from the first navigation input (which shows it
    without moving it), and hides again when the mouse moves, so mouse users
    never see it.

    Widgets are duck-typed: ``is_hidden()``, ``set_focus(focused)``,
    ``refresh_hover(region_name)`` and ``activate()``, plus
    ``adjust(direction)`` for adjustable ones.
    """

    def __init__(
        self, app: ShowBase, rows: list[list], on_back: Callable | None = None
    ):
        """
        Push the navigator's input context.

        :param app: The running ShowBase application
        :param rows: The widgets, row by row, from the top
        :param on_back: Called when the back key is pressed; None ignores it
        """
        self.app = app
        self.rows = rows
        self.on_back = on_back
        self.row = 0
        self.column = 0
        # Column chosen along the last row of several widgets, kept through
        # single-widget rows
        self.preferred_column = 0
        self.focus_shown = False
        self.context = MenuInputContext(app, self)
        app.input_context_stack.push(self.context)

    def remove(self):
        """
        Remove the input context.  Call from the menu state's exit.
        """
        self.app.input_context_stack.remove(self.context)

    # ------------------------------------------------------------------
    # Focus
    # ------------------------------------------------------------------

    @property
    def focused(self):
        """
        :return: The widget with the focus (shown or not).
        """
        return self.rows[self.row][self.column]

    def is_active(self) -> bool:
        """
        :return: False while every widget is hidden (screen covered).
        """
        return any(not w.is_hidden() for row in self.rows for w in row)

    def show_focus(self):
        """
        Show the focus, first moving it to a visible widget if needed, and
        clear the mouse hover of every other widget (the cursor hides as a
        key is pressed, but the widget under it would stay highlighted).
        """
        if self.focused.is_hidden():
            self.step_row(1)
        for row in self.rows:
            for widget in row:
                widget.set_focus(False)
        self.focus_shown = True
        self.focused.set_focus(True)

    def hide_focus(self):
        """
        Hide the focus, keeping its position.
        """
        if self.focus_shown:
            self.focus_shown = False
            self.focused.set_focus(False)

    def refresh_hover(self):
        """
        Give the hover look back to the widget under the mouse pointer, which
        the focus cleared without the pointer leaving it.
        """
        over = self.app.mouseWatcherNode.getOverRegion()
        if over is None:
            return
        for row in self.rows:
            for widget in row:
                widget.refresh_hover(over.getName())

    def focus_on(self, widget):
        """
        Move the focus to *widget*, shown only if the focus is.

        :param widget: One of the navigator's widgets.
        """
        for row_index, row in enumerate(self.rows):
            if widget in row:
                self.preferred_column = row.index(widget)
                self.set_position(row_index, self.preferred_column)
                return

    def set_position(self, row: int, column: int):
        """
        :param row: The row of the newly focused widget.
        :param column: Its column.
        """
        if self.focus_shown:
            self.focused.set_focus(False)
        self.row = row
        self.column = column
        if self.focus_shown:
            self.focused.set_focus(True)

    # ------------------------------------------------------------------
    # Navigation (called by MenuInputContext)
    # ------------------------------------------------------------------

    def move(self, dx: int, dy: int):
        """
        Move the focus by one row (dy) or along the row (dx); show it only,
        if hidden.

        :param dx: -1 (left), 0 or 1 (right)
        :param dy: -1 (up), 0 or 1 (down)
        """
        if not self.is_active():
            return
        if not self.focus_shown:
            self.show_focus()
        elif dy:
            self.step_row(dy)
        elif dx:
            self.step_column(dx)

    def confirm(self):
        """
        Activate the focused widget; show the focus only, if hidden.
        """
        if not self.is_active():
            return
        if not self.focus_shown:
            self.show_focus()
        else:
            self.focused.activate()

    def back(self):
        """
        Call on_back, unless the screen is covered.
        """
        if self.on_back is not None and self.is_active():
            self.on_back()

    def step_row(self, dy: int):
        """
        Focus the next row holding a visible widget, wrapping around.

        :param dy: -1 (up) or 1 (down)
        """
        n_rows = len(self.rows)
        for offset in range(1, n_rows + 1):
            row_index = (self.row + dy * offset) % n_rows
            visible = [
                c for c, w in enumerate(self.rows[row_index]) if not w.is_hidden()
            ]
            if visible:
                column = min(visible, key=lambda c: abs(c - self.preferred_column))
                self.set_position(row_index, column)
                return

    def step_column(self, dx: int):
        """
        Focus the next visible widget along the row, or adjust a lone one.

        :param dx: -1 (left) or 1 (right)
        """
        row = self.rows[self.row]
        visible = [c for c, w in enumerate(row) if not w.is_hidden()]
        if len(visible) > 1:
            position = visible.index(self.column) if self.column in visible else 0
            self.preferred_column = visible[(position + dx) % len(visible)]
            self.set_position(self.row, self.preferred_column)
        elif hasattr(self.focused, "adjust"):
            self.focused.adjust(dx)


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
        pos: tuple[float, float, float],
        initial_text: str = "",
        width: float = 14,
        scale: float = 0.05,
        parent: NodePath | None = None,
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
            global aspect2d when None.
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

    def set(self, text: str):
        """
        Replace the entry field's contents with the given string.

        :param text: The new string to display in the entry.
        """
        self.entry.set(text)

    def destroy(self):
        """Remove the entry widget from the scene graph and free its resources."""
        self.entry.destroy()


class CustomSlider:
    """
    A styled horizontal :class:`DirectSlider` wrapper using the game's thumb
    geometry, consistent with the settings menus' scrollbars.

    The caller supplies a value range and a command invoked on every change;
    read the live value with :meth:`get_value`.
    """

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float, float, float],
        value: float,
        value_range: tuple[float, float],
        command: Callable,
        extraArgs: list = [],
        parent: NodePath | None = None,
        scale: float = 0.4,
    ):
        """
        Create the underlying DirectSlider with game-standard styling.

        :param app: The running ShowBase application; used to retrieve the
            shared thumb geometry from app.menu_models.
        :param pos: 3-tuple (x, y, z) of the slider's position.
        :param value: Initial value of the slider.
        :param value_range: (min, max) range of the slider.
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

    def set_value(self, value: float):
        """Set the slider's value (does not fire the command)."""
        self.slider["value"] = value

    def destroy(self):
        """Remove the slider from the scene graph and free its resources."""
        self.slider.destroy()


class CustomCheckButton:
    """
    A styled :class:`DirectCheckButton` wrapper rendering a simple on/off box.
    """

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float, float, float],
        value: bool,
        command: Callable,
        extraArgs: list = [],
        parent: NodePath | None = None,
        scale: float = 0.07,
    ):
        """
        Create the underlying DirectCheckButton with game-standard styling.

        :param app: The running ShowBase application (accepted for API
            consistency with the other custom widgets).
        :param pos: 3-tuple (x, y, z) of the checkbox position.
        :param value: Initial checked state.
        :param command: Callable invoked as command(status, *extraArgs) on
            toggle, where *status* is 1 (checked) or 0 (unchecked).
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
        )
        self.checkbox.setTransparency(True)
        # Set the indicator glyph/color after construction: DirectCheckButton
        # uses an 'X' internally at creation time to size the box, then
        # force-resets the display text to (' ', '*'); overriding either as a
        # constructor kwarg collides with that sizing pass and shrinks the box.
        self.checkbox["indicator_text"] = (" ", "X")
        self.checkbox["indicator_text_fg"] = (0, 0, 0, 1)
        # DirectCheckButton hardcodes text_pos=(0, -.2), tuned to visually
        # center the default '*' glyph; re-center it for the 'X' glyph instead.
        self.checkbox["indicator_text_pos"] = (0, 0)
        self.checkbox["indicator_text_align"] = TextNode.ACenter

    def get_value(self) -> bool:
        """Return the current checked state."""
        return bool(self.checkbox["indicatorValue"])

    def destroy(self):
        """Remove the checkbox from the scene graph and free its resources."""
        self.checkbox.destroy()


class CustomDropDown:
    """
    A drop-down list built from the game's buttons.

    The head is a :class:`CustomButton` showing the selected option, with a
    down arrow. Clicking it opens the list: one button per option, stacked
    under the head, the selected one pressed. The list stays open until an
    option is clicked (selecting it) or the user clicks anywhere else (closing
    it without changing the value).

    Each option is a (label, value) pair: the buttons show the labels, while
    :meth:`get_value`, :meth:`set_value` and the command deal in values.

    While open, the list is drawn and clicked above every other widget, a
    transparent full-screen frame under it catching the clicks elsewhere.
    """

    # Arrow: scale of the arrow card (0.08 units across) in head button units,
    # and its center's distance to the head's right end
    _ARROW_SCALE = 4.0
    _ARROW_INSET = 0.25
    # Vertical distance between stacked buttons, in button units (a button is
    # 0.5 tall)
    _ITEM_SPACING = 0.52

    def __init__(
        self,
        app: ShowBase,
        pos: tuple[float, float, float],
        options: list[tuple[str, Any]],
        value: Any,
        command: Callable,
        parent: NodePath | None = None,
        scale: float = 0.19,
        width_scale: float = 1.6,
    ):
        """
        Build the head button; the list is built on first opening.

        :param app: The running ShowBase application; used to retrieve the
            shared button and arrow geometry from app.menu_models.
        :param pos: 3-tuple (x, y, z) of the head button's center.
        :param options: The (label, value) pairs listed, in order.
        :param value: The initially selected option's value.
        :param command: Callable invoked as command(value) when the user picks
            an option (even the selected one again), not on :meth:`set_value`.
        :param parent: Panda3D node to attach the head to. Defaults to aspect2d.
            The open list is always attached to aspect2d, to be above all.
        :param scale: Uniform scale of the head and option buttons.
        :param width_scale: Horizontal stretch of the head and option buttons
            (see :class:`CustomButton`).
        """
        self.app = app
        self.options = options
        self.values = [option_value for _, option_value in options]
        self.value = value
        self.command = command
        self.scale = scale
        self.width_scale = width_scale

        self.head = CustomButton(
            app=app,
            pos=pos,
            command=self.open,
            text=self._label(value),
            scale=scale,
            layout="center",
            width_scale=width_scale,
            parent=parent,
        )
        self.arrow = DirectFrame(
            parent=self.head.button,
            geom=app.menu_models.inc_geom[0],
            geom_scale=self._ARROW_SCALE,
            pos=(width_scale - self._ARROW_INSET, 0, 0),
            frameColor=(0, 0, 0, 0),
        )

        # The open list (see open): a root drawn on top of every widget, the
        # click catcher, and the option buttons
        self.popup_root: NodePath | None = None
        self.click_catcher: DirectFrame | None = None
        self.item_buttons: list[CustomButton] = []

    def _label(self, value: Any) -> str:
        """Return the label of the option of the given value."""
        return self.options[self.values.index(value)][0]

    @property
    def is_open(self) -> bool:
        """Whether the list is open."""
        return self.popup_root is not None

    def open(self):
        """Show the option list under the head, the selected option pressed."""
        if self.is_open:
            return
        # Attached last under aspect2d, so it is clicked before every other
        # widget (the GUI picks the last traversed one), and drawn after them
        self.popup_root = aspect2d.attachNewNode("dropDownPopup")
        self.popup_root.setBin("gui-popup", 0)
        self.popup_root.setPos(self.head.button.getPos(aspect2d))

        # Created before the option buttons, so they are clicked before it
        self.click_catcher = DirectFrame(
            parent=self.popup_root,
            state=DGG.NORMAL,
            frameSize=(-100, 100, -100, 100),
            frameColor=(0, 0, 0, 0),
        )
        self.click_catcher.bind(DGG.B1PRESS, lambda _event: self.close())

        spacing = self._ITEM_SPACING * self.scale
        for index, (label, value) in enumerate(self.options):
            button = CustomButton(
                app=self.app,
                pos=(0, 0, -(index + 1) * spacing),
                command=self.select,
                text=label,
                scale=self.scale,
                layout="center",
                width_scale=self.width_scale,
                extraArgs=[value],
                parent=self.popup_root,
            )
            if value == self.value:
                button.set_pressed()
            self.item_buttons.append(button)

    def close(self):
        """Close the option list, if open, leaving the value unchanged."""
        if not self.is_open:
            return
        for button in self.item_buttons:
            button.destroy()
        self.item_buttons = []
        self.click_catcher.destroy()
        self.click_catcher = None
        self.popup_root.removeNode()
        self.popup_root = None

    def select(self, value: Any):
        """Close the list, select an option, and call the command with it."""
        self.close()
        self.set_value(value)
        self.command(value)

    def get_value(self) -> Any:
        """Return the selected option's value."""
        return self.value

    def set_value(self, value: Any):
        """Select the option of the given value (does not fire the command)."""
        self.value = value
        self.head.button["text"] = self._label(value)

    def destroy(self):
        """Close the list, and remove the head from the scene graph."""
        self.close()
        self.arrow.destroy()
        self.head.destroy()
