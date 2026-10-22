# Scenes

`scenes` builds the environment a level flies in — skybox, lighting, planets,
asteroid fields, ocean and volumetric clouds — as independent, game-agnostic
pieces assembled by a per-level `Scene` subclass. It all lives in
[`src/space_flight/scenes/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/scenes/),
except the ocean surface, the clouds and the planet terrain, which come from
[WorldBuilder](https://github.com/JoeDalton/WorldBuilder); the per-class API
is in the [code reference](apidocs/index.rst).

## Mental model

- A **`Scene`** subclass is a level's environment recipe: it owns the pieces
  below and no gameplay logic. `scene_factory(game, scene_name)` picks one by
  name.
- Scenes build in two phases, mirroring `FlightState`'s level entry (see
  [docs/game.md](game.md#levels)). The level's upfront builder calls
  **`build_upfront()`**, which builds the heavy objects synchronously on the
  black screen before the hyperspace animation. `FlightState` then drives the
  **`build_decomposed()`** generator during the animation; it yields a label
  after each cheaper piece (skybox, lighting, planet, dust, set dressing) so the
  animation keeps rendering.
- Every piece follows the codebase's lifecycle contract: constructed with
  `game`, optionally registers a per-frame update in `game.method_lists`,
  exposes `clean()`.
- `Skybox` and `Planet2D` "follow the camera to infinity": they re-centre on the
  player every frame, so cheap geometry can stand for something arbitrarily
  distant. This is separate from the floating render origin (see
  [docs/game.md](game.md#the-floating-render-origin)); scene code works in world
  coordinates under `game.root_node`.

## `scenes.py` — the `Scene` catalogue

| Name | Class | `build_upfront` | `build_decomposed` |
|------|-------|-----------------|--------------------|
| `asteroids` | `SceneAsteroids` | three asteroid fields (one static, two rotating) | purple skybox, lighting, dust |
| `lava_planet` | `SceneLavaPlanet` | three asteroid fields | lava-toned lighting, dust, 2D lava planet, Imperial Star Destroyer (no skybox) |
| `ocean_planet` | `SceneOcean` | `Ocean` (geometric swell on), `Clouds` | dusk skybox, 2D terran planet, lighting, dust |
| `earthlike_planet` | `SceneEarthlike` | `PlanetSurface` (terrain and sea) | dusk skybox, lighting, dust, then waits for the ground to load |
| `debug` | `SceneDebug` | nothing | test skybox, lighting |

`clean()` tears the owned pieces down. Only `SceneOcean.build_upfront` also
forces the one-time GPU prep (`prepare_scene(gsg)`: shader compile, vertex
upload) while the screen is black, and it must run after the player exists:
the ocean's reflection camera copies the player camera's lens. `SceneOcean`
passes one `HAZE_COLOR` to both the ocean and the clouds so they meet at the
horizon.

A scene can also update things each frame after the render origin has moved
onto the player: `FlightState` calls `scene.update_after_recenter()` right
after `recenter_render_origin()` (a no-op by default).

## Static environment pieces

- **[`skybox.py`](../../src/space_flight/scenes/skybox.py)**'s `Skybox` loads a
  named `.bam` sphere at a huge scale, applies its cube map at runtime (see
  `datafiles/models/skyboxes/create_skybox.py` for why it is not baked in), and
  draws it unshaded, unlit and without depth write in the "background" bin,
  re-centred on the player every frame. It opts out of the ocean reflection
  camera's clip plane (`setClipPlaneOff(1)`); the comment there explains the
  horizon band that appears otherwise.
- **[`lighting.py`](../../src/space_flight/scenes/lighting.py)**'s `Lighting` is
  a directional + ambient light pair under `game.root_node`, enabled on
  `render`; `directional_direction` points from the scene toward the sun. No
  per-frame behaviour.
- **[`planet_2d.py`](../../src/space_flight/scenes/planet_2d.py)**'s `Planet2D`
  is a single textured card (not a sphere, and not camera-facing), placed far
  away and scaled up, which `move_planet_task` keeps at a fixed offset from the
  player. Its distance is arbitrary, so it draws in the "background" bin with no
  depth write; the default "transparent" bin (sort 30) would paint it over the
  clouds (sort 25).
- **[`asteroid_field.py`](../../src/space_flight/scenes/asteroid_field.py)**'s
  `AsteroidField` scatters `n_asteroids` model instances in a cube of side
  `field_size`, each with a random scale and a terrain collision sphere. With
  `is_moving=True` each also gets a fixed random spin, integrated by the shared
  physics `Integrator` (see [docs/game.md](game.md)) as one flat state vector of
  `4 * n_asteroids` quaternion components rather than per-asteroid objects.
  Scenes layer several fields: a dense static backdrop plus a few large,
  slowly tumbling rocks.

## Ocean and clouds — from WorldBuilder

The ocean surface and the volumetric clouds live in the separate
[WorldBuilder](https://github.com/JoeDalton/WorldBuilder) project, installed
as the `world_builder` dependency (see
[its ocean page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/ocean.md) and [its clouds page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/clouds.md)
for how they work). The game adds only what is game-specific:

- **[`ocean.py`](../../src/space_flight/scenes/ocean.py)**'s `Ocean` subclasses
  `world_builder.ocean.Ocean` to register a flat terrain collision plane at
  Z=0 (see [docs/game.md](game.md)), so ships can crash into the water, and to
  give lasers the `"water"` material for their sparks.
- **`Clouds`** (`world_builder.clouds.Clouds`) is used as is. Its sprite atlas
  goes through the game's `asset_manager`, which preloads it.
- **Quality.** The ocean and clouds are built with their sections of the
  `world` graphics settings (see
  [docs/global_architecture.md](global_architecture.md)).
- **Far plane.** `CAMERA_FAR_M` in `player.py` raises it to 600 km, set before
  the scene is built because the ocean's reflection camera copies the lens:
  Panda's default 100 km clips the outermost cloud shell and keeps the ocean
  horizon in view only up to 785 m of altitude.

## Planet terrain — from WorldBuilder

**[`planet_surface.py`](../../src/space_flight/scenes/planet_surface.py)**'s
`PlanetSurface` builds WorldBuilder's spherical `Terrain` from a WorldBuilder
level file (planet preset, stamps, paints). `SceneEarthlike` uses
`datafiles/worlds/earthlike_demo/`, an unchanged copy of WorldBuilder's demo
level (`terrain/levels/demo.yaml` and its stamps).

- **Placement.** The planet is not rotated: its centre sits one radius below
  the world origin, so the ground under the origin is the planet's +z pole,
  with sea level at z = 0 there. The demo level's hand-made features sit far
  away, around its reference latitude, and are not seen. The surface curves
  away from z = 0 with distance (about 80 m at 10 km on the 600 km planet);
  the flight model stays flat.
- **Render origin.** The terrain hangs under `render`, not `root_node`, and
  rebases itself in float64: `update_after_recenter` passes it the player's
  world position each frame, after `recenter_render_origin`.
- **Loading.** The ground takes about 10 s to load. `build_decomposed` ends
  with `PlanetSurface.wait_until_loaded`, which keeps the hyperspace tunnel
  open until `Terrain.loading` has stayed False for half a second, at most a
  minute. The game loop is paused then, so the generator drives the terrain.
- **Sea.** There is no swell ocean: the terrain draws the sea itself
  (`set_sea_surface(True)`).
- **Solid.** `enable_collision(CollisionLayers.TERRAIN_INTO)` adds an
  into-only `"terrain"` collision node, owned by WorldBuilder's
  `TerrainSurface`, so ships, munitions and sensors hit it through the usual
  terrain handlers (see [docs/game.md](game.md)), the sea surface included.
  Only drawn chunks within 100 km are solid, at the drawn level of detail:
  coarser away from the player. Without the native collision library built
  for this Panda3D series, building the scene raises `NativeCollisionError`.
- **Quality.** The terrain is built with the `terrain` section of the `world`
  graphics settings.

## Where things live

`Scene` and its subclasses are in `scenes.py`; the static pieces are one file
each (`skybox.py`, `lighting.py`, `planet_2d.py`, `asteroid_field.py`); the
game's ocean subclass is `ocean.py`. The ocean surface, the cloud system and
their shaders are in WorldBuilder (`world_builder.ocean`,
`world_builder.clouds`).
