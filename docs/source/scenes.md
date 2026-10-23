# Scenes

`scenes` builds the environment a level flies in: skyboxes, lighting, 2D
planets, asteroid fields, and a whole planetary world. The pieces are
independent and game-agnostic, assembled by a per-level `Scene` subclass.
They live in
[`src/space_flight/scenes/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/scenes/),
except the planetary world (terrain, air, clouds, ocean, sky), which comes
from [WorldBuilder](https://github.com/JoeDalton/WorldBuilder). The per-class
API is in the [code reference](apidocs/index.rst).

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
| `earthlike_planet` | `SceneEarthlike` | WorldBuilder's `World`: planet (terrain, air, clouds, swell ocean), moon, sky, sun and lights | dust, then waits for the world to load |
| `debug` | `SceneDebug` | nothing | test skybox, lighting |

`clean()` tears the owned pieces down. `build_upfront` runs after the player
exists, so a scene's ocean reflection camera can copy the player camera's
lens.

Every frame, once the render origin has moved onto the player,
`FlightState` asks the scene for two things:
- `scene.depth_ranges()`: the split and far distances of its split depth
  cameras (see [docs/game.md](game.md#split-depth)). By default the split is
  at 2 km and the far plane at `CAMERA_FAR_M`.
- `scene.update_after_recenter()`: updates what must follow the origin. It
  is a no-op by default.

## Static environment pieces

- **[`skybox.py`](../../src/space_flight/scenes/skybox.py)**'s `Skybox` loads a
  named `.bam` sphere at a huge scale, applies its cube map at runtime (see
  `datafiles/models/skyboxes/create_skybox.py` for why it is not baked in), and
  draws it unshaded, unlit and without depth write in the "background" bin,
  re-centred on the player every frame. It opts out of any ocean reflection
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

## Planet world — from WorldBuilder

`SceneEarthlike` (Mission 3) is a whole planetary world: the planet (terrain,
air, clouds, swell ocean), its moon, the sky and the sun. WorldBuilder's
`World` builds and updates it (see
[its world page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/world.md)).
The scene only says what it looks like.

**The look** (class attributes and `bodies()`):
- **The planet** comes from `datafiles/worlds/earthlike_demo/`, an unchanged
  copy of WorldBuilder's demo level (`terrain/levels/demo.yaml` and its
  stamps). It has `AtmosphereParams()`, `CLOUDS` (cumulus at 2.2 km, above
  the convoy) and `OCEAN` (the 20 m swell, hazed to the air's colour).
- **The moon** is the demo's airless sand moon, 10,000 km away, in the
  northern sky ahead of the convoy.
- **The sun** is `SUN`, high in the south-east, and **the sky** is `SKY`,
  WorldBuilder's star field.
- **`LIGHT_SCALE`** scales the Panda3D lights `World` puts on render for the
  ships, about 0.4. Ships use fixed-function lighting with no tone map, so the
  world's physical noon sun would clip them to white.

There is no skybox, no `Lighting` and no 2D planet: the sky, the moon and the
lights are the world's.

**How it runs:**
- **Placement.** The planet is not rotated: its centre sits one radius below
  the world origin, so the ground under the origin is the planet's +z pole,
  with sea level at z = 0 there.
  - That is a polar sea with snowy islands and mountains. The demo level's
    hand-made features sit far away, around its reference latitude, and are
    not seen.
  - The surface curves away from z = 0 with distance (about 80 m at 10 km on
    the 600 km planet), while the flight model stays flat.
- **Build.** `build_upfront` builds the `World` on the black screen, about
  5 s. It runs before `FlightState` creates the split cameras, because the
  ocean's reflection copies the main lens.
- **Loading.** `build_decomposed` ends with `wait_until_loaded`, which holds
  the hyperspace tunnel until `world.loading` (ground and clouds) has stayed
  False for half a second, at most a minute: about 11 s on this machine.
  - The game loop is paused then, so each step is a
    `FlightState.follow_render_origin()`, as a frame would do.
  - `FlightState` centres render on the player as soon as the player exists,
    so the world loads around it.
- **Every frame.**
  - `depth_ranges()` is `world.depth_ranges(player position)`: the split
    follows the nearest ground.
  - `update_after_recenter()` is
    `world.update(player position, far=game.depth_far)`.
- **Solid.** `world.enable_collision(CollisionLayers.TERRAIN_INTO,
  bodies=["planet"])` adds an into-only `"terrain"` collision node, owned by
  WorldBuilder's `TerrainSurface`. Ships, munitions and sensors hit it through
  the usual terrain handlers (see [docs/game.md](game.md)), the sea surface
  included.
  - Only drawn chunks within 100 km are solid, at the drawn level of detail,
    which is coarser away from the player.
  - Without the native collision library built for this Panda3D series,
    building the scene raises `NativeCollisionError`.
- **Quality.** Every part is built with the `world` graphics settings.
- **Far plane.** `CAMERA_FAR_M` (in `space_flight/__init__.py`, applied by
  `player.py`) is 600 km. It is set before the scene is built, because the
  ocean's reflection camera copies the lens. Panda's default of 100 km would
  clip the outermost cloud shell.

## Where things live

`Scene` and its subclasses are in `scenes.py`, with the loading gate
`wait_until_loaded`. The static pieces are one file each (`skybox.py`,
`lighting.py`, `planet_2d.py`, `asteroid_field.py`). The planetary world and
its shaders are in WorldBuilder (`world_builder.world` and the parts it
builds).
