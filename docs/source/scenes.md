# Scenes

`scenes` builds the environment a level flies in — skybox, lighting, planets,
asteroid fields, ocean, and volumetric clouds — as a set of independent,
game-agnostic dressing objects assembled by a per-level `Scene` subclass.
This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](docs/).

All of it lives in [`src/space_flight/scenes/`](../src/space_flight/scenes/),
with the cloud system under
[`scenes/cloud/`](../src/space_flight/scenes/cloud/).

## Mental model

- A **`Scene`** subclass is a level's environment recipe: it owns instances of
  the individual environment pieces below and nothing else — no gameplay
  logic. `scene_factory(game, scene_name)` picks one by name; a level's
  builder (see [docs/game.md](game.md)) calls `build_upfront()` then
  `build_decomposed()` on it.
- Every scene splits its work into the same two-phase shape the level
  builders expose: **`build_upfront()`** does the GPU-heavy, one-time-prep
  objects (ocean, cloud field) synchronously on the black screen before the
  hyperspace animation; **`build_decomposed()`** is a generator that yields
  between the remaining, cheaper pieces (skybox, lighting, planet, dust,
  static set-dressing models) so the animation keeps rendering while they
  build. This mirrors — and is driven by — `FlightState`'s own two-phase
  level entry (see [docs/game.md](game.md)).
- Every environment piece follows the same lifecycle contract as everywhere
  else in the codebase: constructed with `game`, optionally registers a
  per-frame update in `game.method_lists`, exposes `clean()`.
- Several pieces "follow the camera to infinity" by re-centring themselves on
  the player each frame (`Skybox`, `Planet2D`) rather than being fixed in
  world space, so a small/cheap piece of geometry can represent something
  arbitrarily distant.

## `scenes.py` — the `Scene` catalogue

[`scenes.py`](../src/space_flight/scenes/scenes.py) has one `Scene` subclass
per named environment, selected by `scene_factory`:

| Name | Class | Composition |
|------|-------|-------------|
| `asteroids` | `SceneAsteroids` | purple skybox, three asteroid fields (static + two rotating), dust, a drydock model |
| `lava_planet` | `SceneLavaPlanet` | lava-toned lighting, asteroid fields, a 2D lava planet, an Imperial Star Destroyer |
| `ocean_planet` | `SceneOcean` | dusk skybox, `Ocean`, volumetric `Clouds`, a 2D terran planet, a Star Destroyer |
| `debug` | `SceneDebug` | a bare skybox + lighting, nothing else |

Each subclass's `build_upfront`/`build_decomposed` pair is a thin assembly
list rather than logic: it constructs the pieces documented below in a fixed
order and yields a label after each `build_decomposed` step (used for
progress/debugging), then `clean()` tears every owned piece down in reverse.
`SceneOcean` is the most heavily commented example of *why* particular
objects (the ocean, the cloud field) belong in `build_upfront` — their
one-time shader compile/vertex upload is explicitly force-prepared
(`prepare_scene(gsg)`) while the screen is still black, which the module
docstring notes must run only once the player already exists, since the
ocean's reflection camera copies the player camera's lens.

## Static environment pieces

- **[`skybox.py`](../src/space_flight/scenes/skybox.py)**'s `Skybox` loads a
  named `.bam` skybox model at a huge scale, disables shading/lighting/depth
  write on it (it's a background painted at infinity), and re-centres itself
  on the player's position every frame so it never appears to move — the
  simplest example of the "follow to infinity" pattern. It also opts itself
  out of the ocean reflection camera's clip plane (`setClipPlaneOff(1)`),
  with a comment explaining the visible horizon-band artifact that would
  otherwise appear in the reflection at altitude.
- **[`lighting.py`](../src/space_flight/scenes/lighting.py)**'s `Lighting` is
  a plain directional + ambient light pair attached to `game.root_node`,
  parameterised by colour and direction — no per-frame behaviour, just
  setup and `clean()`.
- **[`planet_2d.py`](../src/space_flight/scenes/planet_2d.py)**'s `Planet2D`
  is a single camera-facing textured card (not a sphere) placed far away and
  scaled up — a cheap billboard for a background celestial body. Like the
  skybox, it re-centres on the player each frame (`move_planet_task`) using a
  position stored *relative to* the player, so it appears fixed in the
  distance regardless of how far the player has actually travelled.
- **[`asteroid_field.py`](../src/space_flight/scenes/asteroid_field.py)**'s
  `AsteroidField` scatters `n_asteroids` model instances randomly inside a
  cube, each with a random scale and terrain collision sphere. When
  `is_moving=True` it also gives each asteroid a fixed random spin rate and
  drives their orientation through the shared physics `Integrator` (see
  [docs/game.md](game.md)) exactly like a ship's rotational state — one flat
  state vector of `4 * n_asteroids` quaternion components integrated
  together, rather than per-asteroid objects. A scene typically layers
  several `AsteroidField`s at different counts/scales/speeds (see
  `SceneAsteroids`) to combine a dense static backdrop with a few large,
  slowly tumbling foreground rocks.

## `ocean.py` — clipmap-free reflective ocean

[`ocean.py`](../src/space_flight/scenes/ocean.py)'s `Ocean` is the most
elaborate single-file piece of environment code in the game (see its own
module docstring for the full picture):

- **Camera-locked, per-pixel waves.** The ocean surface has no vertex
  displacement in the default mode — a single huge flat quad, sized past the
  camera's far clip (`_PLANE_FAR_FACTOR`) and re-centred under the camera
  every frame, with all wave detail computed per-pixel in the fragment
  shader from world position. `compute_wave_dirs` precomputes the
  per-iteration wave direction table on the CPU once (rather than
  recomputing trig per pixel per iteration in the shader) and uploads it as
  a uniform array. An optional `geometric_swell` prototype mode instead
  builds a dense, vertically displaced grid (`make_swell_grid_mesh`) for a
  large-scale swell, tapering to flat at its edges so it joins the outer
  flat quad seamlessly.
- **Planar reflections.** `make_reflection_buffer` builds an offscreen
  texture buffer and a mirrored reflection camera (`mirror_camera` flips the
  main camera's Z position/pitch/roll about the water plane each frame,
  called from `update`), clipped to only render geometry above the water
  plane. The buffer is sized off `GraphicsManager.get_render_size()` (see
  [docs/global_architecture.md](global_architecture.md)) scaled by
  `reflection_scale`, so it tracks the chosen internal render resolution
  rather than the window. `uReflUVScale` corrects for GPU texture padding to
  a power of two, refreshed once the buffer's real texture size is known
  post-realization since it differs between the default pipeline (which
  pads) and simplepbr (which doesn't).
- Registers a flat terrain collision plane at Z=0 via
  `attach_collision_plane` (see [docs/game.md](game.md)) so ships can crash
  into the water.
- `set_wave_iterations()` exposes wave-detail quality as a runtime knob (for
  a settings menu) independent from the fixed shader source.

## `cloud/` — volumetric billboard clouds

[`scenes/cloud/`](../src/space_flight/scenes/cloud/) splits cleanly along the
CPU-data/GPU-field line its own package docstring calls out:

- **[`cloud.py`](../src/space_flight/scenes/cloud/cloud.py)** owns a single
  cloud *shape*, entirely on the CPU, with no GPU involvement:
  - **`CloudType`** (`CUMULUS`/`STRATUS`/`CIRRUS`/`CUMULONIMBUS`) selects a
    `DEFAULTS` preset of shape/optical parameters.
  - **`build_cloud_particles`** procedurally scatters billboard particles by
    rejection sampling inside a type-specific envelope function
    (`_envelope_radius` — a rounded dome, a flat slab, a tapered sheet, or an
    anvil-flaring tower depending on type), carved with Worley noise
    (`_worley_accept`) for lumpy internal detail, with cirrus additionally
    sheared along wind (`_apply_cirrus_warp`) for a fibrous streak look.
  - **`_shade_particles`** bakes a per-particle RGB colour with a one-off CPU
    ray-cast self-shadow trace: particles are processed sunward-first so
    each one's occluders already have resolved transmittance, and a
    Beer-Lambert-style attenuation through the nearest occluder's chord
    darkens particles buried inside the cloud — this is what gives a cloud
    its own directional shading without any runtime lighting cost.
  - **`build_templates`/`build_templates_iter`** package a handful of
    distinct shaded shapes (the expensive step: generation + shading) into
    reusable templates that the field scatters many copies of; the
    generator form yields one finished template at a time so a loader can
    spread the ~20-40ms/template cost across frames. An optional on-disk
    cache (`use_cache=True`, keyed by a content hash of every input —
    `_template_cache_key`) skips regeneration entirely on repeat launches,
    since the generation is fully deterministic in its inputs.
- **[`field.py`](../src/space_flight/scenes/cloud/field.py)** turns templates
  into a drawable, animated field — the GPU/runtime half:
  - **`CloudLayer`** is a per-type placement spec (count, altitude range,
    how many distinct templates to build and cycle through); a `CloudField`
    takes a list of layers so multiple cloud types (e.g. cumulus + cirrus)
    coexist and depth-sort correctly against each other in one shared `Geom`.
  - **Wind/recycling without touching vertex data.** Particle positions are
    stored relative to their cloud's centroid; only a small per-cloud
    centroid texture is updated each frame (wind drift, plus toroidal
    wraparound recycling within a camera-centred `domain` box) — the heavy
    per-particle vertex buffer never changes after the initial build. The
    vertex shader looks up each particle's centroid from that texture and
    builds the camera-facing billboard itself.
  - **Depth-correct transparency without a full re-sort.** Particles use
    premultiplied-alpha "over" blending, which requires back-to-front order.
    `_restage` re-sorts only a `1/resort_frames` slice of clouds each frame
    (round-robin), snapshotting a fresh whole-field draw order at the start
    of each cycle and uploading the reordered index buffer once per
    completed cycle — spreading the sort cost instead of spiking one frame.
  - **Lighting** uses a Henyey-Greenstein phase function in the fragment
    shader for a forward-scatter "silver lining" glow when looking toward
    the sun through a cloud edge, plus a separate backward-lobe term that
    brightens the near, sun-facing shell when the sun is behind the viewer.
  - **`Clouds`** is the thin game-facing wrapper matching every other scene
    piece's contract (construct with `game`, register `update` in
    `game.method_lists`, `clean()`), delegating everything else to
    `CloudField`. Its `build()` generator mirrors `CloudField.build()` for
    `defer_build=True` use from a level's `build_decomposed`.

## Where things live

`Scene` and its subclasses live in
[`scenes.py`](../src/space_flight/scenes/scenes.py); static pieces are one
file each (`skybox.py`, `lighting.py`, `planet_2d.py`,
`asteroid_field.py`); the ocean is `ocean.py`; the cloud system lives under
[`scenes/cloud/`](../src/space_flight/scenes/cloud/) split into
`cloud.py` (CPU shape data) and `field.py` (GPU field + game wrapper). The
auto-generated [code reference](docs/) has the full per-class API.
