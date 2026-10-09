# UI

`ui` is the player-facing layer between raw hardware and gameplay: the input
pipeline (hardware polling → contexts that interpret it), the HUD, the
rear-view mirror, and player waypoint guidance. This page is the guided tour;
the per-class API is in the [code reference](apidocs/index.rst).

All of it lives in [`src/space_flight/ui/`](../../src/space_flight/ui/).

## Mental model

- Input has two layers, each with one job:
  [`input_reader.py`](../../src/space_flight/ui/input_reader.py) only knows
  *hardware* (which raw button/axis is active this frame — no game logic);
  [`input_context.py`](../../src/space_flight/ui/input_context.py) only knows
  *meaning* (what a bound action does in the current game mode). A new game
  mode means a new `InputContext` pushed on the stack — never touching the
  reader.
- Only the **top** of the `InputContextStack` receives input each frame, so
  pushing a context (e.g. the radial menu over flight) blocks whatever is
  beneath it without either context knowing about the other.
- Every action name (`"fire"`, `"pause"`, `"throttle_up"`, ...) is resolved
  through the YAML bindings (`configuration/bindings.yaml`), never
  hardcoded to a key. Every device is live at once: the readers' `InputState`s
  are merged, and an action fires from whichever device it is bound on.
- `HUD`, `AimHUD` and `PlayerWaypoints` follow the scene-piece lifecycle
  (see [docs/scenes.md](scenes.md)): construct with `game`, register a
  per-frame update in `game.method_lists`, `clean()`. `RearViewMirror` (owned
  by `Player`) and `WaypointMarker` (driven by `PlayerWaypoints`) have no
  per-frame task, only `clean()`.

## `input_reader.py` — the hardware layer

Each frame every reader subclass rebuilds a plain `InputState` snapshot
(`buttons`/`repeats`/`releases`/`axes`) of its own device, from that device's
bindings (its `device_type`: `keyboard`, `gamepad` or `joystick`):

- **Hybrid detection.** **Polling** is the primary source: `read_all_buttons()`
  each frame, compared with the previous frame to derive pressed/held/released.
  **`accept()` events** are a safety net for a button pressed *and* released
  between two polls, which polling alone would miss. `event-repeat` is
  deliberately unused — held state comes from polling only.
- **`KeyboardReader`** polls Panda3D's `MouseWatcher` for every bound key.
  Keyboards have no analogue axes, so `read_axes` is a no-op and flight axes
  are synthesised in `FlightInputContext`.
- **`GamepadReader`** and **`JoystickReader`** poll their device, apply dead
  zones (`apply_dead_zone()`: zeroes the band and shifts the rest down so output starts at
  0 at its edge; not renormalised, so full deflection gives `1 - dead_zone`),
  and handle hot-plugging (falling back to another device of the same class;
  with none attached they simply report nothing). Only
  `GamepadReader` registers per-button safety-net events; most flight-stick
  buttons don't generate reliable Panda3D events, so `JoystickReader` is
  polling-only.
- **The Windows Unicode monkey-patch.** `_patched_attachInputDevice` /
  `_patched_detachInputDevice` replace two `ShowBase` methods that read
  Panda3D's `device.name`, which raises `UnicodeDecodeError` for some
  controllers. `safe_device_name()` provides a printable name instead, with a
  three-tier fallback (direct read → re-encode → synthesised
  `VID_xxxx&PID_xxxx`).
- **Readers are `DirectObject`s**, so each one's `accept()` callbacks (e.g.
  the gamepad and joystick readers' `connect-device`) never replace another's,
  and `clean()` is just `ignoreAll()`.
- **`CompositeInputReader`** polls the three readers and merges their states
  (hardware names never collide across devices). It also tracks
  `last_device`: the device of the last button press, or of the last axis
  pushed past 0.5 (crossing it, so a lever resting forward does not keep
  claiming it). `InputContext.key_label` uses it to show prompts for the
  device the player is using. It also sets `InputState.mouse_moved`, and
  hides the mouse cursor on such device input (menus and flight alike),
  showing it again as soon as the mouse moves. While it is hidden, the GUI
  (`aspect2d`'s `PGTop`) watches a "blind" `MouseWatcher` outside the data
  graph, so the invisible pointer hovers nothing, not even the widgets of a
  menu newly opened under it.
- **`reader_factory(app)`** loads `bindings.yaml` onto `app.bindings` and
  builds the `CompositeInputReader`. It runs at startup and again when input
  settings are saved (see [docs/menus.md](menus.md#settings-screens)), so
  remapped bindings apply without a restart.

## `input_context.py` — the meaning layer

`InputContext` is the abstract base (`consume(state)` is the only required
method; `on_activate`/`on_deactivate`/`clean`/`refresh_bindings` are optional
hooks). `InputContextStack.dispatch()` only calls the top context, and
`push`/`pop` handle (de)activation. Concrete contexts:

- **`FlightInputContext`** — the gameplay context: ship axes, weapons, boost,
  targeting, mirror, radial menu, head-look and pause, read from
  `contexts.flight` for every device at once (`bound_keys`). Weapons are `fire` (lasers),
  `fire_secondary` (the selected bomb, rocket or missile launcher, while
  held), `cycle_secondary` (on press) and `drop_flare` (while held); held
  launches are paced by each launcher's reload, and a newly selected launcher
  reloads before it can fire. Energy distribution (see
  [docs/actors.md](actors.md#energy-management)) is set on press by
  `energy_engines`, `energy_lasers`, `energy_shields` and `energy_balanced`
  (keyboard 1-4), or cycled by `cycle_energy` (gamepad, joystick). Its
  `pressed`/`held`/`active`/`released` helpers are true when the action's key
  on any device is. `flight_axes` combines the devices:
  - yaw/pitch/roll add up, clamped to `[-1, 1]`: the keyboard's are synthesised
    from key presses through `low_pass_filter_first_order` (so a key press
    doesn't snap to full deflection), and the gamepad/joystick axes are read
    by `axis`, applying the `invert_*` bindings;
  - the throttle follows the device that last touched it (`update_throttle`):
    an analog throttle takes it over once moved more than `THROTTLE_TAKEOVER`
    from where it last left it (or from where it was first seen, so a lever
    resting forward at spawn does nothing), and the keyboard takes it over
    while a throttle key is held, stepping from the current value (clamped to
    `[0, 1]`).
- **`MenuInputContext`** — pushed by every menu's `MenuNavigator` (see
  [docs/menus.md](menus.md#navigation)), it turns input into menu navigator calls:
  - keyboard and gamepad keys are hardcoded (`MENU_BUTTONS` in
    `input_reader.py`, polled whatever the bindings): arrows / d-pad move,
    Enter or Space / A confirm, Escape / B go back; the joystick reuses its
    flight bindings (`JOYSTICK_MENU_ACTIONS`: the `view_*` hat moves, inverted
    so that pushing it forward moves up, `fire` confirms, `fire_secondary`
    goes back), its button numbers varying between sticks. Every device's flight `pause` key also goes back, so it closes
    the pause menu;
  - the gamepad left stick and the joystick's radial-menu axes move once
    pushed past `MENU_AXIS_THRESHOLD`, along their dominant axis; a stick
    already pushed when the menu opens is ignored until re-centred;
  - a held direction repeats after `MENU_REPEAT_DELAY`, then every
    `MENU_REPEAT_INTERVAL`, on the real clock (game time is frozen in the
    pause menu);
  - moving the mouse hides the focus and gives the hover look back to the
    widget under the pointer (`MenuNavigator.refresh_hover`).

  Sitting above `FlightInputContext` (pause menu, level end), it freezes the
  ship's controls with no extra logic. `InputContextStack.remove(context)`
  lets a menu remove its own context wherever it is, a no-op once the stack
  was cleaned (e.g. leaving the level clears the flight state first).
- **`HyperspaceInputContext`** — the same blocking pattern for the hyperspace
  overlay's "press key to drop out" prompt (see [docs/game.md](game.md)): it
  fires its callback once on the `drop_hyperspace` key (of any device), then
  ignores input
  until the overlay pops it.
- **`RadialMenuInputContext`** — drives the radial target-filter menu (see
  [docs/menus.md](menus.md#in-session-overlays)). Each frame `read_direction`
  gets a 2D direction (each device's analog axes, or directional keys combined
  into a vector, summed over the devices); once its magnitude clears `min_magnitude`, `angle_to_slice` maps it
  to a slice (0 at the top, clockwise), and `on_hover` is called so the
  overlay highlights it live. Releasing the trigger (any device's
  `radial_menu` key) pops the radial menu
  state and calls `on_select` with the slice (or `None`).

## `hud.py` — heads-up display

[`hud.py`](../../src/space_flight/ui/hud.py) has two independent overlays:

- **`HUD`** — a debug panel when `DEBUG_HUD` is set (player
  speed/health/shield, game time, team strengths, target lock, plus
  lead-bot/turret lines wrapped in `try`/`except AttributeError` so it
  tolerates levels without them), an FPS counter (graphics setting
  `hud.fps_counter`), and two timed message lines: `set_event_text` /
  `set_chatter_text` store a string plus an expiry time, and
  `clear_scenario_hud` blanks each once its game-time deadline passes; the
  chatter line sits at the top of the screen, above the mirror. They
  are driven by the mission's `hud` and `speech` actions (see
  [docs/scenario_scripting.md](scenario_scripting.md#actions)). Bottom right, an
  `OrdnanceHUD` shows the secondary weapons of the cycle
  (`Fighter.secondary_cycle`) with their stock, spent ones at x0, on a
  [`RollingDrum`](#utilspy--generic-ui-items), the selected one facing the
  player. Under it, a line always shows the flares left. Bottom left, an
  `EnergyHUD` shows the player's gauges, left to right: HP (pink half-ring,
  health at its centre), lasers (red column), engines (green half-ring, speed
  at its centre) and shields (blue half-ring, shield strength at its centre,
  hidden on unshielded ships). The gauge of the system power is redirected to
  is brighter. Its layout, colours and brightness are module constants.
- **`AimHUD`** — the aiming cues, placed each frame by projecting world
  points into screen space (`project_to_screen`: `cam.getRelativePoint` +
  `lens.project`):
  - a **crosshair** where the lasers go: the ship's nose direction, projected
    as a point at infinity (the cannons fire parallel to it), so it stays true
    when the head is jolted or turned. It turns red while auto-aim is locked
    (shots lead the target).
  - a **lead indicator** where to aim to hit the target: auto-aim's predicted
    position (`AutoAim.predict_target_position`, see
    [docs/ai.md](ai.md#autoaim)). Shown only with a target and when that point
    is ahead and on screen, and only if the player's `lead_indicator`
    [gameplay setting](global_architecture.md#gameplay_settingspy--difficulty)
    is on (read once, when the HUD is built).
  - a **target box** with distance/name labels. In view, the box encircles the
    target. It turns red while the armed missile is locked on the target
    (`Fighter.is_missile_locked`): a missile launched then is guided to it.
    It is updated first, as it drops a target that has just died. Off-screen
    (outside the FoV *or* behind the camera) it is pinned to the screen border
    along the true bearing, by scaling the projected vector to meet the edge
    rectangle — clamping each axis separately would snap it to jittering
    corners. Behind the camera the projection is mirrored, so its sign is
    flipped; the depth is clamped away from zero so the projection stays
    finite near the camera's XZ plane (details in the code comments). The
    label shows the target's parent name, falling back to the target's own
    name (subsystems). If the target has a scan (`pawn.scan`, a `ScanState`
    from [`actors/scan.py`](../../src/space_flight/actors/scan.py)), a
    transparent bar fills the box in proportion to its progress — yellow
    while scanning, then green (clear) or red (contraband) — and its status
    ("SCANNING 42%", "CLEAR", "CONTRABAND") is appended to the name. Only
    that attribute is read, so any pawn a mission makes scannable gets the
    bar.
  - an **incoming missile warning**, while guided missiles home on the player
    (`nearest_incoming`, see [docs/ai.md](ai.md#guided-missiles-a-navigator-and-a-pilot-no-tactician)):
    a red line under the crosshair with the nearest missile's distance (and
    their count if several), blinking faster as its time to impact shrinks,
    and a violet ring (the lead indicator's, 1.5 times bigger) on the nearest
    missile, pinned to the screen border like the target box
    (`pin_to_screen_edge`) when off screen.

## `rear_view_mirror.py`

`RearViewMirror` renders a backward-facing camera into an offscreen texture
buffer shown as a small horizontally flipped card at the top of the screen.
Its resolution scales with the `mirror_scale` graphics setting;
`toggle_mirror()` (the `toggle_mirror` binding) deactivates the buffer as well
as hiding the card, so a hidden mirror costs nothing to render.

## `player_waypoints.py`

Backs the mission's `player_waypoints` action (see
[docs/scenario_scripting.md](scenario_scripting.md#actions)):

- **`WaypointMarker`** — a recoloured, semi-transparent sphere posing as a
  minimal pawn for targeting: it registers with `Interactions` (see
  [docs/ai.md](ai.md)) as a neutral (team 0) actor, so bots never target it,
  exposes the attributes the targeting system and HUD read (`id`, `team`,
  `position`, `is_dead`, ...), and has `category = "waypoint"` so the
  player's "Waypoints" target filter (see [docs/actors.md](actors.md)) can
  isolate it while other filters exclude it.
- **`PlayerWaypoints`** — shows only the *next* of an ordered list of
  positions through one reused marker. Each frame `update()` advances once the
  player is within `arrival_radius_m`, and shows the marker only while the
  player's target filter is `"Waypoints"`. After the last waypoint,
  `_finish()` removes the marker.

## `utils.py` — generic UI items

- **`make_text_line`** — a HUD-style line of text (small caps, drop shadow,
  fadable).
- **`ArcGauge`** — a half-ring gauge read by the angle filled, sweeping from
  its left end over the top, with a line of text at its centre. The fill is
  quantised to the ring's segments and only rebuilt when that step changes.
- **`ColumnGauge`** — a vertical bar gauge filling up from its base.
- **`RollingDrum`** — a looping list of text lines written round a cylinder
  seen from the side: the selected item faces the viewer, the previous and
  next ones are above and below, smaller, flattened by the curvature and
  fainter, until they turn out of sight. `update(items, selected, label)`
  rolls it to a new selection, by as many slots as it moved, the shorter way
  round, easing out over `roll_time_s` (on the clock it is given).

## Where things live

Every module above sits directly under
[`src/space_flight/ui/`](../../src/space_flight/ui/); the
[code reference](apidocs/index.rst) has the full per-class API.
