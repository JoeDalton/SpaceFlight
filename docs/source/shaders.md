# Shaders

[`src/space_flight/datafiles/shaders/`](../../src/space_flight/datafiles/shaders/)
holds the GLSL the game loads from disk (as opposed to shaders baked into
imported models). GLSL isn't covered by the docstring-generated
[code reference](apidocs/index.rst), so this page says what each shader does
and which Python module compiles and drives it. The volumetric cloud field's
`cloud.vert`/`cloud.frag`, loaded by
[`scenes/cloud/field.py`](../../src/space_flight/scenes/cloud/field.py), are
covered in [scenes.md](scenes.md).

## Mental model

- Every shader is `#version 140` GLSL (the cloud shaders are `#version 330`),
  loaded with `Shader.load` and fed only by uniforms, textures and vertex
  columns from Python — nothing persists on the shader side between frames.
- `ocean.vert`, `ocean.frag` and `shield.frag` each carry their own copy of a
  small value-noise kit (`hash`/`smoothNoise` plus `fbmNoise`, or a variant
  `fbm` in the shield). The two ocean copies must stay identical, because the
  geometric swell and the shading normal must match.
- Shaders that sample an offscreen render target correct for Panda3D padding
  it up to a power of two: the composite samples only the `texScale` fraction
  of the scene texture, and the ocean scales its reflection lookup by
  `uReflUVScale`. (The hyperspace shaders work from
  `gl_FragCoord`/`iResolution` on plain render2d cards and don't need this.)
- **Render space is not world space.** The render origin stays on the player
  (see [the floating render origin](game.md#the-floating-render-origin)), so
  `p3d_ModelMatrix`, `p3d_ViewMatrix` and `p3d_ViewProjectionMatrix` are
  relative to a frame that moves every frame. A shader must never combine them
  with a position Python measured relative to `game.root_node`. The shaders
  here stay consistent in one of three ways:
  - **Their own world matrix.** `ocean.vert` takes `uModelMatrix`, the plane's
    matrix relative to the ocean's base node, so its world position,
    `iCameraPos` and `uReflMVP` share that frame.
  - **One frame on the GPU.** `shield.frag` takes the eye from
    `p3d_ViewMatrixInverse`, in the same render space as its
    `p3d_ModelMatrix` position. `laser.vert` works in model space.
  - **World geometry under `root_node`.** `cloud.vert`, `spark.vert` and
    `explosion.vert` place vertices in world coordinates and project them with
    `p3d_ModelViewProjectionMatrix`, whose model part carries the offset.

## Hyperspace loading-screen shaders

Driven by
[`game/hyperspace_loading_state.py`](../../src/space_flight/game/hyperspace_loading_state.py)
(see [game.md](game.md)): one fullscreen fragment shader per phase of the
jump, sharing the position-only passthrough
[`hyperspace.vert`](../../src/space_flight/datafiles/shaders/hyperspace.vert).

- **[`hyperspace_into.frag`](../../src/space_flight/datafiles/shaders/hyperspace_into.frag)**
  (entering hyperspace): star streaks converging into a central lens flare
  that grows and whites out the screen. Streaks are procedural per-slice line
  segments (`sdLine`) with offset/speed/length seeded per slice (`rand`). The
  animation length is the `iIntoDuration` uniform, fed from Python's
  `INTO_DURATION` so the whiteout always matches the Python phase. Time is
  **clamped**, not wrapped, so the white frame holds for the cross-fade into
  the tunnel instead of restarting the trails.
- **[`hyperspace_inside.frag`](../../src/space_flight/datafiles/shaders/hyperspace_inside.frag)**:
  the seamlessly looping warp tunnel held while the level builds. A 3D
  simplex-noise fBm (`loopFbm`) is sampled around a circle in depth-phase
  space instead of tiled with `mod()`, so every octave is periodic over the
  loop period `T_LOOP` and there is no seam.
- **[`hyperspace_outof.frag`](../../src/space_flight/datafiles/shaders/hyperspace_outof.frag)**
  (dropping out): the reverse of `hyperspace_into.frag` — streaks collapsing
  into the revealed level, fading from an initial whiteout. From 35% of its
  loop the black background turns transparent, so the live scene shows
  through while the streaks still play: alpha is the larger of that
  background opacity and the streak brightness, and the colour is divided
  by alpha so the streaks keep their brightness over the scene. The 35% must
  match Python's `REVEAL_START`, which starts the simulation at that moment.

`into` and `outof` are adapted from one ShaderToy source and `inside` from
another (MIT); the header comments carry the credits.

## Render-scale / anti-aliasing pipeline shaders

Driven by
[`GraphicsManager.begin_scene_render`](../../src/space_flight/global_architecture/graphics_manager.py)
(see [global_architecture.md](global_architecture.md)) to composite the
(possibly downscaled) offscreen 3D render onto the window. Both fragment
shaders share the fullscreen-quad passthrough
[`composite.vert`](../../src/space_flight/datafiles/shaders/composite.vert).

- **[`blit.frag`](../../src/space_flight/datafiles/shaders/blit.frag)** (FXAA
  off) samples the scene texture, scaled by `texScale`, and lets GPU texture
  filtering do any upscaling.
- **[`fxaa.frag`](../../src/space_flight/datafiles/shaders/fxaa.frag)** (FXAA
  on) is a simplified port of Timothy Lottes' FXAA3: it estimates an edge
  direction from the luma of the four diagonal neighbours, blends two taps
  along it (`rgbA`) and two more further out (`rgbB`), and outputs `rgbB`
  unless its luma leaves the local range (`lumaMin`/`lumaMax`), in which case
  it falls back to `rgbA`.

## Ocean shaders

Driven by [`scenes/ocean.py`](../../src/space_flight/scenes/ocean.py) (see
[scenes.md](scenes.md)):

- **[`ocean.vert`](../../src/space_flight/datafiles/shaders/ocean.vert)** is a
  passthrough plus the optional `uGeometricSwell` mode (which `SceneOcean`
  enables): it displaces vertices vertically by the same `swellField` the
  fragment shader samples, tapered to zero near the dense grid's edge so the
  displaced centre joins the flat border. Its world position comes from
  `uModelMatrix` (refreshed by `Ocean.update` after the plane is re-centred),
  not `p3d_ModelMatrix`, so the waves stay anchored to the world rather than
  to the moving render origin.
- **[`ocean.frag`](../../src/space_flight/datafiles/shaders/ocean.frag)**:
  - **Wave field.** `getwaves`/`waveGradient` accumulate Gerstner-like octaves
    (`wavedx`) along per-iteration directions `iWaveDirs`, precomputed in
    Python by `compute_wave_dirs`. `waveGradient` computes the slope
    analytically in one pass instead of a three-sample finite difference.
  - **Level of detail.** `detailAngle` (view-ray elevation, so the look is
    consistent at any altitude) and `distFade` (camera distance) fade wave
    detail toward a flat mirror. `normalIter` decays exponentially with
    distance (`uWaveFadeK2`); `warpIter` and the warp strength follow
    `lodFactor = detailAngle × distFade`. Below a `detailAngle` of 0.01 the
    small waves are skipped.
  - **Swell + frequency modulation.** A large-scale `swellField` (the product
    of two drifting value-noise layers, so it changes shape rather than
    scrolling) tilts the normal with no distance fade, and also shifts the
    small-wave phase (`fmPhase`) so the dominant octave's tiling drifts.
  - **Reflection.** The reflection UV is recomputed per fragment from the
    flat (z = 0) surface position: interpolating a vertex clip-space value
    would skew the projective divide per triangle once the swell displaces
    vertices. Sampling at that flat footprint still slides against the
    displaced geometry (see the
    [ocean swell artifact report](../../src/space_flight/scenes/OCEAN_SWELL_ARTIFACT_REPORT.md)).
    The ripple-perturbed UV is clamped to the rendered region
    (`uReflUVScale`) so it never samples the power-of-two padding.
  - **Output.** The fresnel blend of reflection and water colour is
    ACES-tonemapped (`aces_tonemap`), then hazed toward `uHazeColor` over
    `uHazeDistance` — after the tonemap, as the cloud field does, so sea and
    sky meet cleanly at the horizon.
  - **Debug.** `uDebugMode` 1–8 visualise intermediate quantities (0 is normal
    rendering): normal, reflection UV, fresnel, world grid, reflection-UV
    clamp, raw reflection, pre-tonemap clipping, FM phase.

## Shield shaders

Driven by
[`actors/capital_ship/shield_model.py`](../../src/space_flight/actors/capital_ship/shield_model.py)
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
    `uImpactLife`).
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
[`src/space_flight/datafiles/shaders/`](../../src/space_flight/datafiles/shaders/),
named after the effect; each is loaded by the Python module named in its
section.
