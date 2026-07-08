# Menus

`menus` holds every non-gameplay screen — splash, main menu, level selection,
pause, settings, and the level-end/radial overlays — built as
[`BaseState`](global_architecture.md) subclasses pushed onto the app's
`StateManager` (see [docs/global_architecture.md](global_architecture.md)).
This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](docs/).

All of it lives in [`src/space_flight/menus/`](../src/space_flight/menus/).

## Mental model

- Every screen is a `BaseState`: `enter()` builds its widgets, `exit()`
  destroys them, and navigation is expressed entirely through
  `state_manager.push`/`pop`/`replace`/`clear` calls — states don't reach
  into each other directly.
- [`menu_utils.py`](../src/space_flight/menus/menu_utils.py) is the shared
  widget toolkit: every menu screen builds its UI from `CustomButton`,
  `CustomEntry`, `CustomSlider`, `CustomCheckButton` and `ProgressBar`
  rather than raw `DirectGui` widgets, so styling (colours, geometry, hover
  states) stays consistent app-wide and each screen's own code only
  expresses layout and behaviour.
- The two settings screens
  ([`input_settings_menu_state.py`](../src/space_flight/menus/input_settings_menu_state.py),
  [`graphics_settings_menu_state.py`](../src/space_flight/menus/graphics_settings_menu_state.py))
  share one pattern end to end: load a YAML config, edit a deep-copied
  **working copy** in memory, and only write it back to disk (plus apply it
  live where possible) on *Save* — *Cancel* simply discards the working copy,
  *Default* reloads factory values into it without touching disk.

## `menu_utils.py` — shared widgets

[`menu_utils.py`](../src/space_flight/menus/menu_utils.py) has no state logic
of its own; it's a small design system every screen builds on:

- **`MenuModels`** loads the game's shared egg models once (button, thumb,
  inc/dec scrollbar arrows) into the four-state `(ready, click, hover,
  disabled)` geometry tuples `DirectButton`/`DirectScrollBar` expect, and
  registers the game's dialog background as Panda3D's default dialog
  geometry. Constructed once by `SpaceFlightSimulator` (see
  [docs/global_architecture.md](global_architecture.md)) and referenced as
  `app.menu_models` by every widget below.
- **`CustomButton`** wraps `DirectButton` with the game's button geometry and
  styling baked in, exposing `layout="left"/"center"/"right"` for text
  alignment plus `set_pressed()`/`reset()` to lock a button into its "active"
  visual state — used throughout for radio-button-style selectors (input
  type, display mode) where one option is persistently highlighted rather
  than only reacting to hover.
- **`CustomEntry`**, **`CustomSlider`**, **`CustomCheckButton`** are the same
  pattern applied to `DirectEntry`/`DirectSlider`/`DirectCheckButton` — game
  palette and geometry pre-applied, thin `get`/`set`/`destroy` wrappers.
- **`ProgressBar`** is a minimal white fill-bar plus a rotating "blurb" hint
  label above it (a random string swapped on a timer), used by
  `SplashState` while assets load.

## Startup and top-level navigation

- **[`splash_state.py`](../src/space_flight/menus/splash_state.py)**'s
  `SplashState` is the very first state pushed by `SpaceFlightSimulator`
  (see [docs/global_architecture.md](global_architecture.md)). It opens a
  small undecorated splash window, shows the splash image with a
  `ProgressBar`, and kicks off `asset_manager.load_game_assets` (see
  [docs/global_architecture.md](global_architecture.md)); when loading
  finishes it fades the splash out and replaces itself with `MainMenuState`.
  Its `exit()` calls `graphics_manager.open_game_window()` to swap from the
  small splash window to the real game window sized per the saved graphics
  settings.
- **[`main_menu_state.py`](../src/space_flight/menus/main_menu_state.py)**'s
  `MainMenuState` is just three buttons (Play, Settings, Quit) routing to
  `LevelSelectionMenuState` / `SettingsMenuState` / `sys.exit()`.
- **[`level_selection_menu_state.py`](../src/space_flight/menus/level_selection_menu_state.py)**'s
  `LevelSelectionMenuState` hardcodes the `LEVELS` list (name + description,
  kept in sync with the level builders under
  [`game/levels/`](../src/space_flight/game/levels/) — see
  [docs/game.md](game.md)) and renders it as a scrollable button list.
  Selecting a level shows its description and a *Start Game* button;
  starting sets `app.configuration["selected_level"]` (the key
  `FlightState._build_upfront`/`_make_build_generator` dispatch on) and
  replaces the current state with `GAME_STATE`.
- **[`settings_menu_state.py`](../src/space_flight/menus/settings_menu_state.py)**'s
  `SettingsMenuState` is a small landing screen (reached from both the main
  menu and the pause menu) routing to `INPUT_SETTINGS_STATE` or
  `GRAPHICS_SETTINGS_STATE`.

## In-session overlays

- **[`pause_menu_state.py`](../src/space_flight/menus/pause_menu_state.py)**'s
  `PauseMenuState` is pushed over a running `FlightState`; because it
  doesn't override `PAUSES_BELOW`, pushing it pauses the game underneath (see
  [docs/game.md](game.md)'s `FlightState.pause`). It also pushes a
  `PauseMenuInputContext` (see the [`ui`](../src/space_flight/ui/) input
  stack) so gameplay input is captured while the menu is up. Buttons resume
  the game, open settings, return to the main menu (`state_manager.clear()`
  then `replace(MAIN_MENU_STATE)`, discarding every state below), or quit —
  quitting saves the flight record first when `RECORD_GAME` is set (see
  [docs/game.md](game.md)'s `Record`).
- **[`level_end_state.py`](../src/space_flight/menus/level_end_state.py)**'s
  `LevelEndState` is the terminal screen for any outcome — `victory`,
  `defeat`, or `death` — each with its own title text and colour tint
  (`_OUTCOMES`) plus an optional explanatory `text`. It's pushed by
  `Scenario`'s `end_level` action (see [docs/game.md](game.md)) or by
  `FlightState.update_game_world_task` directly on player death. Its two
  buttons mirror the pause menu's return-to-main-menu and quit.
- **[`radial_menu_state.py`](../src/space_flight/menus/radial_menu_state.py)**'s
  `RadialMenuState` is the player's weapon/target-filter picker, opened by
  holding a bound trigger. It declares `PAUSES_BELOW = False` so the game
  keeps simulating while the wheel is open (matching the hyperspace overlay
  pattern in [docs/game.md](game.md)) and is fully parameterised at push
  time via kwargs (`on_select`, `slice_labels`) rather than a fixed set of
  options, which is how `Player.open_radial_target_menu` (see
  [docs/actors.md](actors.md)) reuses it for the target filter list. Two
  pieces split cleanly: `RadialMenuVisual` only draws and highlights the
  slice labels around a circle; the actual direction-to-slice mapping and
  trigger handling live in `RadialMenuInputContext` (see
  [`ui/input_context.py`](../src/space_flight/ui/)), keeping the visual
  ignorant of input hardware.

## Settings screens

Both settings screens follow the working-copy pattern described above, built
around their respective config owner (see
[docs/global_architecture.md](global_architecture.md) for `GraphicsSettings`):

- **[`graphics_settings_menu_state.py`](../src/space_flight/menus/graphics_settings_menu_state.py)**'s
  `GraphicsSettingsMenuState` is the simpler of the two: display mode is a
  small button group, render/reflection/mirror scale are `CustomSlider`s
  mapped through `_get_by_path`/`_set_by_path` onto the nested config dict,
  MSAA is a slider snapped to discrete stops (`_MSAA_VALUES`), and FXAA is a
  checkbox. On save it calls `GraphicsSettings.save()` (persists +
  re-sanitises) and `GraphicsManager.apply_window_settings()` for the parts
  that can change live; a warning label makes clear that render-scale/AA
  changes need the next level load to take effect (see
  [docs/global_architecture.md](global_architecture.md) for why).
- **[`input_settings_menu_state.py`](../src/space_flight/menus/input_settings_menu_state.py)**
  is the largest and most involved menu screen in the game:
  - **`InputSettingsMenuState`** builds a scrollable, per-input-type
    (keyboard/gamepad/joystick) list of every dead zone and every action
    binding read from `configuration.yaml`, laid out via manually positioned
    rows (`make_row_data`/`rebuild_scroll`) rather than a native scrolled
    list, driven by a custom `DirectScrollBar` wired to move a content node.
    Selecting a different input type flushes any typed dead-zone edits, then
    rebuilds the row list filtered to that type's bindings. Saving writes the
    YAML, then rebuilds the live `InputReader` (`reader_factory`) and asks
    the `InputContextStack` to refresh all bindings, so remapped controls
    take effect immediately without restarting.
  - **`ChangeBindingDialog`** is the "press any key" capture dialog opened by
    each row's *Change* button. While open, it redirects Panda3D's button
    throwers to two generic listener events so *any* keyboard/gamepad/
    joystick button can be captured as a raw hardware name, and separately
    polls every attached device's axes each frame against a baseline
    snapshot (`watchControls`) so a deliberate axis movement can be
    distinguished from resting-position drift and captured as an axis
    binding instead. Restores the throwers to normal on close either way
    (OK or Cancel). The implementation explicitly mirrors Panda3D's own
    `mappingGUI.py` gamepad sample, credited in the class docstring.
  - **`format_binding()`** is the small shared helper that turns a raw stored
    hardware name back into a human-readable "Axis: Left X" / "Button:
    Space" label for display.

## Where things live

Every module in this page lives directly under
[`src/space_flight/menus/`](../src/space_flight/menus/): shared widgets in
`menu_utils.py`, top-level navigation in `splash_state.py`/
`main_menu_state.py`/`level_selection_menu_state.py`/`settings_menu_state.py`,
in-session overlays in `pause_menu_state.py`/`level_end_state.py`/
`radial_menu_state.py`, and the two settings editors in
`graphics_settings_menu_state.py`/`input_settings_menu_state.py`. The
auto-generated [code reference](docs/) has the full per-class API.
