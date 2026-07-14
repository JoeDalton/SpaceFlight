# Global architecture

`global_architecture` is the application shell: the root Panda3D app, its
stack-based state machine, and the app-lifetime services (assets, graphics
settings) that outlive any single game session — as opposed to
[`game/`](game.md), which is scoped to one `FlightState` session. This page
is the guided tour; the per-class API is generated from the docstrings in the
[code reference](docs/).

All of it lives in
[`src/space_flight/global_architecture/`](../src/space_flight/global_architecture/).

## Mental model

- **`SpaceFlightSimulator`** is the single root `ShowBase` instance — the
  actual Panda3D application. It constructs every app-lifetime subsystem once
  and pushes the first state.
- **`StateManager`** runs a stack of `BaseState`s (splash, menus, loading,
  flight, pause...). Only the top of the stack is fully active; the app
  navigates by pushing and popping, not by direct transitions.
- **`AssetManager`** and its pools cache expensive-to-load resources
  (models, textures, sounds) once, app-wide, so any level can request the
  same asset by path and get the already-loaded instance.
- **`GraphicsManager`** and **`GraphicsSettings`** together own everything
  about *how* the scene is rendered (window mode, render scale,
  anti-aliasing) versus `game/`'s ownership of *what* is rendered.

## `simulator.py` — the app root and its state machine

[`simulator.py`](../src/space_flight/global_architecture/simulator.py) has
two classes:

- **`StateManager`** is a stack-based state machine: `push()` instantiates
  and enters a new state (pausing the current top first, unless the new
  state declares `PAUSES_BELOW = False` — used by overlays like the
  hyperspace loading screen that must let the state underneath keep running,
  see [docs/game.md](game.md)); `pop()` exits and discards the top, resuming
  whatever is now on top; `replace()` is pop-then-push at the same depth;
  `clear()` collapses the stack down to just the current top, exiting
  everything below it (used when returning to the main menu from deep in a
  level). Every concrete state class the app can enter is declared as a
  class attribute here (`GAME_STATE`, `LOADING_STATE`,
  `HYPERSPACE_LOADING_STATE`, the various menu states, ...), so any module
  can reference `StateManager.GAME_STATE` without importing that state
  module directly — avoiding import cycles between states that push each
  other.
- **`SpaceFlightSimulator`** subclasses `ShowBase` and is the literal
  application: its `__init__` builds every app-lifetime subsystem in order
  — `GraphicsSettings` → `GraphicsManager` → `StateManager` →
  `InputContextStack`/input reader (see
  [`ui/input_context.py`](../src/space_flight/ui/)) → `AssetManager` →
  `MenuModels` → `SFX` (see [docs/fx.md](fx.md)) — then pushes `SplashState`
  to begin the app. `input_task`, registered at a high sort priority (`-100`,
  before other tasks), polls the input reader and dispatches through the
  context stack every frame regardless of which state is active.

A module-level `loadPrcFileData` call disables Panda3D's on-disk shader
cache; the comment above it explains why — enabling it also routes glTF
loading through `panda3d-gltf`, whose tangent calculation crashes on a
non-triangle primitive in one of the ship cockpit models, and the cache was
never the actual loading bottleneck.

## `base_state.py` — the state contract

[`base_state.py`](../src/space_flight/global_architecture/base_state.py)'s
`BaseState` is the interface every pushable state implements: `enter()`
(build UI, start tasks) and `exit()` (tear them down) are abstract;
`pause()`/`resume()` default to no-ops for states that don't need to react to
being covered/uncovered. `PAUSES_BELOW` (default `True`) controls whether
pushing this state freezes the state beneath it — flipped to `False` only for
overlays that must let the state below keep ticking (the hyperspace loading
screen builds the level underneath itself; see
[docs/game.md](game.md)). `force_render()` forces two synchronous frame
renders, called at the end of a state's `exit()` so the outgoing scene
doesn't visibly hang on screen while the next state's heavy assets start
loading.

## `asset_manager.py` and `asset_pools.py` — caching by path

[`asset_manager.py`](../src/space_flight/global_architecture/asset_manager.py)'s
`AssetManager` is a single app-wide `path -> loaded asset` cache:
`get_asset()` returns the already-loaded asset for a path or loads-and-caches
it on first request, so every caller (levels, actors, UI) that references the
same file gets one shared instance rather than reloading it. `COMMON_ASSETS_TO_LOAD`
is the fixed list of assets always worth preloading at boot regardless of
level (ship models, common sounds, dust/explosion textures — see the
inline comments on *why* specific heavy assets like capital ship glTFs and
the cloud atlas are preloaded, to avoid mid-level load stalls);
`load_game_assets`/`load_assets_task` drain that list one asset per frame
during the splash screen, updating a progress bar as they go.
`instantiate_3d_model_to_node` is the usual way actors attach a model: it
resolves the (cached) model asset and creates a Panda3D *instance* of it
under the caller's node, rather than a full copy.

[`asset_pools.py`](../src/space_flight/global_architecture/asset_pools.py)
implements the two non-model asset kinds `AssetManager` delegates to:
- **`TexturePool`** loads either a single texture file or every file
  matching a glob pattern in a directory, and `get_texture()` returns a
  random one from the pool — used for texture *variety* (e.g. picking among
  several dust sprite colours) rather than pure caching.
- **`SoundPool`** pre-loads a fixed-size pool of sound instances (200 by
  default, `SOUND_POOL_LENGTH`) so multiple copies of the same sound can play
  overlapping without one cutting the other off. `get_sound()` hands back an
  instance not currently `in_use` (optionally randomising its pitch for
  variety) and raises if the whole pool is busy; `release_sound()` stops
  playback and frees the slot. Distinguishes 3D (positional,
  `Audio3DManager`-loaded) from plain sounds via `is_3d`. This is the same
  pooling model `fx/sfx.py`'s `SFX` builds its own lower-level pools on top
  of (see [docs/fx.md](fx.md)) — `AssetManager` is the app-wide cache,
  `SFX`'s per-category pools are the gameplay-facing API.

## `graphics_manager.py` and `graphics_settings.py` — how the scene renders

These two modules split responsibility the same way `AssetManager` and
`asset_pools.py` do: settings own *what the sanitised configuration says*,
the manager owns *making the engine reflect it*.

[`graphics_settings.py`](../src/space_flight/global_architecture/graphics_settings.py)'s
`GraphicsSettings` loads `configuration/graphics.yaml` layered over a
read-only `configuration/default_graphics.yaml` (`_deep_merge`, the same
pattern used for [input bindings](../src/space_flight/menus/) — see that
module's docs), then `sanitise()`s the merged result so every field is
clamped to something the renderer can safely act on (valid display mode,
minimum window size, render scale in `[0.25, 1.0]`, valid MSAA sample counts,
etc.) — a malformed or hand-edited config file degrades to defaults rather
than crashing the renderer. `save()` re-sanitises and persists to the user
file; `reset_to_default()` reloads just the defaults without touching it.

[`graphics_manager.py`](../src/space_flight/global_architecture/graphics_manager.py)'s
`GraphicsManager` applies that sanitised config to the live engine, split
into two independent concerns (detailed in the module's own docstring):

- **Window mode** — `open_game_window()` closes the splash window and opens
  the real one honouring the saved fullscreen/windowed size (called once,
  from `SplashState.exit`); `apply_window_settings()` re-applies display
  settings to the *already-open* window at runtime (used by the graphics
  settings menu on save) without needing a restart.
- **Render-scale / anti-aliasing pipeline** — `begin_scene_render()` (called
  once per level load from `FlightState.enter`, see
  [docs/game.md](game.md)) is a no-op when scale is 1.0 and no AA is
  requested (straight-to-window rendering); otherwise it builds a
  `FilterManager` pipeline that renders the 3D scene into an offscreen
  buffer sized `window * scale` (with MSAA if requested) and composites it
  back to the window through a fullscreen quad shader (plain blit, or FXAA).
  Critically, only the 3D scene is routed through this buffer — 2D layers
  (HUD, menus) stay at native window resolution, so lowering render scale
  for performance never blurs UI text. `_update_pipeline_uniforms` keeps a
  power-of-two texture-padding correction in sync every frame, since the
  GSG may pad the offscreen target and the correct scale factor is only
  known after the first render. `get_render_size()` lets other
  resolution-dependent buffers (e.g. the ocean reflection) size themselves
  off the *internal* render resolution rather than the window size.
  `end_scene_render()` tears the whole pipeline down and is always called
  first inside `begin_scene_render()`, making rebuilding idempotent.

## Where things live

Everything in this page lives directly under
[`src/space_flight/global_architecture/`](../src/space_flight/global_architecture/):
the app root and state stack in `simulator.py`, the state contract in
`base_state.py`, asset caching in `asset_manager.py`/`asset_pools.py`, and
display/render settings in `graphics_manager.py`/`graphics_settings.py`. The
auto-generated [code reference](docs/) has the full per-class API.
