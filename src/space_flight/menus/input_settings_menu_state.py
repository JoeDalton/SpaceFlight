"""
Input settings menu — lets the player view and remap all input bindings.

Reads ``configuration/configuration.yaml`` on entry, keeps an in-memory
working copy while the menu is open, and writes changes back on *Save*.
After saving the active :class:`~space_flight.ui.input_reader.InputReader`
is rebuilt so the new bindings take effect immediately without a restart.
"""

import copy

import yaml
from direct.gui.DirectGui import (
    DGG,
    DirectFrame,
    DirectLabel,
    DirectScrolledFrame,
    OkCancelDialog,
)
from panda3d.core import InputDevice, TextNode, VBase4, Vec2

from space_flight import CONFIGURATION_PATH
from space_flight.global_architecture.base_state import BaseState
from space_flight.menus.menu_utils import CustomButton, CustomEntry
from space_flight.ui.input_reader import (
    GAMEPAD_AXIS_NAMES,
    JOYSTICK_AXIS_NAMES,
    reader_factory,
)

_CONFIG_FILE = CONFIGURATION_PATH / "configuration.yaml"
_DEFAULT_CONFIG_FILE = CONFIGURATION_PATH / "default_configuration.yaml"

_CONTEXT_LABELS = {"flight": "Flight", "radial_menu": "Radial Menu"}
_ROW_HEIGHT = 0.09
_AXIS_DEAD_ZONE = 0.33


def _format_binding(input_type: str, value: str, forced_type: str | None = None) -> str:
    """
    Format a raw binding value for display in the UI.

    Returns a string such as ``"Axis: Left X"`` or ``"Button: Space"`` based
    on whether *value* is recognised as an axis name for *input_type*.
    When *forced_type* is given it overrides the heuristic lookup.

    :param input_type: Active input type (``"keyboard"``, ``"gamepad"``, or
        ``"joystick"``).
    :param value: Raw hardware name stored in the YAML configuration.
    :param forced_type: ``"axis"`` or ``"button"`` to bypass the heuristic;
        ``None`` to auto-detect.
    :return: Human-readable binding string, or ``"Unmapped"`` if *value* is
        empty.
    """
    if not value:
        return "Unmapped"
    if forced_type == "axis":
        is_axis = True
    elif forced_type == "button":
        is_axis = False
    elif input_type == "gamepad":
        is_axis = value in GAMEPAD_AXIS_NAMES
    elif input_type == "joystick":
        is_axis = value in JOYSTICK_AXIS_NAMES
    else:
        is_axis = False
    label = value.replace("_", " ").title()
    return f"Axis: {label}" if is_axis else f"Button: {label}"


class ChangeBindingDialog(object):
    """
    Modal dialog that captures the next key press or axis movement and reports
    it to a callback.

    The implementation mirrors the ``ChangeActionDialog`` / ``changeMapping`` /
    ``closeDialog`` / ``watchControls`` pattern from
    ``panda3d_samples/gamepad/mappingGUI.py``.

    While the dialog is open, all Panda3D button throwers are redirected to two
    generic events (``"keyListenEvent"`` / ``"deviceListenEvent"``) so that any
    hardware input can be captured as a raw string.  Throwers are restored to
    their original state in :meth:`onClose`.

    Axes are polled every frame via the :meth:`watchControls` task.  A baseline
    snapshot of each axis value taken at construction time prevents resting-
    position drift from registering as a deliberate movement.
    """

    def __init__(self, app, action: str, input_type: str, button_geom, command):
        """
        Open the dialog and start intercepting hardware input.

        Creates the :class:`~direct.gui.DirectGui.OkCancelDialog`, redirects all
        button throwers to generic listener events, snapshots the current axis
        values, and starts the :meth:`watchControls` per-frame task.

        :param app: The Panda3D application instance.
        :param action: Human-readable name of the action being remapped; passed
            back unchanged to the command callback.
        :param input_type: Active device type (``"keyboard"``, ``"gamepad"``, or
            ``"joystick"``); used to apply the ``"gamepad_"`` prefix required by
            the YAML convention for gamepad button names.
        :param button_geom: Four-state geom tuple for the OK / Cancel buttons,
            obtained from :class:`~space_flight.menus.menu_utils.MenuModels`.
        :param command: Callback invoked on close with the signature
            ``(action, input_type, input_value)`` where *input_type* is
            ``"button"`` or ``"axis"`` and *input_value* is the hardware name
            to store.  Both are ``None`` if the user cancelled or pressed OK
            without selecting any input.
        """
        self.app = app
        # This stores which action we are remapping.
        self.action = action
        self.input_type = input_type

        # This will store the key/axis that we want to assign to an action.
        self.newInputType = ""
        self.newInput = ""

        self.__command = command

        # ---- Dialog UI (same as ChangeActionDialog.__init__ in mappingGUI.py) ----
        self.dialog = OkCancelDialog(
            dialogName="dlg_device_input",
            pos=(0, 0, 0.25),
            text="Hit desired key:",
            text_fg=VBase4(0.898, 0.839, 0.730, 1.0),
            text_shadow=VBase4(0, 0, 0, 0.75),
            text_shadowOffset=Vec2(0.05, 0.05),
            text_scale=0.05,
            text_align=TextNode.ACenter,
            fadeScreen=0.65,
            frameColor=VBase4(0.3, 0.3, 0.3, 1),
            button_geom=button_geom,
            button_scale=0.15,
            button_text_scale=0.35,
            button_text_align=TextNode.ALeft,
            button_text_fg=VBase4(0.898, 0.839, 0.730, 1.0),
            button_text_pos=Vec2(-0.9, -0.125),
            button_relief=1,
            button_pad=Vec2(0.01, 0.01),
            button_frameColor=VBase4(0, 0, 0, 0),
            button_frameSize=VBase4(-1.0, 1.0, -0.25, 0.25),
            button_pressEffect=False,
            command=self.onClose,
        )
        self.dialog.setTransparency(True)
        self.dialog.configureDialog()
        scale = self.dialog["image_scale"]
        self.dialog["image_scale"] = (scale[0] / 2.0, scale[1], scale[2] / 2.0)
        self.dialog["text_pos"] = (
            self.dialog["text_pos"][0],
            self.dialog["text_pos"][1] + 0.06,
        )

        # ---- Input interception ----
        # Devices are already attached by InputReader; collect for axis polling only.
        self.attachedDevices = list(app.devices.getDevices())

        # Redirect all button events to generic listener events.
        for bt in app.buttonThrowers:
            bt.node().setSpecificFlag(False)
            bt.node().setButtonDownEvent("keyListenEvent")
        for bt in app.deviceButtonThrowers:
            bt.node().setSpecificFlag(False)
            bt.node().setButtonDownEvent("deviceListenEvent")

        app.accept("keyListenEvent", self.buttonPressed)
        app.accept(
            "deviceListenEvent", lambda btn: self.buttonPressed(btn, from_device=True)
        )

        # Snapshot current axis values as a baseline for dead-zone detection.
        self.axisStates = {None: {}}
        for device in self.attachedDevices:
            for axis in device.axes:
                if device not in self.axisStates:
                    self.axisStates[device] = {axis.axis: axis.value}
                else:
                    self.axisStates[device][axis.axis] = axis.value

        app.taskMgr.add(self.watchControls, "checkControls")

    def buttonPressed(self, button, from_device: bool = False):
        """
        Handle a button-down event captured by the redirected button thrower.

        Updates the dialog text and records the pending binding.  Events fired by
        the dialog's own OK / Cancel buttons are silently ignored to prevent a
        mouse click from being registered as the new binding.

        :param button: The :class:`~panda3d.core.ButtonHandle` that was pressed.
        :param from_device: ``True`` when the event came from a device button
            thrower (gamepad / joystick) via ``"deviceListenEvent"``; ``False``
            for keyboard events via ``"keyListenEvent"``.  Controls whether the
            ``"gamepad_"`` prefix is prepended.
        """
        if any(btn.guiItem.getState() == 1 for btn in self.dialog.buttonList):
            # Ignore events while dialog OK/Cancel buttons are active (mouse clicks).
            return

        btn_str = str(button)
        # Prefix device buttons to match the YAML convention (e.g. "gamepad_lshoulder").
        if from_device and self.input_type == "gamepad":
            self.newInput = "gamepad_" + btn_str
        else:
            self.newInput = btn_str
        self.newInputType = "button"
        text = self.newInput.replace("_", " ").title()
        self.dialog["text"] = "New event will be:\n\nButton: " + text

    def axisMoved(self, axis):
        """
        Record an axis movement that exceeded the dead zone.

        Updates the dialog text and stores the axis name string as the pending
        binding.  Called by :meth:`watchControls` whenever a significant change
        is detected.

        :param axis: The :class:`~panda3d.core.InputDevice.Axis` enum value that
            moved; its ``.name`` attribute is used as the stored binding string.
        """
        text = axis.name.replace("_", " ").title()
        self.dialog["text"] = "New event will be:\n\nAxis: " + text
        self.newInputType = "axis"
        self.newInput = axis.name

    def watchControls(self, task):
        """
        Per-frame task that polls all device axes and fires :meth:`axisMoved`
        when movement exceeds the dead zone.

        Compares each axis value against the baseline snapshot taken in
        ``__init__`` and updates the snapshot on any significant movement, so
        only fresh inputs are reported rather than the same held position.

        Mouse devices are skipped because their axes do not represent discrete
        flight controls.

        :param task: Panda3D task object.
        :return: ``task.cont`` to keep the task running.
        """
        DEAD_ZONE = 0.33
        for device in self.attachedDevices:
            if device.device_class == InputDevice.DeviceClass.mouse:
                continue
            if device not in self.axisStates:
                continue
            for axis in device.axes:
                if axis.axis not in self.axisStates[device]:
                    continue
                if (
                    self.axisStates[device][axis.axis] + DEAD_ZONE < axis.value
                    or self.axisStates[device][axis.axis] - DEAD_ZONE > axis.value
                ):
                    self.axisStates[device][axis.axis] = axis.value
                    if axis.axis != InputDevice.Axis.none:
                        self.axisMoved(axis.axis)
        return task.cont

    def onClose(self, result):
        """
        Clean up input interception and invoke the command callback.

        Invoked by the :class:`~direct.gui.DirectGui.OkCancelDialog` when the
        user clicks OK or Cancel.  Destroys the dialog, restores all button
        throwers to their normal state, removes the axis-watch task, and calls
        the constructor-supplied command with the recorded binding.

        :param result: :attr:`~direct.gui.DGG.DIALOG_OK` when the user pressed
            OK, :attr:`~direct.gui.DGG.DIALOG_CANCEL` otherwise.
        """
        self.dialog.cleanup()

        if self.newInput and result == DGG.DIALOG_OK:
            self.__command(self.action, self.newInputType, self.newInput)
        else:
            self.__command(self.action, None, None)

        # Restore button throwers (same as mappingGUI.py).
        for bt in self.app.buttonThrowers:
            bt.node().setSpecificFlag(True)
            bt.node().setButtonDownEvent("")
        for bt in self.app.deviceButtonThrowers:
            bt.node().setSpecificFlag(True)
            bt.node().setButtonDownEvent("")
        self.app.ignore("keyListenEvent")
        self.app.ignore("deviceListenEvent")
        self.app.taskMgr.remove("checkControls")
        # Devices are not detached here — they are managed by InputReader,
        # unlike mappingGUI.py where devices were explicitly attached for this dialog.


# ---------------------------------------------------------------------------


class InputSettingsMenuState(BaseState):
    """
    Full-screen overlay for viewing and editing all input bindings.

    Loads ``configuration/configuration.yaml`` on entry and keeps an unsaved
    working copy in memory.  Three bottom buttons govern the outcome:

    - **Save** — flush dead-zone edits, write the YAML, rebuild the
      :class:`~space_flight.ui.input_reader.InputReader`, and return to the
      main menu.
    - **Cancel** — discard all edits and return to the main menu.
    - **Default** — reload the working copy from
      ``configuration/default_configuration.yaml`` without writing to disk.

    Individual bindings are changed through :class:`ChangeBindingDialog`,
    which is opened by the *Change* button on each binding row.
    """

    def __init__(self, app):
        super().__init__(app)
        self._working_config: dict = {}
        self._saved_config: dict = {}
        self._dz_entries: dict[tuple, CustomEntry] = {}
        self._binding_labels: dict[tuple, DirectLabel] = {}
        self._input_type_buttons: dict[str, CustomButton] = {}
        self._static_widgets: list = []
        self._active_dialog: ChangeBindingDialog | None = None
        self.scroll_frame = None

    # ------------------------------------------------------------------
    # State lifecycle
    # ------------------------------------------------------------------

    def enter(self):
        """
        Load the configuration file, build the static UI, and populate the
        scrollable binding list.

        The YAML is read from disk each time the state is entered, so any
        changes written by a previous session are picked up automatically.
        """
        self._working_config = self._load_file(_CONFIG_FILE)
        self._saved_config = copy.deepcopy(self._working_config)
        self._build_static_ui()
        self._rebuild_scroll()

    def pause(self):
        """
        Pause the state; no action required.
        """
        pass

    def resume(self):
        """
        Resume the state; no action required.
        """
        pass

    def exit(self):
        """
        Dismiss any open dialog and destroy all UI elements.

        If a :class:`ChangeBindingDialog` is open when the state exits (e.g.
        because the state manager pops this state programmatically), the dialog
        is closed with a cancel result before the rest of the UI is torn down.
        """
        if self._active_dialog is not None:
            self._active_dialog.onClose(DGG.DIALOG_CANCEL)
            self._active_dialog = None
        if self.scroll_frame is not None:
            self.scroll_frame.destroy()
            self.scroll_frame = None
        self.title.destroy()
        self.bg.destroy()
        for w in self._static_widgets:
            w.destroy()
        for btn in self._input_type_buttons.values():
            btn.destroy()
        self.default_btn.destroy()
        self.cancel_btn.destroy()
        self.save_btn.destroy()
        self.force_render()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_static_ui(self):
        """
        Create the persistent UI elements shown for the lifetime of this state.

        Builds the full-screen background frame, the title label, the three
        input-type selector buttons (Keyboard / Gamepad / Joystick), and the
        Save / Cancel / Default action buttons.  Called once per :meth:`enter`
        invocation; only the scrollable content is rebuilt when the input type
        changes.
        """
        self.bg = DirectFrame(
            frameSize=(self.app.a2dLeft, self.app.a2dRight, -1.0, 1.0),
            frameColor=(0.04, 0.04, 0.1, 0.97),
        )
        self.bg.setTransparency(True)

        self.title = DirectLabel(
            text="Input Settings",
            scale=0.1,
            pos=(0, 0, 0.88),
            frameColor=(0, 0, 0, 0),
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 0.75),
            text_shadowOffset=(0.05, 0.05),
            text_align=TextNode.ACenter,
        )
        self.title.setTransparency(True)

        # Input type label
        it_label = DirectLabel(
            text="Input type:",
            scale=0.06,
            pos=(-0.85, 0, 0.73),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        )
        it_label.setTransparency(True)
        self._static_widgets.append(it_label)

        # Input type selector buttons
        xs = {"keyboard": -0.1, "gamepad": 0.38, "joystick": 0.86}
        for name, x in xs.items():
            btn = CustomButton(
                app=self.app,
                pos=(x, 0, 0.73),
                command=self._select_input_type,
                text=name.capitalize(),
                scale=0.23,
                layout="center",
                extraArgs=[name],
            )
            self._input_type_buttons[name] = btn
        self._refresh_input_type_buttons()

        # Bottom action buttons
        self.default_btn = CustomButton(
            app=self.app,
            pos=(-0.7, 0, -0.91),
            command=self._load_default,
            text="Default",
            scale=0.28,
            layout="center",
        )
        self.cancel_btn = CustomButton(
            app=self.app,
            pos=(0.0, 0, -0.91),
            command=self._cancel,
            text="Cancel",
            scale=0.28,
            layout="center",
        )
        self.save_btn = CustomButton(
            app=self.app,
            pos=(0.7, 0, -0.91),
            command=self._save,
            text="Save",
            scale=0.28,
            layout="center",
        )

    def _rebuild_scroll(self):
        """
        Destroy the current scrollable frame and rebuild it from the working
        configuration.

        Called on :meth:`enter` and again each time the input type is changed so
        the binding list always reflects the active device's mappings.  Also
        resets the :attr:`_dz_entries` and :attr:`_binding_labels` caches so
        stale widget references are never kept.
        """
        if self.scroll_frame is not None:
            self.scroll_frame.destroy()
            self.scroll_frame = None
        self._dz_entries.clear()
        self._binding_labels.clear()

        rows = self._make_row_data()
        canvas_h = len(rows) * _ROW_HEIGHT + 0.05

        frame_bottom = -0.82
        frame_top = 0.65
        frame_h = frame_top - frame_bottom

        self.scroll_frame = DirectScrolledFrame(
            frameSize=(self.app.a2dLeft + 0.08, self.app.a2dRight - 0.08, 0.0, frame_h),
            pos=(0, 0, frame_bottom),
            frameColor=(0, 0, 0, 0.25),
            canvasSize=(
                self.app.a2dLeft + 0.12,
                self.app.a2dRight - 0.12,
                -canvas_h,
                0.02,
            ),
            verticalScroll_scrollSize=0.2,
            verticalScroll_frameColor=(0.02, 0.02, 0.02, 1),
            verticalScroll_thumb_relief=1,
            verticalScroll_thumb_geom=self.app.menu_models.thumb_geom,
            verticalScroll_thumb_pressEffect=False,
            verticalScroll_thumb_frameColor=(0, 0, 0, 0),
            verticalScroll_incButton_relief=1,
            verticalScroll_incButton_geom=self.app.menu_models.inc_geom,
            verticalScroll_incButton_pressEffect=False,
            verticalScroll_incButton_frameColor=(0, 0, 0, 0),
            verticalScroll_decButton_relief=1,
            verticalScroll_decButton_geom=self.app.menu_models.dec_geom,
            verticalScroll_decButton_pressEffect=False,
            verticalScroll_decButton_frameColor=(0, 0, 0, 0),
        )

        canvas = self.scroll_frame.getCanvas()
        for i, row in enumerate(rows):
            y = -(i * _ROW_HEIGHT)
            kind = row["kind"]
            if kind == "header":
                self._add_header(canvas, row["text"], y)
            elif kind == "deadzone":
                self._add_deadzone_row(canvas, row, y)
            else:
                self._add_binding_row(canvas, row, y)

    def _add_header(self, canvas, text: str, y: float):
        """
        Add a blue section-header label to the scroll canvas.

        :param canvas: The scroll canvas node to parent the label to.
        :param text: Header text displayed in the label (e.g. ``"Flight
            Bindings"``).
        :param y: Vertical position on the canvas (more negative = further down).
        """
        left = self.app.a2dLeft + 0.14
        scale = 0.055
        width = (self.app.a2dRight - 0.14 - left) / scale
        hdr = DirectLabel(
            parent=canvas,
            text=text,
            scale=scale,
            pos=(left, 0, y - 0.02),
            frameSize=(-0.05, width, -0.35, 0.65),
            frameColor=(0.1, 0.1, 0.3, 0.85),
            text_fg=(0.65, 0.82, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        hdr.setTransparency(True)

    def _add_deadzone_row(self, canvas, row: dict, y: float):
        """
        Add a dead-zone label and editable entry to the scroll canvas.

        The entry is stored in :attr:`_dz_entries` keyed by *row["path"]* so
        that :meth:`_flush_dead_zones` can read back the edited value.

        :param canvas: The scroll canvas node to parent the widgets to.
        :param row: Row descriptor dict with ``"label"``, ``"path"``, and
            ``"value"`` keys.
        :param y: Vertical position on the canvas.
        """
        DirectLabel(
            parent=canvas,
            text=row["label"] + ":",
            scale=0.05,
            pos=(self.app.a2dLeft + 0.2, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        ).setTransparency(True)
        entry = CustomEntry(
            app=self.app,
            pos=(-0.5, 0, y - 0.01),
            initial_text=row["value"],
            width=8,
            parent=canvas,
        )
        self._dz_entries[row["path"]] = entry

    def _add_binding_row(self, canvas, row: dict, y: float):
        """
        Add an action-binding row to the scroll canvas.

        Each row contains the action name, the current binding formatted as
        ``"Axis: …"`` or ``"Button: …"``, and a *Change* button that opens
        :class:`ChangeBindingDialog`.  The value label is stored in
        :attr:`_binding_labels` keyed by *row["path"]* so it can be updated
        in place when the user confirms a new binding.

        :param canvas: The scroll canvas node to parent the widgets to.
        :param row: Row descriptor dict with ``"label"``, ``"path"``, and
            ``"value"`` keys.
        :param y: Vertical position on the canvas.
        """
        inp = self._working_config.get("input_type", "keyboard")

        DirectLabel(
            parent=canvas,
            text=row["label"] + ":",
            scale=0.05,
            pos=(self.app.a2dLeft + 0.2, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.898, 0.839, 0.730, 1.0),
            text_align=TextNode.ALeft,
        ).setTransparency(True)

        val_lbl = DirectLabel(
            parent=canvas,
            text=_format_binding(inp, row["value"]),
            scale=0.045,
            pos=(-0.15, 0, y - 0.015),
            frameColor=(0, 0, 0, 0),
            text_fg=(0.7, 0.85, 1.0, 1.0),
            text_align=TextNode.ALeft,
        )
        val_lbl.setTransparency(True)
        self._binding_labels[row["path"]] = val_lbl

        btn_scale = 0.18
        CustomButton(
            app=self.app,
            pos=(self.app.a2dRight - (0.898 * btn_scale + 0.3), 0, y),
            command=self._open_dialog,
            text="Change",
            scale=btn_scale,
            layout="center",
            extraArgs=[row["path"], row["label"]],
            parent=canvas,
        )

    def _refresh_input_type_buttons(self):
        """
        Visually mark the active input-type button as pressed and reset the
        others so the selector reflects ``_working_config["input_type"]``.
        """
        cur = self._working_config.get("input_type", "keyboard")
        for name, btn in self._input_type_buttons.items():
            if name == cur:
                btn.set_pressed()
            else:
                btn.reset()

    # ------------------------------------------------------------------
    # Row data
    # ------------------------------------------------------------------

    def _make_row_data(self) -> list[dict]:
        """
        Build the ordered list of row descriptors for the scrollable area.

        Returns a flat list of dicts, each with a ``"kind"`` key that is one of:

        - ``"header"`` — section separator with a ``"text"`` key.
        - ``"deadzone"`` — editable numeric field with ``"label"``, ``"path"``,
          and ``"value"`` keys.
        - ``"binding"`` — remappable action with ``"label"``, ``"path"``, and
          ``"value"`` keys.

        Order: dead zones, then global bindings, then one section per context
        (flight, radial menu, …) filtered to the currently selected input type.

        :return: Ordered list of row descriptor dicts.
        """
        cfg = self._working_config
        inp = cfg.get("input_type", "keyboard")
        rows = []

        rows.append({"kind": "header", "text": "Dead Zones"})
        for key, val in cfg.get("dead_zones", {}).items():
            rows.append(
                {
                    "kind": "deadzone",
                    "label": key.replace("_", " ").capitalize(),
                    "path": ("dead_zones", key),
                    "value": str(val),
                }
            )

        if cfg.get("global"):
            rows.append({"kind": "header", "text": "Global Bindings"})
            for action, binding in cfg["global"].items():
                rows.append(
                    {
                        "kind": "binding",
                        "label": action.replace("_", " ").capitalize(),
                        "path": ("global", action),
                        "value": str(binding) if binding is not None else "",
                    }
                )

        for ctx_name, ctx_data in cfg.get("contexts", {}).items():
            bindings = ctx_data.get(inp, {})
            if not bindings:
                continue
            label = _CONTEXT_LABELS.get(ctx_name, ctx_name.replace("_", " ").title())
            rows.append({"kind": "header", "text": f"{label} Bindings"})
            for action, val in bindings.items():
                rows.append(
                    {
                        "kind": "binding",
                        "label": action.replace("_", " ").capitalize(),
                        "path": ("contexts", ctx_name, inp, action),
                        "value": str(val) if val is not None else "",
                    }
                )

        return rows

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_file(path) -> dict:
        """
        Parse a YAML configuration file and return its contents as a dict.

        :param path: Path to the YAML file.
        :return: Parsed configuration dict.
        """
        with open(path, "r") as f:
            return yaml.safe_load(f)

    def _flush_dead_zones(self):
        """
        Write current entry widget values back into :attr:`_working_config`.

        Called before saving or switching the input type so that typed dead-zone
        edits are not silently discarded.  Values are converted to ``float`` when
        the original YAML value was a float; strings that cannot be parsed are
        kept as strings.
        """
        for path, entry in self._dz_entries.items():
            val = entry.get().strip()
            d = self._working_config
            for key in path[:-1]:
                d = d[key]
            orig = d.get(path[-1])
            if isinstance(orig, float):
                try:
                    val = float(val)
                except ValueError:
                    pass
            d[path[-1]] = val

    # ------------------------------------------------------------------
    # Dialog
    # ------------------------------------------------------------------

    def _open_dialog(self, path: tuple, label: str):
        """
        Open a :class:`ChangeBindingDialog` for the action at *path*.

        Silently ignored if a dialog is already open, preventing stacked dialogs.

        :param path: Config-tree path tuple identifying the binding (e.g.
            ``("contexts", "flight", "keyboard", "fire")``).
        :param label: Human-readable action name shown inside the dialog.
        """
        if self._active_dialog is not None:
            return
        inp = self._working_config.get("input_type", "keyboard")
        self._active_dialog = ChangeBindingDialog(
            app=self.app,
            action=label,
            input_type=inp,
            button_geom=self.app.menu_models.button_geom,
            command=lambda _, t, v: self._on_confirmed(path, t, v),
        )

    def _on_confirmed(self, path: tuple, new_type: str | None, new_value: str | None):
        """
        Callback fired by :class:`ChangeBindingDialog` when the user confirms a
        new binding.

        Updates :attr:`_working_config` and refreshes the binding's display label
        in place.  Does nothing when *new_value* is ``None`` (the user cancelled).

        :param path: Config-tree path tuple of the binding that changed.
        :param new_type: ``"button"`` or ``"axis"``; drives the display prefix in
            :func:`_format_binding`.
        :param new_value: Hardware name to store (e.g. ``"space"`` or
            ``"gamepad_lshoulder"``), or ``None`` on cancel.
        """
        self._active_dialog = None
        if new_value is None:
            return
        d = self._working_config
        for key in path[:-1]:
            d = d[key]
        d[path[-1]] = new_value
        inp = self._working_config.get("input_type", "keyboard")
        if path in self._binding_labels:
            self._binding_labels[path]["text"] = _format_binding(
                inp, new_value, new_type
            )

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def _select_input_type(self, input_type: str):
        """
        Switch the active input type and rebuild the binding list.

        Flushes unsaved dead-zone edits before rebuilding so they are not lost.
        Silently ignored if a dialog is open.

        :param input_type: One of ``"keyboard"``, ``"gamepad"``, or
            ``"joystick"``.
        """
        if self._active_dialog is not None:
            return
        self._flush_dead_zones()
        self._working_config["input_type"] = input_type
        self._refresh_input_type_buttons()
        self._rebuild_scroll()

    def _save(self):
        """
        Flush edits, write the configuration to disk, and rebuild the reader.

        Writes :attr:`_working_config` to ``configuration/configuration.yaml``
        then reinitialises the running
        :class:`~space_flight.ui.input_reader.InputReader` so the new bindings
        are active in the current session without a restart.  Finally navigates
        back to the main menu.  Silently ignored if a dialog is open.
        """
        if self._active_dialog is not None:
            return
        self._flush_dead_zones()
        with open(_CONFIG_FILE, "w") as f:
            yaml.dump(
                self._working_config, f, default_flow_style=False, sort_keys=False
            )
        self._saved_config = copy.deepcopy(self._working_config)
        # Rebuild the InputReader so the new bindings take effect immediately.
        # reader_factory re-reads the YAML, sets app.bindings, and re-registers
        # all accept() callbacks with the updated hardware names.
        self.app.input_reader.clean()
        self.app.input_reader = reader_factory(app=self.app)
        self.app.state_manager.pop()
        self.app.state_manager.push(self.app.state_manager.MAIN_MENU_STATE)

    def _cancel(self):
        """
        Discard all unsaved changes and return to the main menu.

        The YAML file on disk is not modified.  Silently ignored if a dialog is
        open.
        """
        if self._active_dialog is not None:
            return
        self.app.state_manager.pop()
        self.app.state_manager.push(self.app.state_manager.MAIN_MENU_STATE)

    def _load_default(self):
        """
        Replace the working configuration with the factory defaults.

        Reads from ``configuration/default_configuration.yaml`` and rebuilds the
        binding list.  Changes are not written to disk until the user clicks
        *Save*.  Silently ignored if a dialog is open.
        """
        if self._active_dialog is not None:
            return
        self._working_config = self._load_file(_DEFAULT_CONFIG_FILE)
        self._refresh_input_type_buttons()
        self._rebuild_scroll()
