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
  coordinates, converted at the scene graph (`game.render_origin`) for nodes
  under `game.root_node`.

## `scenes.py` — the `Scene` catalogue

| Name | Class | `build_upfront` | `build_decomposed` |
|------|-------|-----------------|--------------------|
| `asteroids` | `SceneAsteroids` | `space/asteroids.yaml`: open space (sky, sun, lights) and Missions 1-2's asteroid field | dust, then waits for the field's rock shapes |
| `lava_planet` | `SceneLavaPlanet` | `space/lava.yaml`: open space without a sky, lava-toned light, a sparser field | dust, 2D lava planet, then waits for the field |
| `solar_system` | `SceneSolarSystem` | `solar_system/solar_system.yaml`: home planet (terrain, air, clouds, sea), moon, ice planet and ring, sky, sun and lights | dust, then waits for the world to load |
| `debug` | `SceneDebug` | `space/empty.yaml`: open space, sky, sun, lights | nothing |

Every scene is a `SceneWorld`: its world is a WorldBuilder world file in
`datafiles/worlds/`, loaded whole by `load_world` in `build_upfront` (see
[the planet world](#planet-world--from-worldbuilder) for how), and `clean()`
tears it down. The files define the objects and nothing about running them;
the scene gives the quality, the game's clock and `LIGHT_SCALE`. Headless (no
window), `load_world` builds the world without its depth camera and seas.

Every frame, once the render origin has moved onto the player,
`FlightState` calls `scene.update_after_recenter()`: it updates what must
follow the origin (the world and the scene's depth camera, see
[docs/game.md](game.md#depth)). It is a no-op by default.

A scene owns its depth camera (`scene.depth`, the world's own, None until
`build_upfront`), and `scene.release_depth()` removes it:
`FlightState.exit` calls it before the render pipeline goes.

Missions also ask it `scene.clear_position(position, radius)` for ships
placed at run time relative to the player: the nearest place with room, the
position itself in a scene without obstacles.

Two more services every scene gives, through its WorldBuilder `World` when it
has one:
- **"Up"**: `scene.up_at(position)` is what the bots level their wings to
  (see [ai.md](ai.md)). It points against the gravity of the world's bodies,
  or is `default_up_direction` (world +Z) where there is none or it is
  negligible (`MIN_GRAVITY_NORM`). It is reckoned at the player's position at
  most every `UP_REFRESH_S` (1 s) and given for every position meanwhile: the
  ships stay a few kilometres from the player, and over that distance a
  planet's up turns by a fraction of a degree.
- **Lighting and shadows of models**: `scene.track_model(node)` hands a node to
  `World.track_light`, which lights it by the light where it is (not at the
  camera) and makes it cast shadows (`MODELS_CAST_SHADOWS`). With
  `MODELS_USE_WORLD_SHADER` (on by default) it is also drawn by WorldBuilder's
  model shader, so it receives the world's shadows (clouds, mountains, the
  other ships). `AnchoredModel.anchor_model` calls it for every model it
  anchors (ships, turrets, any prop), with the node it anchors to: a
  hierarchy is tracked once, and a node under a tracked one follows it. Without
  a world it does nothing. The light at the tracked nodes is reckoned every
  `LIGHT_PERIOD_FRAMES` (3) frames (`World.light_period`), and at once when the
  sun moves or a node is tracked.

## Open space and asteroid fields — from WorldBuilder

`SceneSpace` is open space, `space/empty.yaml`: no body, the sky (stars, the
sun's disc, a violet nebula), the sun and a strong blue sky light away from
every body. `LIGHT_SCALE` (0.2) scales the Panda3D lights the world puts on
render for the ships. `SceneDebug` is just that. Every frame
`update_after_recenter` is `game_world.update(player position)`.

`SceneAsteroids` (`space/asteroids.yaml`) adds Missions 1 and 2's field, a
WorldBuilder `AsteroidField` (see
[its asteroids page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/asteroids.md)),
the world's field `FIELD` (`"field"`, `space/asteroid_field.yaml`).
`SceneLavaPlanet` (`space/lava.yaml`) is the Dev level's: a sparser field
(`sparse_field.yaml`), orange light and no sky, over a 2D planet backdrop.

- **The field.** A 15 km cube around the origin, patchy, its rocks' radii
  from 50 m to 2 km (a power law: many small, few big), a little ice; about
  5,500 rocks. They turn, some tumbling, with the game's clock: a pause
  freezes them.
- **Room.** The level's `keep_outs` (`common.route_keep_outs`: capsules
  along its routes, balls at its spawn points) are empty of rocks.
  The scene passes them to `load_world(keep_outs={field: [...]})`, which adds
  them to the field's own. Ships
  spawned relative to the player (Mission 1's formation, Mission 2's
  smuggler and TIEs) go through `scene.clear_position`, the field's
  `find_clear`: the nearest place with room within 3 km.
- **Drawn** by instancing, at levels of detail chosen by their pixel error,
  for the main camera and the rear-view mirror (the mirror's camera is in
  `GameWorld.views` while it is shown: one field update). Its shapes are built in the
  world's worker processes during the hyperspace animation;
  `build_decomposed` holds it until they are in (about 3 s). Lit by the
  world's sun and sky light, tone mapped like the ships.
- **Solid** through `field.enable_collision(TERRAIN_INTO, name="terrain")`
  (the world's field, `world.field(FIELD)`):
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

`SceneSolarSystem` (Mission 3 and Free Flight) is a whole planetary world
loaded from a file by WorldBuilder's `load_world` (see
[its world file page](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/world_file.md)):
the home planet (terrain, air, clouds, sea), its moon, an ice planet and its
ring, the sky and the sun.

**The world file** is `datafiles/worlds/solar_system/solar_system.yaml`, a
copy of WorldBuilder's shipped world with the body files it links
(`kerbin.yaml`, `moon.yaml`, `ice.yaml`, `ring.yaml`, `sky.yaml`) and the
`stamps/` images the home planet places: a coast with the sea to the north,
a range to the south, a crater, a mesa, a landing pad and a lake near the
start. It defines the objects and nothing about running them; to change what
the world looks like or where things are, edit the file.

**What the scene decides** (class attributes): `WORLD_PATH`, `PLANET` (the
body levels fly over), `LIGHT_SCALE` (about 0.4: it scales the Panda3D lights
the world puts on render for the ships, which use fixed-function lighting
with no tone map, so the world's physical noon sun would clip them to white)
and `TERRAIN_COLLISION_RANGE_M`. There is no 2D planet: the sky, the moon and
the lights are the world's.

**How it runs:**
- **Placement.** WorldBuilder never rotates a planet, so the chart's
  reference point is not at the planet's +z pole.
  `SceneSolarSystem.level_frame()` (a
  [`LevelFrame`](../../src/space_flight/scenes/level_frame.py), made once from
  the planet's body in the file) converts chart coordinates around the
  planet's centre, wherever the file puts it.
  - There, the chart's east, north and up are not the world's x, y and z.
    `default_up_direction` is the frame's up, and the bots take "up" from
    gravity (see above).
  - Levels write their positions on the chart (x metres east, y metres north
    of the reference point, z metres above sea level), and
    `LevelFrame.position(x, y, z)` turns them into world positions, on the
    sphere. `LevelFrame.orientation(position, toward)` gives a level
    orientation facing a point.
  - Mission 3 and Free Flight start at (0, -4000, 1300) on the chart: 900 m
    over the coastal plain, facing north to the coast. Mission 3's waves,
    routes and formations are written on the chart too
    (`WaveSpec.formation_frame` turns the formation's slots to the level's
    axes).
- **Build.** `build_upfront` calls `load_world(app, WORLD_PATH, settings=...,
  clock=..., light_scale=..., light_period=...)` on the black screen, about
  5 s. It builds the world and its depth camera (`GameWorld.depth`,
  `scene.depth`), after the player (whose camera the ocean's reflection
  copies) and the render-scale pipeline (into whose buffer the camera
  presents the view), and gives the camera's depth mode to the rear-view
  mirror. `scene.world` is the loaded `World`, which the scene's queries read.
- **Loading.** `build_decomposed` ends with `wait_until_loaded`, which holds
  the hyperspace tunnel until `world.loading` (ground and clouds) has stayed
  False for half a second, at most a minute: about 11 s on this machine.
  - The game loop is paused then, so each step is a
    `FlightState.follow_render_origin()`, as a frame would do.
  - `FlightState` centres render on the player as soon as the player exists,
    so the world loads around it.
- **Every frame.** `update_after_recenter()` is
  `game_world.update(player position)`: the depth camera takes the world's
  far distance and the height over the nearest ground, and the world is
  drawn around the player.
- **Solid.** `world.enable_collision(CollisionLayers.TERRAIN_INTO,
  max_distance=TERRAIN_COLLISION_RANGE_M)` adds an into-only `"terrain"`
  collision node to every body, owned by WorldBuilder's `TerrainSurface`.
  Ships, munitions and sensors hit it through the usual terrain handlers
  (see [docs/game.md](game.md)), the sea surface included.
  - Only drawn chunks within `TERRAIN_COLLISION_RANGE_M` (10 km) of the
    player are solid, at the drawn level of detail, which is coarser away
    from the player. Every chunk within that range is checked each frame, and
    the fights stay a few kilometres from the player.
  - Without the native collision library built for this Panda3D series,
    building the scene raises `NativeCollisionError`.
- **Quality.** Every part is built with the `world` graphics settings.
- **Shadows.** Every ship is tracked with `World.track_light(node,
  cast=True, shader=True)` (see `Scene.track_model`): it is drawn by the
  world's model shader, so it is shadowed per pixel by the mountains, the
  clouds and the other bodies' eclipses, and it casts shadows on the terrain,
  the sea and the other ships, as the `shadows` settings allow
  (`object_shadows`, and the terrain and cloud map sizes: all on from the
  `mid` preset up).
- **Far plane.** `CAMERA_FAR_M` (in `space_flight/__init__.py`, applied by
  `player.py`) is 600 km, kept by the rear-view mirror. `load_world` sets the
  main lens's far plane before the world is built, because the ocean's
  reflection camera copies the lens.

## Where things live

`Scene` and its subclasses are in `scenes.py`, with the loading gate
`wait_until_loaded` (which sleeps a few milliseconds per step while loading,
so the worker processes' results get through a loading loop run flat out, as
a headless build runs it). `level_frame.py` is the chart-to-world frame of a
planet of a WorldBuilder world file. `planet_2d.py` is the 2D planet. The world, the
asteroid fields and their shaders are in WorldBuilder (`world_builder.world`,
`world_builder.asteroids`).
