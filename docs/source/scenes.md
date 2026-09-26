# Scenes

`scenes` builds the environment a level flies in — skybox, lighting, planets,
asteroid fields, ocean, and volumetric clouds — as a set of independent,
game-agnostic dressing objects assembled by a per-level `Scene` subclass.
This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](apidocs/index.rst).

All of it lives in [`src/space_flight/scenes/`](../../src/space_flight/scenes/),
with the cloud system under
[`scenes/cloud/`](../../src/space_flight/scenes/cloud/).

## Mental model

- A **`Scene`** subclass is a level's environment recipe: it owns instances of
  the individual environment pieces below and nothing else — no gameplay
  logic. `scene_factory(game, scene_name)` picks one by name; a level's
  builder (see [docs/game.md](game.md)) calls `build_upfront()` then
  `build_decomposed()` on it.
- Every scene splits its work into the same two-phase shape the level
  builders expose: **`build_upfront()`** builds the heavy objects
  synchronously on the black screen before the hyperspace animation — the
  ocean and cloud field for `SceneOcean` (whose one-time GPU prep it also
  forces, see below), the asteroid fields for `SceneAsteroids` and
  `SceneLavaPlanet` (built, but without a forced `prepare_scene`);
  **`build_decomposed()`** is a generator that yields
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

[`scenes.py`](../../src/space_flight/scenes/scenes.py) has one `Scene` subclass
per named environment, selected by `scene_factory`:

| Name | Class | Composition |
|------|-------|-------------|
| `asteroids` | `SceneAsteroids` | purple skybox, three asteroid fields (static + two rotating), dust, a drydock model |
| `lava_planet` | `SceneLavaPlanet` | lava-toned lighting, asteroid fields, a 2D lava planet, an Imperial Star Destroyer |
| `ocean_planet` | `SceneOcean` | dusk skybox, `Ocean` (with geometric swell on), volumetric `Clouds`, a 2D terran planet, dust (its Star Destroyer block is commented out) |
| `debug` | `SceneDebug` | a bare skybox + lighting, nothing else |

Each subclass's `build_upfront`/`build_decomposed` pair is a thin assembly
list rather than logic: it constructs the pieces documented below in a fixed
order and yields a label after each `build_decomposed` step (used for
progress/debugging), then `clean()` tears the owned pieces down roughly in
reverse. `SceneOcean` is the most heavily commented example of *why* particular
objects (the ocean, the cloud field) belong in `build_upfront` — their
one-time shader compile/vertex upload is explicitly force-prepared
(`prepare_scene(gsg)`) while the screen is still black, which
`SceneOcean.build_upfront`'s docstring notes must run only once the player
already exists, since the ocean's reflection camera copies the player
camera's lens.

## Static environment pieces

- **[`skybox.py`](../../src/space_flight/scenes/skybox.py)**'s `Skybox` loads a
  named `.bam` skybox model at a huge scale, disables shading/lighting/depth
  write on it (it's a background painted at infinity), and re-centres itself
  on the player's position every frame so it never appears to move — the
  simplest example of the "follow to infinity" pattern. It also opts itself
  out of the ocean reflection camera's clip plane (`setClipPlaneOff(1)`),
  with a comment explaining the visible horizon-band artifact that would
  otherwise appear in the reflection at altitude.
- **[`lighting.py`](../../src/space_flight/scenes/lighting.py)**'s `Lighting` is
  a plain directional + ambient light pair attached to `game.root_node`,
  parameterised by colour and direction — no per-frame behaviour, just
  setup and `clean()`.
- **[`planet_2d.py`](../../src/space_flight/scenes/planet_2d.py)**'s `Planet2D`
  is a single textured card (not a sphere) with a fixed orientation, placed
  far away and scaled up — a cheap stand-in for a background celestial body
  (it doesn't turn to face the camera). Like the
  skybox, it re-centres on the player each frame (`move_planet_task`) using a
  position stored *relative to* the player, so it appears fixed in the
  distance regardless of how far the player has actually travelled. Its
  nominal distance is arbitrary, so it draws in the "background" bin with no
  depth write: merely being transparent put it in the "transparent" bin (sort
  30), after the clouds (25), and it painted over the cloud field.
- **[`asteroid_field.py`](../../src/space_flight/scenes/asteroid_field.py)**'s
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

[`ocean.py`](../../src/space_flight/scenes/ocean.py)'s `Ocean` is the most
elaborate single-file piece of environment code in the game (see its own
module docstring for the full picture):

- **Camera-locked, per-pixel waves.** The ocean surface has no vertex
  displacement in the default mode — a single huge flat quad, re-centred under
  the camera every frame, with all wave detail computed per-pixel in the
  fragment shader from world position. `compute_wave_dirs` precomputes the
  per-iteration wave direction table on the CPU once (rather than
  recomputing trig per pixel per iteration in the shader) and uploads it as
  a uniform array. An optional `geometric_swell` prototype mode (which
  `SceneOcean` enables) instead builds a dense, vertically displaced grid
  (`make_swell_grid_mesh`) for a large-scale swell, tapering to flat at its
  edges so it joins its flat border seamlessly — in this mode the border is
  a set of geometrically spaced rings in the same mesh, not a separate outer
  quad.
- **Curved over the planet** (swell mode). Every vertex droops by
  `d² / 2R`, baked into the mesh: that is exact because the mesh is re-centred
  on the camera, the same origin the cloud shader droops from, and it costs
  nothing per frame. The horizon then dips `sqrt(2h/R)` below eye level (1.0° at
  1 km, 3.05° at 9 km) instead of sitting dead level. The border has to be rings
  rather than one quad, because a quad can only interpolate linearly and would
  droop into a cone; the ring spacing is geometric because the flat-cell error
  is `spacing² / 8R`, and 28 rings keep it under 1 arcmin everywhere (0.2 at
  1 km, 0.8 at 9 km) for about 22% more triangles — 15 rings would give 2.9.
  The surface is sized to reach past the horizon, `sqrt(2R·altitude)` (about
  505 km for 20 km of eye altitude), so the planet's own bulge hides its edge;
  sizing it off the 600 km far plane would ask for 1800 km. Two things stay flat
  on purpose: the collision plane (the ship is always within metres of the
  camera, where the droop is micrometres) and the planar reflection, which
  mirrors about z=0 and drifts by the droop with distance — 7.8 m at 10 km,
  where the normal is already flattened to a mirror.
- **Aerial perspective.** Distant water fades to the same `HAZE_COLOR` as the
  cloud field (applied after the tonemap, as the clouds do), so sea and sky meet
  at the horizon. Its haze distance is much shorter than the clouds': the air
  path to sea level is far denser than the path to cloud at altitude.
- **The far plane** is raised to 600 km (`CAMERA_FAR_M` in `player.py`, set
  before the scene is built because the reflection camera copies the lens).
  Panda's default 100 km clips the outermost cloud shell and gives a correct
  ocean horizon only up to 785 m of altitude; 600 km clears the 512 km shell and
  keeps the horizon in view to about 28 km. It is nearly free for depth
  precision, which goes as `z² / (near · 2^bits)` and is set by the near plane.
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
  pads) and simplepbr (which doesn't; simplepbr is currently disabled — its
  init is commented out in `global_architecture/simulator.py`).
- Registers a flat terrain collision plane at Z=0 via
  `attach_collision_plane` (see [docs/game.md](game.md)) so ships can crash
  into the water.
- `set_wave_iterations()` exposes wave-detail quality as a runtime knob (for
  a settings menu) independent from the fixed shader source.

## `cloud/` — volumetric billboard clouds

[`scenes/cloud/`](../../src/space_flight/scenes/cloud/) is built on two ideas, and
almost every design decision in it follows from one of them.

**A billboard is a sample of a volume, not a sprite.** Its geometry says only
where in the volume it sits and how many metres of cloud lie behind each of its
pixels; the outline, the opacity and the colour are continuous functions of world
position, evaluated per fragment. Nothing about appearance may be carried per
particle, because anything that is shows up as quad-shaped patches once the field
gives each billboard a crisp footprint.

**A cloud is not an object.** A cloud *type* is one density field spanning a slab
of sky, and the clouds you see are its features. That is what lets clouds shadow
each other, and it is why their silhouettes are exactly as crisp as the field is.

- **[`noise.py`](../../src/space_flight/scenes/cloud/noise.py)** owns what a type
  looks like:
  - **`DensityField`** is the shape in full: the slab, the per-axis noise scale
    (hence the feature size), the four fbm octaves, how much of the sky is cloud,
    and the vertical profile. A frozen dataclass, so a field cannot be mutated
    behind the shader's back.
  - **`coverage`** is *how much* cloud there is, authored as the fraction of that
    type's own slab which is cloud, measured zenith-projected — a column counts if
    there is cloud at any height in it. Per type, so a cumulus deck at 0.3 under a
    cirrus veil at 0.3 leaves `0.7 × 0.7` of the sky clear, not `0.4`.

    The smoothstep window the shader actually uses is *derived* from it, not
    authored: `column_peaks` measures the per-column peak field strength over one
    noise period and sorts it, which is the exact inverse of the coverage
    function, so the threshold is a quantile of that array — no solver, no fitting.
    Two reasons it has to work this way. A window cannot be baked into a preset at
    all, because which raw fbm value means "30% of the sky" depends on the noise
    volume and therefore on the seed; and deriving it decouples *amount* from
    *shape*, so retuning the octave weights no longer silently changes how much
    cloud there is. `resolve_field` fills the window in, and `measure_coverage`
    reads it back — a round trip the tests assert at an independent resolution.

    Coverage is not orthogonal to cloud type. Thresholding a 1/f field is a
    percolation transition, so the low end gives isolated puffs and the high end a
    connected sheet with holes; `CUMULUS` at 0.9 is genuinely stratus-like. It is
    also the most expensive knob, because billboards fill a *volume* while coverage
    measures a *projection* — a covered column is also cloudy over a taller stretch
    of its slab, so doubling coverage roughly triples the billboard count.
  - **`edge_softness`** is the window's width, in standard deviations of that
    field's own fbm (`fbm_sigma`). A narrow window is the entire source of the
    crisp cauliflower edge. In sigma rather than raw fbm units so it means the same
    thing for every type and survives a change of octave weights.
  - **`value_noise_volume`/`build_noise_texture`** generate the single tileable
    octave the shader taps four times, as a `sampler3D`. Not a baked fbm: the
    octaves are sampled at 1/2/7/16 with independent offsets, baking them would
    freeze their relative phase, and resolving the 16x octave would need 1024³.
  - **`density`** evaluates the field on the CPU *exactly* as the fragment shader
    does — same trilinear half-texel addressing, same 8-bit quantisation. That
    equality is load-bearing: it is what lets placement be driven by the very
    field that will be drawn.
  - Two types share one volume and are decorrelated by a constant offset in noise
    space (`field_offset`) — an independent field with identical statistics, for
    the cost of an add.
- **[`cloud.py`](../../src/space_flight/scenes/cloud/cloud.py)** decides where a
  type's billboards go, entirely on the CPU:
  - **`PRESETS`** maps `CloudType` (`CUMULUS`/`STRATUS`/`CIRRUS`/
    `CUMULONIMBUS`) to a `CloudSpec` — a field plus a billboard radius range and
    a target volume fraction. Every shape parameter lives inside the field, so a
    type is described the way a field is described rather than through envelope,
    tower, anvil and Worley knobs.
  - **`sample_field_particles`** rejection-samples the slab and keeps the points
    the field calls cloud, so the field alone bounds each cloud. The accept rate
    measures the cloud's volume directly, which is what makes the extinction
    calibration exact rather than tuned (`volume_fraction`): extinction is the
    field's density divided by the achieved sphere-volume fraction and the
    sprites' mean alpha, so changing the billboard budget is a performance
    decision and not a look change.
  - **`snap_to_noise_period`** trims a layer's recycle box down to a whole number
    of the field's noise periods. A cell teleporting by such a width lands where
    the field is bit-identical, so the recycle is invisible and needs no fade —
    which is why `wrapFadeBand` is zero for an isotropic layer.
- **[`field.py`](../../src/space_flight/scenes/cloud/field.py)** turns a placement
  into a drawable, animated field — the GPU/runtime half:
  - **`CloudLayer`** is one type's worth of sky. Note what it does *not* carry: no
    cloud count and no altitude range, because the billboard count follows from
    the field's coverage and the altitude *is* the field's slab.
  - **Per-type fields on the GPU** ride in a `layerParams` uniform array indexed
    by a flat layer id (twelve `vec4`s each). A uniform array rather than a texture:
    a fragment needs two dozen of its type's parameters, which as `texelFetch`es
    would be two dozen texture reads per pixel and as varyings would burn most of
    the interpolator budget.
  - **Wind/recycling without touching vertex data.** Particle positions are
    stored relative to their *cell's* centre; only a small per-cell parameter
    texture is updated each frame (wind drift, plus toroidal wraparound within a
    camera-centred `domain` box) — the heavy per-particle vertex buffer never
    changes after the build. The vertex shader looks the centre up and builds the
    camera-facing billboard itself. The same wind advects the noise coordinate, so
    a billboard sits at a fixed place in the field and keeps its shape as it
    drifts instead of dissolving.
  - **Depth-correct transparency without a full re-sort.** Particles use
    premultiplied-alpha "over" blending, which requires back-to-front order.
    `_restage` re-sorts only a `1/resort_frames` slice of *cells* each frame
    (round-robin), snapshotting a fresh whole-field draw order per cycle and
    uploading the reordered index buffer once per completed cycle. Cell
    populations vary, so the particle arrays are ragged with a `cell_start`
    offsets table — padding to the largest cell would cost about 3x the vertex
    memory at cumulus coverage — and the ragged gather plus sort is still one
    `lexsort` keyed on (cell rank, distance), with no Python loop over cells.
  - **Lighting** follows the reference shader: a dual-lobe Henyey-Greenstein
    phase for the forward-scatter silver lining, a short per-fragment march
    toward the sun through the shared field (which is what makes clouds shadow
    each other), the "powder" dark-edge term, a multiple-scattering fill, and a
    soft-knee roll-off. All live uniforms — `set_sun` moves the sun with no
    rebuild, because nothing is baked. Three details there are worth knowing,
    because each was wrong once and each has a visible signature:
    - `sun_brightness` and `exposure` are *not* independent gains. The knee
      saturates above about 3, so too bright a pair flattens the lit and shadowed
      sides onto the same white.
    - The knee is applied to the **peak channel** and used to scale the colour,
      not to each channel independently. Per-channel drives every channel to the
      same asymptote, so an orange dusk sun at silver-lining intensity maps to
      white — the brightest, most saturated highlights being exactly the ones that
      lose the sun's colour.
    - The multiple-scattering fill is **sky-coloured and not phase-weighted**.
      Light reaching a shadowed interior arrives from the sky and from
      neighbouring cloud, not down a beam. As a floor on sun *visibility* it was
      both sun-tinted (so dusk shadows came out orange instead of blue-grey) and
      phase-multiplied (so looking toward the sun made shadowed cloud brighter
      than side-lit sunlit cloud, flattening a dusk deck to one uniform orange).

    And a few more in `cloud.frag`, each also a fixed bug:
    - The field is sampled **on the quad plane**, not offset back to mid-chord.
      The offset displaced the lookup by up to a particle radius — most of a noise
      feature — and varied with radius and across the sprite, so overlapping
      billboards disagreed about where the cloud was and cut holes in each other.
    - The **powder** term takes the *local* density over a fixed reference length.
      Fed the sunward depth, it inverts (the lit surface gets the heaviest
      darkening); fed the quad's own chord, it depends on billboard size (small
      near quads went dark, large far ones white).
    - The **sun march** uses only the two lowest octaves, affinely calibrated
      (`noise.shadow_calibration`) onto the full field. Plain renormalisation left
      the mean and spread too high: the march saw 1.65x the cloud and greyed the
      tops in full sun.
    - The **LOD crossfade** weights *optical depth*, after the per-billboard cap.
      On depth the shells' transmittances multiply out exactly; on alpha two
      half-weight billboards at depth 1.5 composite to 0.544 instead of 0.65, a
      ~16% light ring that sweeps with the camera. Weighting before the cap would
      let each shell reach it and sum to twice it.
    - **Aerial perspective** tends to the haze *colour*, never to transparent:
      fading alpha made a deck seen from above take on the ground behind it.
  - **An open idea** for cirrus: the atlas sprites are painted cumulus puffs, and
    stretching magnifies their detail along the long axis — backwards for a wisp,
    which wants fine detail along and softness across. A cheap fix would modulate
    the sprite's thickness by a 1-D tap of the existing noise volume along the
    stretched axis, where aspect > 1 (the aspect would need passing to the
    fragment stage). Not done: the field's own anisotropy may be enough.
  - **Quality** (`CloudQuality`, `at_quality`) scales a type's cost across
    LOW/MID/HIGH/ULTRA, read from `clouds.quality` in the graphics settings.
    HIGH is the identity — what the presets ship — so a caller with no settings
    (the demo scripts, the tests) gets the authored look rather than a silent
    downgrade. Two knobs, scaled differently on purpose:

    Billboard count takes the full ×0.25/×0.5/×1/×2 spread, because that is where
    the frame time is (measured 2.3 / 3.6 / 5.8 / 11.4 ms on a six-shell deck).
    The count is changed through the **radius**, not through `volume_fraction`:
    since `volume_fraction` is `(4/3)·π·n·<r³>`, holding it fixed makes the count
    fall as the cube of the radius — the same conservation law `lod_shells` uses
    for distance, so quality is that trade applied globally instead of per shell.
    Cutting `volume_fraction` was the obvious approach and is worse: it holds
    optical depth exactly, but only where billboards still reach, and at a cloud's
    fringe removing them removes the silhouette rather than thinning it. Measured
    at LOW, that cost 18% of the cloud's screen area against 8.8% for the radius,
    with more grain and no saving.

    Bigger billboards cost so little here because a billboard is not a sprite:
    density is evaluated *per fragment* from the field, so lateral detail and the
    silhouette do not depend on quad size. What a bigger radius coarsens is the
    **chord** — one billboard standing in for a longer stretch of volume from a
    single mid-chord sample — so what degrades is resolution along the view ray.

    The sun march is stepped far more gently (×2/3 a level, not ×1/2), because it
    is what makes clouds shadow themselves and so carries most of their form; and
    its **reach** (`sun_steps × sun_step_length`) is held constant while only its
    resolution changes. Beer-Lambert exponentiates the integral, so a coarser
    sampling of the same path approximates it well — a shorter path approximates
    nothing.
  - **What can change live**, and what needs a rebuild, is decided by whether
    placement depends on it. `set_sun` and `set_optics` are pure uniform writes.
    `set_coverage` is the interesting case: the expensive half of the calibration
    is the sorted column peaks, and those never change, so re-deriving a threshold
    is an array index rather than a fresh measurement. But it re-packs *without*
    re-placing, and placement was rejection-sampled at the coverage the field was
    built at — so lowering coverage is exact (the surplus billboards fall below the
    higher bar and discard, and extinction is per-billboard so what remains keeps
    the right optical depth), while raising it past the built value has no
    billboards to draw the new cloud with and grows holes instead. A tuning knob,
    in other words; committing a higher coverage means rebuilding.
  - **`Clouds`** is the thin game-facing wrapper matching every other scene
    piece's contract (construct with `game`, register `update` in
    `game.method_lists`, `clean()`), delegating everything else to
    `CloudField`, which builds synchronously in its constructor.

Two things the headless tests cannot check, and which therefore need
[`scripts/demo_clouds.py`](../../scripts/demo_clouds.py) or an offscreen GL context:
the pixels, and whether the GLSL compiles at all — `Shader.load` succeeds with no
graphics context.

The demo builds its deck with **coverage headroom** above the authored value,
because `set_coverage` is only exact downward. Measured on six shells at
1280x720 from a 0.29 deck: no headroom is 100k billboards and 9.6 ms, 0.15 is
170k and 15.3 ms, 0.25 is 221k and 17.6 ms; 0.15 buys a 0.29 → 0.44 sweep, which
crosses from isolated puffs toward the percolated, sheet-with-holes regime. Its
`forward_gain` sweep stops at 15: above about 10 the view into the sun clips in
the tonemap, and past about 20 (at 0.4 anisotropy) the phase solve needs a
negative isotropic weight. The ground is a curved polar mesh for the same reason
as the ocean — a flat plane clips the drooped deck beyond about 113 km — with
256 segments (0.26 arcmin of flat spot, against 1.0 at 128) out to 550 km, good
for eye heights to about 24 km. Its cirrus layer (`WITH_CIRRUS`) is toggled by
zeroing the layer's optical-depth cap, since every layer shares one Geom: a look
toggle, not a cost saving.

## Where things live

`Scene` and its subclasses live in
[`scenes.py`](../../src/space_flight/scenes/scenes.py); static pieces are one
file each (`skybox.py`, `lighting.py`, `planet_2d.py`,
`asteroid_field.py`); the ocean is `ocean.py`; the cloud system lives under
[`scenes/cloud/`](../../src/space_flight/scenes/cloud/) split into `noise.py` (the
density field), `cloud.py` (placement) and `field.py` (GPU field + game
wrapper), with the shaders in `datafiles/shaders/cloud.vert|frag`. The
auto-generated [code reference](apidocs/index.rst) has the full per-class API.
