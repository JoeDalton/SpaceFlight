# Menus

`menus` holds every non-gameplay screen — splash, main menu, level selection,
pause, settings, and the level-end/radial overlays — built as `BaseState`
subclasses pushed onto the app's `StateManager` (see
[docs/global_architecture.md](global_architecture.md)). This page is the guided
tour; the per-class API is in the [code reference](apidocs/index.rst).

All of it lives in [`src/space_flight/menus/`](../../src/space_flight/menus/).

## Mental model

- Every screen is a `BaseState`: `enter()` builds its widgets, `exit()`
  destroys them, and navigation goes only through
  `state_manager.push`/`pop`/`replace`/`clear` — states don't reach into each
  other.
- [`menu_utils.py`](../../src/space_flight/menus/menu_utils.py) is the shared
  widget toolkit, so styling and scrolling stay consistent and each screen's
  code only expresses layout and behaviour.
- The three settings screens share one pattern: edit an in-memory **working
  copy** of a YAML config, and only write it to disk (and apply it live where
  possible) on *Save*. *Cancel* discards the working copy. On the graphics and
  input screens, *Default* reloads factory values into it without touching
  disk; the gameplay screen has presets instead.

## `menu_utils.py` — shared widgets

- **`MenuModels`** loads the shared egg models (button, scrollbar thumb,
  inc/dec arrows) once into the `(ready, click, hover, disabled)` geometry
  tuples `DirectButton`/`DirectScrollBar` expect, and registers the game's
  dialog background as Panda3D's default dialog geometry. Built by
  `SpaceFlightSimulator` and read as `app.menu_models`.
- **`CustomButton`** wraps `DirectButton` with the game's geometry and styling,
  `layout="left"/"center"/"right"` text alignment, and
  `set_pressed()`/`reset()` to lock a button in its "click" look — used for
  radio-style selectors (input type, display mode, level list).
- **`CustomEntry`**, **`CustomSlider`**, **`CustomCheckButton`** apply the same
  treatment to `DirectEntry`/`DirectSlider`/`DirectCheckButton`, with thin
  `get`/`set`, `get_value`/`set_value` and `get_value` accessors respectively.
- **`CustomDropDown`** is a drop-down list made of `CustomButton`s, over
  `(label, value)` options. Its head shows the selected label and a down
  arrow (the scrollbars' `inc_geom`); a click opens the option buttons stacked
  under it, the selected one pressed. The list stays open until an option is
  clicked (`select`: close, select, then `command(value)`) or the user clicks
  anywhere else (closing it, value unchanged). For that, `open()` attaches the
  list to `aspect2d` last, in the `gui-popup` bin, so it is drawn and clicked
  above every other widget (Panda3D's GUI gives a click to the last traversed
  widget), with a transparent full-screen frame first under it to catch the
  clicks elsewhere. `set_value` selects without calling the command. Unlike
  `DirectOptionMenu`, it needs no held click and looks like the other
  buttons.
- **`ProgressBar`** is a white fill bar with a rotating random hint ("blurb")
  above it, used by `SplashState` while assets load.
- **`ScrollableList`** pairs a `DirectScrolledFrame` (used only as a
  border/clip) with a `DirectScrollBar` that moves a plain "content" node the
  caller parents its rows to, so the canvas never resizes. API:
  `rebuild(n_rows)` → content node, `row_y(i)`, `wheel_scroll(step)`,
  `destroy()`, plus `add_header`/`add_row_label`/`add_checkbox` row helpers.
  Every settings screen uses it.

## Startup and top-level navigation

- **[`splash_state.py`](../../src/space_flight/menus/splash_state.py)** —
  `SplashState` is the first state pushed by `SpaceFlightSimulator`. It opens a
  small undecorated window with the splash image and a `ProgressBar`, starts
  `asset_manager.load_game_assets`, and once loading finishes fades out and
  replaces itself with `MainMenuState`. Its `exit()` calls
  `graphics_manager.open_game_window()` to swap to the real game window sized
  per the saved graphics settings.
- **[`main_menu_state.py`](../../src/space_flight/menus/main_menu_state.py)** —
  `MainMenuState`: *Play*, *Settings*, *Quit Game*, routing to
  `LevelSelectionMenuState` / `SettingsMenuState` / `sys.exit()`.
- **[`level_selection_menu_state.py`](../../src/space_flight/menus/level_selection_menu_state.py)** —
  `LevelSelectionMenuState` builds its `LEVELS` list (name + description) from
  the level registry `space_flight.game.levels.LEVELS` (see
  [docs/game.md](game.md#levels)), so it can't drift from what `FlightState`
  can build. Selecting a level shows its description and a *Start Game*
  button, which sets `app.configuration["selected_level"]` and replaces the
  current state with `GAME_STATE`.
- **[`settings_menu_state.py`](../../src/space_flight/menus/settings_menu_state.py)** —
  `SettingsMenuState` is a landing screen (reached from the main and pause
  menus) routing to `GAMEPLAY_SETTINGS_STATE`, `INPUT_SETTINGS_STATE` or
  `GRAPHICS_SETTINGS_STATE`.

## In-session overlays

- **[`pause_menu_state.py`](../../src/space_flight/menus/pause_menu_state.py)** —
  `PauseMenuState` is pushed over a running `FlightState` and, keeping the
  default `PAUSES_BELOW = True`, pauses it. It pushes a
  `PauseMenuInputContext` (see [docs/ui.md](ui.md)) so gameplay input is
  blocked while it is up. Buttons resume, open settings, return to the main
  menu (`state_manager.clear()` then `replace(MAIN_MENU_STATE)`), or quit;
  the last two save the flight record first when `RECORD_GAME` is set (see
  [docs/game.md](game.md#record)).
- **[`level_end_state.py`](../../src/space_flight/menus/level_end_state.py)** —
  `LevelEndState` is the terminal screen for every outcome (`victory`,
  `defeat`, `death`), each with its own title and tint (`_OUTCOMES`) plus an
  optional explanatory `text`. It is pushed by `FlightState.end_level`
  (skipped headless), called by the level's `Mission` (see
  [docs/game.md](game.md#mission-scripting)) or once the player's death spin
  ends. It pauses the game beneath it; its buttons mirror the pause menu's
  return-to-main-menu and quit.
- **[`radial_menu_state.py`](../../src/space_flight/menus/radial_menu_state.py)** —
  `RadialMenuState` is a generic label/callback wheel, opened by the
  `radial_menu` binding. It sets `PAUSES_BELOW = False` so the game keeps
  simulating, and takes its options as push kwargs (`on_select`,
  `slice_labels`) — `Player.open_radial_target_menu` (see
  [docs/actors.md](actors.md)) uses it for the target filter. Drawing lives in
  `RadialMenuVisual`; direction-to-slice mapping and trigger handling live in
  `RadialMenuInputContext` (see [docs/ui.md](ui.md)), so the visual knows
  nothing about input hardware.

## Settings screens

- **[`gameplay_settings_menu_state.py`](../../src/space_flight/menus/gameplay_settings_menu_state.py)** —
  `GameplaySettingsMenuState` edits a deep copy of `GameplaySettings.config`
  (see [docs/global_architecture.md](global_architecture.md#gameplay_settingspy--difficulty)).
  A *Difficulty* `CustomDropDown` above the scrollable rows lists the presets,
  in the presets file's order, then *Custom*. Picking a preset loads its
  values into the working copy and rebuilds the rows; picking *Custom* keeps
  the current values. `make_row_data()` emits one header per side (Player,
  Bots), each listing the settings that side has, in `_ROW_ORDER`: sliders
  (`_SLIDERS`: lock delay, lock angle, assist angle, shot deviation, damage
  multipliers) and checkboxes (`_CHECKBOXES`: auto-aim, lead indicator).
  Editing any of them switches the drop-down to *Custom* (`mark_custom`).
  *Save* calls `GameplaySettings.save()`; every setting applies from the next
  mission, as an on-screen warning says. There is no *Default*: the `normal`
  preset is the default.

  The slider ranges are the limits `GameplaySettings.sanitise()` clamps to,
  imported from it, so a value shown is never clamped on save. Each slider
  snaps to a step (e.g. 0.05 s, 1 degree). A slider reports its value when it
  is built, slightly off (single precision): `on_slider` only stores, and
  switches to *Custom*, when the snapped value actually changes, so building
  the rows never does. Like the graphics screen's discrete sliders, it never
  writes the snapped value back to the thumb.
- **[`graphics_settings_menu_state.py`](../../src/space_flight/menus/graphics_settings_menu_state.py)** —
  `GraphicsSettingsMenuState` edits a deep copy of `GraphicsSettings.config`
  (see [docs/global_architecture.md](global_architecture.md)). `make_row_data()`
  emits one header per top-level section of `default_graphics.yaml` (Display,
  Render, Antialiasing, Compatibility, Clouds, HUD): display mode is a button
  group, render/reflection/mirror scale are continuous sliders (over the limits
  `GraphicsSettings.sanitise()` clamps to, imported from it), MSAA and cloud
  quality are sliders snapped to discrete stops (`_DISCRETE_SLIDERS`, cheapest
  first so dragging right always costs more), and FXAA, *Alternate Model
  Orientation* (a manual workaround for glTF models loading mis-rotated on
  some systems) and *FPS Counter* are checkboxes. *Save* calls
  `GraphicsSettings.save()` (re-sanitises and persists) and
  `GraphicsManager.apply_window_settings()`, so the display mode changes
  live; everything else takes effect on the next level load, as an on-screen
  warning says.

  The discrete sliders deliberately do *not* write the snapped value back to
  the thumb: `PGSliderBar` throws its ADJUST event asynchronously, so setting
  the value from inside the handler re-enqueues ADJUST forever and freezes the
  game.
- **[`input_settings_menu_state.py`](../../src/space_flight/menus/input_settings_menu_state.py)**:
  - **`InputSettingsMenuState`** loads `configuration.yaml` and lists the dead
    zones, the global bindings, and each context's bindings for the selected
    input type (keyboard/gamepad/joystick), with checkboxes for boolean
    options such as `invert_*` (`make_row_data`/`rebuild_scroll`). Switching
    input type flushes typed dead-zone edits, then rebuilds the list. *Save*
    writes the YAML, rebuilds the live `InputReader` (`reader_factory`) and
    calls `InputContextStack.refresh_all_bindings`, so remapped controls work
    without a restart.
  - **`ChangeBindingDialog`** is the "press any key" dialog behind each row's
    *Change* button, modelled on Panda3D's `mappingGUI.py` gamepad sample.
    While open it redirects Panda3D's button throwers to two generic listener
    events, so any keyboard/gamepad/joystick button is captured by raw
    hardware name, and polls every device's axes each frame against a baseline
    snapshot (`watchControls`), so a deliberate axis movement is captured as
    an axis binding while resting drift is ignored. The throwers are restored
    on close (OK or Cancel).
  - **`format_binding()`** turns a stored hardware name into a display label
    such as "Axis: Left X" or "Button: Space".

## Where things live

Every module above sits directly under
[`src/space_flight/menus/`](../../src/space_flight/menus/); the
[code reference](apidocs/index.rst) has the full per-class API.
