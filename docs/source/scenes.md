# Scenes

`scenes` builds the environment a level flies in: the sky and its lights,
asteroid fields, 2D planets, and a whole planetary world. The pieces are
assembled by a per-level `Scene` subclass in
[`src/space_flight/scenes/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/scenes/).
All but the 2D planet come from
[WorldBuilder](https://github.com/JoeDalton/WorldBuilder): its `World` (sky,
sun, lights, and planets with their air, clouds and ocean) and its asteroid
fields. The per-class
API is in the [code reference](apidocs/index.rst).

## Mental model

- A **`Scene`** subclass is a level's environment recipe: it owns the pieces
  below and no gameplay logic. `scene_factory(game, scene_name, keep_outs)`
  picks one by name; `keep_outs` is the room its asteroid field leaves clear
  (a level's spawn points and routes).
- Scenes build in two phases, mirroring `FlightState`'s level entry (see
  [docs/game.md](game.md#levels)). The level's upfront builder calls
  **`build_upfront()`**, which builds the heavy objects synchronously on the
  black screen before the hyperspace animation. `FlightState` then drives the
  **`build_decomposed()`** generator during the animation; it yields a label
  after each cheaper piece (dust, planet, set dressing) so the animation keeps
  rendering, then holds it until WorldBuilder's parts have loaded.
- Every piece follows the codebase's lifecycle contract: constructed with
  `game`, optionally registers a per-frame update in `game.method_lists`,
  exposes `clean()`.
- `Planet2D` "follows the camera to infinity": it re-centres on the player
  every frame, so cheap geometry can stand for something arbitrarily
  distant. This is separate from the floating render origin (see
  [docs/game.md](game.md#the-floating-render-origin)); scene code works in world
  coordinates under `game.root_node`.

## `scenes.py` — the `Scene` catalogue

| Name | Class | `build_upfront` | `build_decomposed` |
|------|-------|-----------------|--------------------|
| `asteroids` | `SceneAsteroids` | open space (`World` with no planet: sky, sun, lights) and Missions 1-2's asteroid field | dust, then waits for the field's rock shapes |
| `lava_planet` | `SceneLavaPlanet` | open space without a sky, lava-toned light, a sparser field | dust, 2D lava planet, then waits for the field |
| `earthlike_planet` | `SceneEarthlike` | WorldBuilder's `World`: planet (terrain, air, clouds, swell ocean), moon, sky, sun and lights | dust, then waits for the world to load |
| `debug` | `SceneDebug` | open space: sky, sun, lights | nothing |

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

Missions also ask it `scene.clear_position(position, radius)` for ships
placed at run time relative to the player: the nearest place with room, the
position itself in a scene without obstacles.

## Open space and asteroid fields — from WorldBuilder

`SceneSpace` is open space: WorldBuilder's `World` with no planet. It draws
the sky (`SKY`: stars, the sun's disc, a violet nebula; None for none), and
puts Panda3D's sun and ambient lights on render for the ships, from `SUN` and
`AMBIENT` (the sky light in open space) scaled by `LIGHT_SCALE` (0.2: the
ships' fixed-function lighting has no tone map). Every frame
`update_after_recenter` is `world.update(player position, far=game.depth_far)`.
`SceneDebug` is just that.

`SceneAsteroids` adds Missions 1 and 2's field: a WorldBuilder
`AsteroidField` (see
[its asteroids page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/asteroids.md)),
`FIELD` describing it.

- **The field.** A 15 km cube around the origin, patchy, its rocks' radii
  from 50 m to 2 km (a power law: many small, few big), a little ice; about
  5,500 rocks. They turn, some tumbling, with the game's clock: a pause
  freezes them.
- **Room.** The level's `keep_outs` (`common.route_keep_outs`: capsules
  along its routes, balls at its spawn points) are empty of rocks. Ships
  spawned relative to the player (Mission 1's formation, Mission 2's
  smuggler and TIEs) go through `scene.clear_position`, the field's
  `find_clear`: the nearest place with room within 3 km.
- **Drawn** by instancing, at levels of detail chosen by their pixel error,
  for the main camera and the rear-view mirror. Its shapes are built in the
  world's worker processes during the hyperspace animation;
  `build_decomposed` holds it until they are in (about 3 s). Lit by the same
  sun and ambient light as the ships, with no tone map either.
- **Solid** through `field.enable_collision(TERRAIN_INTO, name="terrain")`:
  ships, munitions and sensors hit the drawn rocks through the terrain
  handlers. Its owner, WorldBuilder's `AsteroidSurface`, gives the material
  at a hit ("rock", or "snow" for an icy rock) and the speed of the turning
  surface there, which the crash and spark handlers take into account. Rocks
  more than 20 km from the player are not solid.
- **Quality.** The `asteroids` section of the `world` graphics settings.

`SceneLavaPlanet` (the Dev level) is the same with a sparser field, an orange
light from the lava planet's side, no sky, and the 2D lava planet.

[`planet_2d.py`](../../src/space_flight/scenes/planet_2d.py)'s `Planet2D` is
a single textured card (not a sphere, and not camera-facing), placed far away
and scaled up, which `move_planet_task` keeps at a fixed offset from the
player. Its distance is arbitrary, so it draws in the "background" bin with
no depth write; the default "transparent" bin (sort 30) would paint it over
the clouds (sort 25).

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

There is no 2D planet: the sky, the moon and the lights are the world's.

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
`wait_until_loaded` (which sleeps a few milliseconds per step while loading,
so the worker processes' results get through a loading loop run flat out, as
a headless build runs it). `planet_2d.py` is the 2D planet. The world, the
asteroid fields and their shaders are in WorldBuilder (`world_builder.world`,
`world_builder.asteroids`).
