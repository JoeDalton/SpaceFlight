# Capital-ship subsystems

Capital ships are not monolithic health bars: they are built from **subsystems**
— destructible modules bolted onto the hull (engines, a shield generator,
targeting systems, turrets, a tractor beam…). Each is a target in its own right,
so a fight against a capital ship is really a fight against its parts: knock out
its shield generator and the bubble drops; kill its targeting system and its
turrets lose their aim; destroy its turrets and it stops shooting back.

All of the subsystem code lives in
[`src/space_flight/actors/capital_ship/`](../src/space_flight/actors/capital_ship/).
The per-class API (constructor arguments, methods) is generated from the
docstrings in the [code reference](docs/); this page is the guided tour of how
the pieces fit together.

## Mental model

- A **subsystem** is a [`SubSystem`](#the-subsystem-base) — a destructible chunk
  of a ship. It owns its health and a collider, is targetable, and explodes when
  killed. It is *mounted on* a ship and dies with it.
- Some subsystems are **passive** (they just exist and can be shot off — engines,
  hangars). Others are **active** and change the ship's capabilities while alive:
  the shield generator projects a bubble, the targeting system boosts turrets, a
  turret shoots, a tractor beam grabs.
- Active subsystems are deliberately **loosely coupled**. A subsystem never
  reaches "up" to command the ship; instead the ship (or its turrets) *pull* what
  they need each frame and check the subsystem's alive/dead state. So killing a
  subsystem needs no teardown wiring — the capability simply stops being pulled.

## The `SubSystem` base

[`sub_system.py`](../src/space_flight/actors/capital_ship/sub_system.py) defines
the behaviour every subsystem shares:

- **Destructible.** It owns a strength pool (`health` / `max_health`) and
  monitors it every frame. When depleted it plays a death explosion at its last
  location and is cleaned up centrally.
- **Mounted.** Its node hangs off the ship node at a mounting offset.
  `mounted_on` is the ship it is bolted to (used to spare the parent ship from
  its own colliders and to route ram-pushback to the ship). For most subsystems
  `parent` *is* the ship; for the aiming mounts `parent` is the controlling Bot
  and `mounted_on` is passed explicitly.
- **Into-only collider.** A spherical `"subsystem"` collider that is only ever
  *hit* — like terrain it never initiates collisions. Its `owner` tag points
  back at the subsystem so the collision handlers can route a laser hit to
  `take_hit`, and same-vehicle pairs are skipped so a ship never collides with
  its own parts.
- **Targetable.** It registers with the interaction system, so bots and the
  player can lock onto it individually.
- **Dies with its ship.** If the ship it is mounted on is gone, the subsystem
  brings its own health to zero so it is cleaned up on the next frame.

Concrete subsystems subclass `SubSystem` (or `TrackingMount`, which is itself a
`SubSystem`) and add their specific behaviour.

| Subsystem | Class | Base | Role |
|-----------|-------|------|------|
| Engine | `Engine` | `SubSystem` | Placeholder hull module (shoot-off target) |
| Hangar | `Hangar` | `SubSystem` | Placeholder hull module (shoot-off target) |
| Tractor beam mount (stub) | `TractorBeamProjector` | `SubSystem` | Placeholder hull module (see note below) |
| Shield generator | `ShieldGenerator` | `SubSystem` | Projects a protective shield bubble |
| Targeting system | `TargetingSystem` | `SubSystem` | Grants turrets auto-aim + faster fire |
| Tracking mount | `TrackingMount` | `SubSystem` | Base for turrets/tractor beams that swivel to aim |
| Turret | `Turret` | `TrackingMount` | Aims and fires laser cannons |
| Tractor beam | `TractorBeamProjector` | `TrackingMount` | Aims, grabs a prey and reels it in |

## Passive modules: engine, hangar

[`Engine`](../src/space_flight/actors/capital_ship/engine.py) and
[`Hangar`](../src/space_flight/actors/capital_ship/hangar.py) are, for now, bare
`SubSystem`s with no added behaviour: hull modules that exist to be seen,
targeted and shot off. They are the simplest example of the pattern and the
natural place to grow engine/hangar-specific effects later.

## Shield generator & shield

A ship may mount **several**
[`ShieldGenerator`](../src/space_flight/actors/capital_ship/shield_generator.py)s
(or **none**), and they all project **one shared**
[`Shield`](../src/space_flight/actors/capital_ship/shield.py) — the bubble is
built and owned by the ship, not by any single generator. The generators are the
*hardware*; the shield is the *effect*. **No generators means no shield**: the
shield is an effect of the generator hardware, so a ship with none gets no
bubble (a stray `shield` spec on such a ship is ignored, with a warning).

- **Pro-rata perks.** Each generator contributes an equal share of the shield's
  perks. With `initial` generators and `alive` still standing, the fraction
  `alive / initial` scales both the maximum strength and the regeneration rate,
  and the current strength is clamped down to the reduced maximum. So shooting
  off one of three generators leaves the shield at two-thirds strength; the
  effect is recomputed every frame as generators fall.
- **One-way coupling.** The shield polls the generators' alive state to compute
  that fraction; the generators know nothing of the shield, which keeps them
  plain destructible hardware. The shield itself owns `get_shield_level()` (its
  current strength) for the fleet AI's fighting-shape estimate. The ship builds
  both and hands the generator list to the shield.

The shield has **two distinct failure modes**:

- **Disabled** — its own strength pool is depleted by hits (on top of any
  pro-rata reduction). The bubble collapses (the fluid *death* animation) and
  stays *down*: not protecting, hidden, but still alive. After a regeneration
  cooldown it strengthens again and *reappears* (the death animation played in
  reverse), coming back online.
- **Destroyed** — **every** generator (or the whole ship) is destroyed. This is
  the only thing that ends the shield's life for good. It plays the same collapse
  and only *then* reports itself dead, so cleanup is delayed until the animation
  has finished.

Key behaviours:

- **Not functional while animating.** During either the death or the appearance
  animation the shield blocks nothing (it is skipped in the laser/shield
  collision handler); it only protects while fully *up*.
- **Regeneration cooldown.** Regeneration does not start until a cooldown has
  elapsed since the last absorbed hit (10 s), and that cooldown is **doubled**
  (20 s) while the shield is down — a collapsed shield takes longer to reform.
- **Directional-agnostic absorption.** A laser fired from *outside* is absorbed;
  one fired from *inside* passes straight through, so a ship sheltering in its
  own bubble can still shoot out.
- **Health-driven look.** The bubble's tint tracks its strength: light blue at
  full health, through violet, to pink-violet when empty. Laser hits leave a
  localised flash where they strike.

The **visuals are separated from the logic**: everything about the bubble's
appearance — the mesh (sphere / capsule / shared model), the animated GLSL
shader and all its uniforms, the impact flashes and the fluid retraction — lives
in [`ShieldModel`](../src/space_flight/actors/capital_ship/shield_model.py), which
also carries the `make_capsule` mesh builder used by tubular shields. The
`Shield` class keeps only the game logic (strength, collision, lifecycle, the
death/appearance state machine) and drives the model each frame. The collider is
built from the same resolved dimensions the model exposes, so the visible bubble
and the thing lasers hit always coincide. The shader lives in
[`datafiles/shaders/shield.frag`](../src/space_flight/datafiles/shaders/shield.frag).

### A note on cleanup timing

Because a destroyed shield must *finish its collapse* before it vanishes, it
keeps reporting positive health to the central death handler until the animation
completes. And because the shield's node hangs off the ship node (which is
removed when the ship dies), the shield detects the doom one frame early — the
moment the generator's or ship's health hits zero — and reparents itself to the
world root so it survives the ship node's removal and can play out.

## Targeting system

The [`TargetingSystem`](../src/space_flight/actors/capital_ship/targeting_system.py)
is fire control: while alive it grants **every turret on the same ship** two
boosts — auto-aim (shots lead the target instead of flying straight down the
barrel) and a faster rate of fire. The coupling is one-way: the targeting system
only exposes its multiplier and its alive/dead state, and the turrets *pull*
those each frame. Destroy it and the boosts vanish on the next frame — turrets
revert to unassisted fire at their base rate. This is the clearest example of the
loose-coupling principle above.

## Tracking mounts: turrets & the tractor beam

A [`TrackingMount`](../src/space_flight/actors/capital_ship/tracking_mount.py) is a
subsystem that **swivels in yaw and pitch to track a target**. It is the shared
base for the two things a capital ship aims: the laser turret and the tractor
beam. Everything about *aiming* lives in the mount — the mounting frame, the
yaw/pitch state and rate limits, the swivelling model, and the "remarkable
directions" the AI reads — while what the mount *does* once aimed is deferred to
an `_operate()` hook that subclasses override.

Unlike other subsystems, a tracking mount is driven by a **Bot**: the Bot is its
`parent` (controller) while `mounted_on` is the ship it sits on. Its generic AI
picks a prey and steers the barrel, publishing a lead solution (aim direction +
target distance) that `_operate()` acts on. Its swivelling geometry is the
[`TurretModel`](../src/space_flight/actors/capital_ship/turret_model.py) (the
presentation half, analogous to `ShieldModel`).

- **[`Turret`](../src/space_flight/actors/capital_ship/turret.py)** adds laser
  cannons and the fire decision: it fires when its barrel is aligned with where
  the prey is heading and the prey is in range. A living targeting system on the
  ship upgrades it with auto-aim and a faster fire rate (pulled each frame).
- **[`TractorBeamProjector`](../src/space_flight/actors/capital_ship/tractor_beam.py)**
  grabs a prey and reels it in instead of shooting it. When a prey enters its
  grab cone within range it locks on and applies two forces each frame: a drag
  opposing the prey's velocity relative to the projector's ship, and a light
  attraction pulling it in. The **cone acquires, range retains**: once locked it
  holds the prey until the grab times out, the prey wrenches free by exceeding a
  relative speed, the prey leaves range, or the prey is gone — after which a
  cooldown prevents an instant re-grab.

> **Two `TractorBeamProjector`s.** There are currently two classes named
> `TractorBeamProjector`: the functional tracking-mount one above
> ([`tractor_beam.py`](../src/space_flight/actors/capital_ship/tractor_beam.py)),
> and a bare placeholder `SubSystem`
> ([`tractor_beam_projector.py`](../src/space_flight/actors/capital_ship/tractor_beam_projector.py))
> kept as a hull-module stub. Prefer the tracking-mount version for real tractor
> behaviour; the stub is a target-only placeholder.

## Where things live

Every subsystem module now sits under
[`src/space_flight/actors/capital_ship/`](../src/space_flight/actors/capital_ship/),
including the turret and tractor-beam mounts and their `TurretModel` presentation
(previously under `actors/`), so the whole family lives together. The
auto-generated [code reference](docs/) has the full per-class API.
