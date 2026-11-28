# Shaders

[`src/space_flight/datafiles/shaders/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/datafiles/shaders/)
holds the GLSL the game loads from disk (as opposed to shaders baked into
imported models). GLSL isn't covered by the docstring-generated
[code reference](apidocs/index.rst), so this page says what each shader does
and which Python module compiles and drives it. The ocean's and the
volumetric clouds' shaders come with them from
[WorldBuilder](https://github.com/JoeDalton/WorldBuilder) and are covered in
its [ocean](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/ocean.md) and [clouds](https://github.com/JoeDalton/WorldBuilder/blob/main/docs/source/clouds.md) pages.

## Mental model

- Every shader is `#version 140` GLSL,
  loaded with `Shader.load` and fed only by uniforms, textures and vertex
  columns from Python — nothing persists on the shader side between frames.
- `shield.frag` carries its own copy of a small value-noise kit
  (`hash`/`smoothNoise` and a variant `fbm`), from the same lineage as
  WorldBuilder's ocean shaders.
- Shaders that sample an offscreen render target correct for Panda3D padding
  it up to a power of two (WorldBuilder's ocean samples only the
  `uReflUVScale` fraction of its reflection; the rear-view mirror's card
  takes its texture's tex scale). (The hyperspace shaders work from
  `gl_FragCoord`/`iResolution` on plain render2d cards and don't need this.)
- **Render space is not world space.** The render origin stays on the player
  (see [the floating render origin](game.md#the-floating-render-origin)), so
  `p3d_ModelMatrix`, `p3d_ViewMatrix` and `p3d_ViewProjectionMatrix` are
  relative to a frame that moves every frame. A shader must never combine them
  with a world position. The shaders here stay consistent in one of three
  ways:
  - **Their own world matrix.** WorldBuilder's `ocean.vert` takes
    `uModelMatrix`, the plane's matrix relative to the ocean's base node, so
    its world position, `iCameraPos` and `uReflMVP` share that frame.
  - **One frame on the GPU.** `shield.frag` takes the eye from
    `p3d_ViewMatrixInverse`, in the same render space as its
    `p3d_ModelMatrix` position. `laser.vert` works in model space.
  - **Model space, placed by the node.** `spark.vert` and `explosion.vert`
    place vertices relative to their particle buffer's anchor, and project
    them with `p3d_ModelViewProjectionMatrix`, whose model part carries the
    anchor's place (see
    [the floating render origin](game.md#the-floating-render-origin)).
    WorldBuilder's `cloud.vert` places its own geometry around the camera.

## Hyperspace shaders

Drawn by
[`fx/hyperspace_overlay.py`](../../src/space_flight/fx/hyperspace_overlay.py)
(see [fx.md](fx.md)), for both the loading screen and the in-flight warp: one
fullscreen fragment shader per phase of the jump, sharing the position-only
passthrough
[`hyperspace.vert`](../../src/space_flight/datafiles/shaders/hyperspace.vert).

What the three phases share lives in
[`hyperspace_common.glsl`](../../src/space_flight/datafiles/shaders/hyperspace_common.glsl),
pulled in with `#pragma include "hyperspace_common.glsl"` (Panda3D resolves it
next to the including shader). That covers the uniforms, the screen point and
mouse rotation, `rand`/`sdLine`, and `overlay_color`, the single place that
turns an effect colour into the final fragment:

- **Alpha is the larger of the background opacity and the colour's brightness.**
  The black background can then go transparent while bright streaks and glows
  stay visible.
- **The colour is divided by alpha,** so it keeps its brightness when blended
  over the scene.

The loading screen and the warp differ only in their **look**, a few uniforms
set from Python's `HyperspaceLook`:

| Uniform | Effect | Loading | Warp |
|---|---|---|---|
| `iBackgroundOpacity` | opacity of the black background | 1 | 0 |
| `iTunnelOpacity` | overall opacity of the inside tunnel | 1 | `WARP_TUNNEL_OPACITY` |
| `iMaxWhiteout` | strength of the white flashes, and of the into flare's final swell over the screen | 1 | `WARP_MAX_WHITEOUT` (0: no flash) |
| `iFlare` | strength of the star-like lens flare at the centre of into | 1 | 0 |

With the loading look (all at 1) the output is exactly the original opaque
effect. The warp look lets the scene show through everywhere but the streaks.

- **[`hyperspace_into.frag`](../../src/space_flight/datafiles/shaders/hyperspace_into.frag)**
  (entering hyperspace): star streaks converge into a central lens flare that
  grows and whites out the screen.
  - Streaks are procedural per-slice line segments (`sdLine`), with
    offset/speed/length seeded per slice (`rand`).
  - The animation length is the `iIntoDuration` uniform, fed from Python's
    `INTO_DURATION`, so the whiteout always matches the Python phase.
  - Time is **clamped**, not wrapped, so the white frame holds for the
    cross-fade into the tunnel instead of restarting the trails.
- **[`hyperspace_inside.frag`](../../src/space_flight/datafiles/shaders/hyperspace_inside.frag)**:
  the seamlessly looping warp tunnel. A 3D simplex-noise fBm (`loopFbm`) is
  sampled around a circle in depth-phase space instead of tiled with `mod()`,
  so every octave is periodic over the loop period `T_LOOP` and there is no
  seam.
- **[`hyperspace_outof.frag`](../../src/space_flight/datafiles/shaders/hyperspace_outof.frag)**
  (dropping out): the reverse of `hyperspace_into.frag`. Streaks collapse into
  the revealed scene, fading from an initial whiteout.
  - From 35% of its loop, its background opacity falls to 0, so the live
    scene shows through while the streaks still play.
  - The 35% must match the loading screen's `REVEAL_START`, which starts the
    simulation at that moment.

`into` and `outof` are adapted from one ShaderToy source and `inside` from
another (MIT); the header comments carry the credits.

## Render scale, anti-aliasing and FSR 1

The game has no post-process shaders of its own any more: the view's way to
the screen (render scale, MSAA, FXAA, FSR 1's EASU and RCAS) is WorldBuilder's
(`world_builder.post`), drawn by the world's depth camera and by the rear-view
mirror's chain.

## Shield shaders

Driven by
[`actors/major_ship/shield_model.py`](../../src/space_flight/actors/major_ship/shield_model.py)
(see [subsystems.md](subsystems.md)):

- **[`shield.vert`](../../src/space_flight/datafiles/shaders/shield.vert)**
  forwards both *object-space* position/normal (the surface pattern and the
  death sink points are anchored to the hull, so they stay put as the ship
  rotates) and *render-space* ones (for the fresnel rim). With the eye from
  `p3d_ViewMatrixInverse`, the rim is right in every pass (main view,
  rear-view mirror, ocean reflection) without a camera uniform.
- **[`shield.frag`](../../src/space_flight/datafiles/shaders/shield.frag)**:
  - **Living look.** A triplanar value-noise field (`surfacePattern`, weighted
    by the object-space normal, so no seams or poles on any mesh) of a slowly
    morphing, domain-warped `smoothField`, plus a fresnel rim, a health colour
    ramp (blue → violet → pink as `uHealth` drops) and per-impact flashes
    (`impactGlow`, one radial falloff per hit in `uImpacts`, dropped after
    `uImpactLife`). The flash radius `uImpactRadius` is a fixed world size
    (`_IMPACT_RADIUS_M`) converted to the geometry's local units, so a hit
    leaves the same mark on any bubble; the pattern and death scales instead
    follow the bubble's size.
  - **Behind a cloud.** The clouds write no depth, and the bubble (depth
    write off, bin `fixed` 60) is drawn after them: it includes WorldBuilder's
    `cloud_cover.glsl` and scales its alpha by `1 - cloudCoverBefore(...)` at
    its distance from the eye, so a cloud in front hides it (a thin one in
    part) and one behind stays behind. The scene tracks the bubble
    (`Scene.track_translucent`, WorldBuilder's `World.track_translucent`),
    which sets its inputs every frame; `no_cover` gives it inputs with no
    cloud until then, and the rear-view mirror and the sea's reflection draw
    it without cover (the clouds are marched for the main view).
  - **Death/appearance animation** — "fluid retracting into random points" —
    is a per-fragment mask over the living look, driven by `uDeath`, which
    Python ramps 0 → 1 to die or 1 → 0 to reappear (no mesh changes). Material
    renders only within a shrinking radius of its nearest `uSinks` point
    (`nearestSink`), so it drains into the sinks. Animated noise (`isoNoise`)
    breaks the boundary into irregular blobs, and a `bead` highlight rides the
    edge like a liquid meniscus. Python only drives `uDeath` and the sinks;
    every visual detail of the collapse lives here.

## Explosion particle shaders

Driven by `_FireSmokeBuffer` in
[`fx/fire_smoke_fx.py`](../../src/space_flight/fx/fire_smoke_fx.py), on the
GPU particle system of [`fx/__init__.py`](../../src/space_flight/fx/__init__.py)
(see [fx.md](fx.md)). One pair shared by the fire and smoke buffers, which
differ only by atlas and the `uFadein` uniform:

- **[`explosion.vert`](../../src/space_flight/datafiles/shaders/explosion.vert)**
  rebuilds each billboard from its spawn-time vertex columns (`velocity`,
  `size`, `spin`, `spawn_time`, `lifetime`, `tile_rect`): age from
  `uTime - spawn_time`, linear motion, growth from 30 % to 100 % of `size`,
  spin, billboarding along `uCamRight`/`uCamUp`, and alpha =
  fade-out × fade-in (over the first `uFadein` of life) × alive.
- **[`explosion.frag`](../../src/space_flight/datafiles/shaders/explosion.frag)**
  samples the atlas tile whose UV rect arrives as `vTileRect` (no uniform
  array or dynamic indexing) and multiplies by the vertex alpha, discarding
  invisible fragments first.

## Spark particle shaders

Driven by `SparkPool` in
[`fx/spark_fx.py`](../../src/space_flight/fx/spark_fx.py) (see [fx.md](fx.md)).
One pair shared by every preset:

- **[`spark.vert`](../../src/space_flight/datafiles/shaders/spark.vert)**
  rebuilds each spark from its vertex columns (`velocity`, `size`,
  `spawn_time`, `lifetime`, `gravity`, `spark_color`) on a **ballistic** path
  (linear velocity plus per-particle downward `gravity`), shrinking with age
  and fading quadratically. Colour and gravity are per particle so presets
  stay independent in one buffer.
- **[`spark.frag`](../../src/space_flight/datafiles/shaders/spark.frag)**
  discards outside an SDF circle and builds the shape from a soft glow plus a
  hard core; the `spark.png` alpha can only add to that procedural floor, so a
  flat texture still reads. Tinted by the per-spark `vColor`, additively
  blended.

## Speed dust shaders

Driven by `SpeedDustCloud` in
[`fx/speed_dust_cloud.py`](../../src/space_flight/fx/speed_dust_cloud.py) (see
[fx.md](fx.md)).

- **[`speed_dust.vert`](../../src/space_flight/datafiles/shaders/speed_dust.vert)**
  places each mote from the distance flown (`uTravel`, kept modulo a whole
  number of depths), in the dust's frame (the ship's):
  - it moves back from where it started (`p3d_Vertex`) until it is behind
    the ship;
  - then it comes back `uDepth` ahead, at a new place across within
    `uSpread`, from a hash of its `seed` and its lap;
  - its quad faces the eye: the `corner` offset (times its `size`) is added
    in view space.
- **[`speed_dust.frag`](../../src/space_flight/datafiles/shaders/speed_dust.frag)**
  draws the mote's sprite (`p3d_Texture0`) under the dust's colour scale (its
  opacity grows with speed).

## Laser bolt shaders

Driven by `LaserShot` in
[`weapons/laser_cannon.py`](../../src/space_flight/weapons/laser_cannon.py) (see
[actors.md](actors.md)). Each bolt is one camera-facing quad that the
fragment shader turns into an *analytic capsule impostor*: no mesh, so it
reads as a glowing tube from any angle, including straight down its axis (the
player firing forward), where it is a bright disc rather than a flat sliver.

- **[`laser.vert`](../../src/space_flight/datafiles/shaders/laser.vert)**
  billboards the card in the projectile node's **model space**:
  `LaserShot._build_visual` orients the node's local +Z along the bolt once at
  spawn (where the swept collision segment also lives) and the `Munition` base
  in [`weapons/__init__.py`](../../src/space_flight/weapons/__init__.py) only
  translates it, so the core is the fixed segment `[uA, uB]` along local Z.
  The eye is column 3 of `p3d_ViewMatrixInverse` — the position of whichever
  camera draws the pass — so bolts are right in the main view, mirror and
  ocean reflection with no per-frame CPU work. (Column 3 is unambiguous in any
  axis convention; the basis columns are deliberately avoided.)
- **[`laser.frag`](../../src/space_flight/datafiles/shaders/laser.frag)** casts
  a ray from the eye through each pixel and takes its distance to the core
  segment: a white-hot core plus a soft `uColor` halo. Blending is additive
  with depth write off; it writes `gl_FragDepth` at the ray point nearest the
  core, so opaque geometry occludes bolts while bolts never occlude each other
  or translucent geometry.

## Behind the clouds

The world's clouds write no depth, and every translucent effect drawn in the
world (the shield bubbles, fire and smoke `explosion.frag`, `spark.frag`,
`laser.frag`, `speed_dust.frag`) is drawn after them with depth write off: on
its own it would be laid over a cloud in front of it. Each includes
WorldBuilder's `cloud_cover.glsl` (`load_glsl_shader` puts its folder on Panda's
model path) and fades by `cloudCoverBefore(gl_FragCoord.xy, distance)`, the
opacity of the cloud between the eye and the fragment: the alpha for the
straight-alpha and alpha-weighted additive ones, the colour for the laser's
`ONE, ONE` glow. Their nodes are tracked by the scene's world
(`Scene.track_translucent`: the fire, smoke and spark pools in
`SceneWorld.build_upfront`, the shields, laser bolts and speed dust as they are
made), and get no-cloud inputs (`no_cover`) until then. The rear-view mirror
draws them without cover (`World.cover_off_in`). The ordnance spheres are
fixed-function and not covered.

## Cockpit damage overlay shaders

Driven by `CockpitFX` in
[`fx/cockpit_fx.py`](../../src/space_flight/fx/cockpit_fx.py) (see
[fx.md](fx.md)) on a fullscreen render2d card.
[`cockpit_overlay.vert`](../../src/space_flight/datafiles/shaders/cockpit_overlay.vert)
is a UV passthrough;
[`cockpit_overlay.frag`](../../src/space_flight/datafiles/shaders/cockpit_overlay.frag)
combines a red vignette rising from the screen edges (`uVignetteColor`,
`uVignetteStrength`) and a directional hit flash (`uFlashColor`, `uFlashDir`,
`uFlashStrength`) that blooms on the side the shot came from plus a faint
full-screen wash. The output is alpha-blended over the scene.

## Where things live

All shaders sit directly in
[`src/space_flight/datafiles/shaders/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/datafiles/shaders/),
named after the effect; each is loaded by the Python module named in its
section.
