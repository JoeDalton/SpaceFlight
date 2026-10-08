# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

- Better radial menu #93
- Parallelized pytest config #118

### Fixed

- Fixed level 1 waypoints in asteroid #138

### Removed

## [0.1.0] - 2026-10-04

First alpha release.

### Added

#### Flight and combat
- Flight model with airplane-like and pure-spaceship handling, boost and lift-induced drag.
- Energy management: distribute power between engines, lasers and shields, for the player and the bots.
- Laser cannons, missiles and rockets, with shields, hull damage and hit feedback.
- Collision handling between ships, ordnance and asteroids.
- Target selection with filters through a radial menu, and a scan to reveal hidden enemies.
- Death of the player and end-of-level screen.

#### Ships and AI
- Fighters: X-wing, Y-wing, A-wing, Eta-2, TIE fighter, TIE interceptor and TIE bomber.
- Capital ships and transports with destructible subsystems: engines, hangar, shield generators, targeting system, turrets and tractor beams.
- AI pilots with patrol, hunting, evading, escort and formation behaviours, primary targets, collision avoidance and configurable personalities.

#### Levels
- Three missions, including a tutorial, selectable from a level selection menu.
- Mission scripting in Python.
- Scenes with skyboxes, asteroid fields, planets, volumetric clouds and a reflective ocean.
- Hyperspace loading screen while a level initialises.

#### Presentation
- HUD with target indicator, shield and health readouts, waypoints, rear-view mirror and a toggleable FPS counter.
- Cockpit views with head movement following the ship's motion, and cockpit damage effects.
- Visual effects for lasers, explosions, sparks, fire, smoke and speed dust.
- 3D sound effects with Doppler and engine sounds.

#### Settings and input
- Keyboard, gamepad and joystick/HOTAS support, with in-game rebinding and configurable dead zones.
- Graphics settings menu.
- Gameplay difficulty presets (easy, normal, hard, ace) with adjustable auto-aim, aim deviation, damage multipliers and lead indicator.
- Pause menu.

#### Installation and documentation
- Windows install, launch and update scripts in `MS_Windows_install/`.
- Developer documentation built with Sphinx.
