# Global architecture

`global_architecture` is the application shell: the root Panda3D app, its
stack-based state machine, and the app-lifetime services (assets, graphics
and gameplay settings) that outlive any single game session — as opposed to
[`game/`](game.md), which is scoped to one `FlightState` session. Everything
here lives in
[`src/space_flight/global_architecture/`](../../src/space_flight/global_architecture/);
the per-class API is in the [code reference](apidocs/index.rst).

## Mental model

- **`SpaceFlightSimulator`** is the single root `ShowBase`: it builds every
  app-lifetime subsystem once and pushes the first state.
- **`StateManager`** runs a stack of `BaseState`s (splash, menus, loading,
  flight, pause...). Only the top is fully active; the app navigates by
  pushing and popping, not by direct transitions.
- **`AssetManager`** caches expensive resources (models, textures, sounds)
  app-wide by path.
- **`GraphicsSettings`** / **`GraphicsManager`** own *how* the scene is
  rendered (window mode, render scale, anti-aliasing); `game/` owns *what* is
  rendered.
- **`GameplaySettings`** owns the difficulty: a preset, or custom values for
  auto-aim, shot deviation and damage, read when a level is built.

## `simulator.py` — the app root and its state machine

[`simulator.py`](../../src/space_flight/global_architecture/simulator.py) has
two classes:

- **`StateManager`**: `push()` instantiates and enters a state, pausing the
  current top first unless the new state declares `PAUSES_BELOW = False`;
  `pop()` exits the top and resumes the new top; `replace()` is pop-then-push;
  `clear()` exits everything below the top and keeps only the top (used to
  return to the main menu from deep in a level). Every concrete state class is
  a class attribute (`GAME_STATE`, `HYPERSPACE_LOADING_STATE`, the menu
  states...), so modules reference `StateManager.GAME_STATE` instead of
  importing state modules that push each other — avoiding import cycles.
- **`SpaceFlightSimulator`** builds, in order, `GraphicsSettings` →
  `GameplaySettings` → `GraphicsManager` → `StateManager` → `InputContextStack` and input reader
  (see [`ui/input_context.py`](../../src/space_flight/ui/input_context.py)) →
  `AssetManager` → `MenuModels` → `SFX` (see [docs/fx.md](fx.md)), then pushes
  `SplashState`. `input_task` (task sort `-100`, before other tasks) polls the
  reader and dispatches through the context stack every frame, whatever state
  is active. With `headless=True` there is no input reader, no `input_task`
  and no splash: the stack stays empty for
  [`headless/harness.py`](../../src/space_flight/headless/harness.py) to push
  a headless `FlightState` itself.

Two module-level `loadPrcFileData` calls configure Panda3D: one silences
ffmpeg (`notify-level-ffmpeg error`), the other disables the on-disk model
cache (`model-cache-dir`), and with it the compiled-shader cache, because it
was implicated in glTF models failing to load on some systems.

## `base_state.py` — the state contract

[`base_state.py`](../../src/space_flight/global_architecture/base_state.py)'s
`BaseState`: `enter()` (build UI, start tasks) and `exit()` (tear them down)
are abstract; `pause()`/`resume()` default to no-ops. `PAUSES_BELOW` (default
`True`) is `False` only for overlays that must let the state below keep
ticking: the hyperspace loading screen, which builds the level underneath it
(see [docs/game.md](game.md)), and the radial target-filter menu (see
[docs/menus.md](menus.md)). `force_render()` renders two frames synchronously;
most states call it at the end of `exit()` so the outgoing scene doesn't hang
on screen while the next state's heavy assets load.

## `asset_manager.py` and `asset_pools.py` — caching by path

[`asset_manager.py`](../../src/space_flight/global_architecture/asset_manager.py)'s
`AssetManager.get_asset()` returns the cached asset for a path, loading it on
first request, so every caller shares one instance. `COMMON_ASSETS_TO_LOAD`
is preloaded at boot whatever the level (its inline comments say why some
heavy assets, like capital ship glTFs, their turret and the cloud atlas, are
on it: to avoid mid-level load stalls); `load_game_assets`/`load_assets_task` load it one
asset per frame during the splash screen, updating its progress bar.
`instantiate_3d_model_to_node` is how actors attach a model: it attaches a
Panda3D *instance* of the cached model under the caller's node, not a copy.

[`asset_pools.py`](../../src/space_flight/global_architecture/asset_pools.py)
holds the non-model asset kinds:

- **`TexturePool`** loads one texture file, or every file matching a glob in a
  directory; `get_texture()` returns a random one (all current callers pass a
  single file).
- **`SoundPool`** preloads `SOUND_POOL_LENGTH` (1000) instances of a sound —
  or, for a directory, random picks among the matching files — so copies can
  overlap without cutting each other off. `get_sound()` hands out an instance
  not `in_use` (optionally with a randomised pitch) and raises if the whole
  pool is busy; `release_sound()` stops it and frees the slot. `is_3d` picks
  positional (`Audio3DManager`) or plain loading. `SFX` (see
  [docs/fx.md](fx.md)) fetches its per-category pools through `AssetManager`
  and is the gameplay-facing sound API.

## `graphics_settings.py` and `graphics_manager.py` — how the scene renders

The settings own *what the sanitised configuration says*; the manager owns
*making the engine reflect it*.

[`graphics_settings.py`](../../src/space_flight/global_architecture/graphics_settings.py)'s
`GraphicsSettings` loads `configuration/graphics.yaml` layered over the
read-only `datafiles/default_configuration/default_graphics.yaml`
(`_deep_merge`). The [input bindings](ui.md) are not layered: `load_bindings`
reads `configuration/bindings.yaml` alone, and
`datafiles/default_configuration/default_bindings.yaml` is only read by the
input settings menu's reset-to-defaults. `sanitise()` then clamps every field to something the renderer can act on (valid display mode,
minimum window size, render scale in `[0.25, 1.0]`, valid MSAA sample count,
known cloud-quality name, ...), so a malformed or hand-edited file degrades to
defaults instead of crashing. `save()` re-sanitises and writes the user file;
`reset_to_default()` reloads the defaults without writing it.

Not every setting goes through `GraphicsManager`: the setting belongs to the
thing that acts on it. `CloudField` reads `clouds.quality` when it builds, and
the ocean reads `render.reflection_scale`. The four quality names must match
`CloudQuality` in
[`scenes/cloud/cloud.py`](../../src/space_flight/scenes/cloud/cloud.py): a name
the sanitiser accepts but the enum doesn't know would fall back to `high` at
build time. A test asserts the two lists agree.

[`graphics_manager.py`](../../src/space_flight/global_architecture/graphics_manager.py)'s
`GraphicsManager` applies the sanitised config to the live engine:

- **Window mode** — `open_game_window()` closes the splash window and opens
  the real one with the saved fullscreen/windowed size (once, from
  `SplashState.exit`); `apply_window_settings()` re-applies them to the open
  window at runtime (graphics settings menu, on save).
- **Render scale / anti-aliasing** — `begin_scene_render()` (once per level
  load, from `FlightState.enter`) is a no-op at scale 1.0 with no AA.
  Otherwise it builds a `FilterManager` pipeline that renders the 3D scene
  into an offscreen buffer of `window * scale` pixels (with MSAA if
  requested) and composites it to the window through a fullscreen quad
  shader (plain blit, or FXAA). Only the 3D scene goes through the buffer:
  2D layers (HUD, menus) stay at native resolution, so lowering render scale
  never blurs UI text. Changes therefore apply on the next level load.
  `_update_pipeline_uniforms` refreshes a power-of-two padding correction
  every frame, since the GSG may pad the offscreen texture and the real
  scale is only known after the first render. `get_render_size()` lets
  other resolution-dependent buffers (e.g. the ocean reflection) size off
  the internal render resolution rather than the window. `end_scene_render()`
  tears the pipeline down; `begin_scene_render()` calls it first, so
  rebuilding is idempotent.

## `gameplay_settings.py` — difficulty

[`gameplay_settings.py`](../../src/space_flight/global_architecture/gameplay_settings.py)'s
`GameplaySettings` holds the difficulty, as `app.gameplay_settings`. Two files
make it up:

- **`datafiles/default_configuration/gameplay_presets.yaml`** (read-only) holds the presets —
  easy, normal, hard, ace, in the order the menu lists them — each setting
  every value. `normal` reproduces the untuned game, and is the only source
  of defaults: the fallback for anything missing or invalid. `load_presets()`
  reads them (exposed as `GameplaySettings.presets`) and raises if one lacks
  a value or has an invalid one: the file is read-only, so there is nothing
  to fall back on.
- **`configuration/gameplay.yaml`** (the user file) holds `preset: <name>`
  only, or `preset: custom` followed by its own values. A named preset always
  takes its values from the presets file, so re-tuning a preset reaches every
  player who picked it; custom values missing from the file come from
  `normal`.

`resolve()` turns either form into the full settings, `config`: the preset's
name under `preset`, and its values. `save()` writes only the name, unless
custom. `sanitise(config, fallback)` clamps each numeric value to its
`(minimum, maximum)` in the `LIMITS` table (e.g. the assist angle stays above
0, as auto-aim divides by its tangent), coerces the `FLAGS` to booleans, and
takes the fallback's value for any missing or wrong-typed one; `resolve()`
passes the `normal` preset. The gameplay settings menu's sliders span the same
`LIMITS` (see [docs/menus.md](menus.md#settings-screens)).

Each side — the player, and the bots (fighters, turrets, capital ships) — has:

| Setting | Read by | Effect |
|---------|---------|--------|
| `auto_aim.enabled`, `lock_delay_s`, `lock_angle_deg`, `assist_angle_deg` | `Fighter`, `Turret` → `AutoAim` (see [docs/ai.md](ai.md#autoaim)) | whether and how shots lead a locked target |
| `deviation_deg` | `Fighter`, `Turret` → `LaserCannon` (see [docs/actors.md](actors.md#weapons-and-munitions)) | half-angle of the random cone around each laser shot |
| `damage_multiplier` | `Fighter`, `Turret` → their weapons | scales the damage of their bolts and ordnance |

plus, for the player only, `collision_damage_multiplier` (read by
`CollisionSystem`, see [docs/game.md](game.md)) and `lead_indicator` (read by
`AimHUD`, see [docs/ui.md](ui.md)).

Game code reads the settings through `gameplay_config(game)` (or
`auto_aim_params(game, side)`, the auto-aim ones as `AutoAim.configure`
arguments), which falls back to the `normal` preset when the app has no
settings (test doubles, light headless stubs). They are read once, when the
level's ships, HUD and collision system are built: changes made in the menus —
even from the pause menu — apply from the next mission.
