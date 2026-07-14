"""
cloud.py — A cloud's data: procedural generation, CPU self-shadow shading, and
the packaged sprite atlas.

This module owns the data side of a cloud (no GPU): it scatters a procedural set
of billboard particles for a given cloud type (build_cloud_particles), bakes
a per-particle RGB colour by a one-off CPU ray-cast self-shadow trace
(_shade_particles), and packs distinct shaded cloud *shapes* into reusable
render-ready templates (build_templates).  The GPU side — geometry, shaders,
sorting, wind/recycling — lives in field.py.

Each particle is a dict: pos (metres), radius, density, albedo.
CloudType selects a shape preset from DEFAULTS (overridable per call).
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path

import numpy as np

from space_flight import CACHE_PATH, LOGGER
from space_flight.fx import load_atlas

# Darkest a fully self-shadowed particle is allowed to get (0 = black interiors,
# 1 = no shadowing); keeps cloud cores readable rather than crushed to ambient.
MIN_BRIGHTNESS = 0.15

# ── Template disk cache ─────────────────────────────────────────────────────────
# Cloud templates are deterministic in their inputs (seeded RNG + lighting), and
# generating the full default field is ~0.6s of pure CPU. So we cache the built
# templates to disk keyed by every input that affects them; the first launch on a
# machine generates + saves, and every later launch loads them instantly.
#
# Bump _TEMPLATE_CACHE_VERSION whenever the generation/shading *code* changes in a
# way that alters output (the key only covers parameters, not the algorithm).
_TEMPLATE_CACHE_VERSION = 1
_TEMPLATE_CACHE_DIR = CACHE_PATH / "cloud_templates"


# ── Cloud type ──────────────────────────────────────────────────────────────────


class CloudType(Enum):
    CUMULUS = "cumulus"
    STRATUS = "stratus"
    CIRRUS = "cirrus"
    CUMULONIMBUS = "cumulonimbus"


# ── Per-type shape & optical presets ────────────────────────────────────────────
# Each preset feeds build_cloud_particles.  Lengths are metres; *_frac/_thresh are
# in [0,1]; densities/albedos are the optical ranges sampled per particle.
DEFAULTS = {
    CloudType.CUMULUS: dict(
        base_w=400,
        base_d=400,
        cloud_h=300,
        n_towers=4,
        tower_radius=0.30,
        horiz_falloff=1.2,
        n_candidates=1000,
        n_particles=450,
        n_worley_feat=20,
        worley_thresh=0.55,
        p_radius_min=30,
        p_radius_max=70,
        p_radius_var=0.3,
        density_min=0.4,
        density_max=0.9,
        albedo_min=0.7,
        albedo_max=1.0,
        cloud_base_z=1200,
    ),
    CloudType.STRATUS: dict(
        base_w=2000,
        base_d=2000,
        cloud_h=120,
        n_towers=0,
        tower_radius=0.0,
        horiz_falloff=0.15,
        n_candidates=1000,
        n_particles=300,
        n_worley_feat=12,
        worley_thresh=0.80,
        p_radius_min=80,
        p_radius_max=160,
        p_radius_var=0.1,
        density_min=0.5,
        density_max=0.85,
        albedo_min=0.45,
        albedo_max=0.70,
        cloud_base_z=600,
    ),
    CloudType.CIRRUS: dict(
        base_w=2000,
        base_d=400,
        cloud_h=80,
        n_towers=0,
        tower_radius=0.0,
        horiz_falloff=0.5,
        n_candidates=1000,
        n_particles=200,
        n_worley_feat=30,
        worley_thresh=0.35,
        p_radius_min=20,
        p_radius_max=50,
        p_radius_var=0.15,
        density_min=0.1,
        density_max=0.4,
        albedo_min=0.85,
        albedo_max=1.0,
        cloud_base_z=8000,
        fiber_warp_amp=0.35,
        fiber_warp_freq=0.004,
    ),
    CloudType.CUMULONIMBUS: dict(
        base_w=800,
        base_d=800,
        cloud_h=1200,
        n_towers=6,
        tower_radius=0.25,
        horiz_falloff=1.0,
        n_candidates=1500,
        n_particles=600,
        n_worley_feat=30,
        worley_thresh=0.50,
        p_radius_min=50,
        p_radius_max=120,
        p_radius_var=0.4,
        density_min=0.5,
        density_max=1.0,
        albedo_min=0.3,
        albedo_max=0.85,
        cloud_base_z=800,
        anvil_start=0.72,
        anvil_flare=2.0,
        anvil_downwind=0.6,
    ),
}


# ── Procedural noise ──────────────────────────────────────────────────────────


def _worley_noise(points: np.ndarray, n_features: int, seed: int) -> np.ndarray:
    """Worley (cellular) noise: distance from each point to its nearest random
    feature, normalised to [0,1].  Used to carve lumpy detail into the cloud.

    :param points: (P,3) sample positions
    :param n_features: number of random feature points
    :param seed: RNG seed
    :returns: (P,) normalised nearest-feature distance per point
    """
    rng = np.random.default_rng(seed)
    features = rng.uniform(points.min(axis=0), points.max(axis=0), (n_features, 3))
    nearest_dist = np.array(
        [np.min(np.linalg.norm(features - p, axis=1)) for p in points]
    )
    return nearest_dist / nearest_dist.max()


def _smooth_noise_1d(coords: np.ndarray, seed: int = 0) -> np.ndarray:
    """Smooth 1-D noise as a sum of 4 random sinusoids, in roughly [-1,1].

    :param coords: (P,) input coordinates
    :param seed: RNG seed
    :returns: (P,) smooth noise values
    """
    rng = np.random.default_rng(seed)
    phases = rng.uniform(0, 2 * np.pi, 4)
    freqs = rng.uniform(0.7, 1.3, 4)
    return sum(np.sin(f * coords + p) for f, p in zip(freqs, phases)) / 4.0


# ── Per-type shape helpers ────────────────────────────────────────────────────


def _envelope_radius(height_frac: float, cloud_type: CloudType, cfg: dict) -> float:
    """Horizontal radius multiplier of the cloud envelope at a given height.

    Shapes the silhouette per type: a rounded cumulus dome, a flat stratus slab,
    a tapered cirrus sheet, or a cumulonimbus that flares into an anvil near the
    top.  height_frac is the normalised height z / cloud_h in [0,1].

    :param height_frac: normalised height within the cloud, 0 (base) … 1 (top)
    :param cloud_type: cloud type being shaped
    :param cfg: the resolved preset dict (for type-specific params)
    :returns: radius multiplier in [0, ~anvil_flare]
    """
    if cloud_type == CloudType.CUMULUS:
        if height_frac < 0.10:
            return 0.55 + 0.45 * (height_frac / 0.10)
        elif height_frac < 0.65:
            return 1.0 + 0.08 * np.sin(np.pi * (height_frac - 0.10) / 0.55)
        else:
            return max(0.0, 1.0 - ((height_frac - 0.65) / 0.35) ** 1.2)
    elif cloud_type == CloudType.STRATUS:
        if height_frac < 0.15:
            return 0.6 + 0.4 * (height_frac / 0.15)
        elif height_frac < 0.85:
            return 1.0
        else:
            return max(0.0, 1.0 - ((height_frac - 0.85) / 0.15) ** 1.5)
    elif cloud_type == CloudType.CIRRUS:
        if height_frac < 0.20:
            return (height_frac / 0.20) ** 0.5
        elif height_frac < 0.80:
            return 1.0
        else:
            return max(0.0, ((1.0 - height_frac) / 0.20) ** 0.5)
    elif cloud_type == CloudType.CUMULONIMBUS:
        anvil_start = cfg.get("anvil_start", 0.72)
        anvil_flare = cfg.get("anvil_flare", 2.0)
        if height_frac < 0.10:
            return 0.55 + 0.45 * (height_frac / 0.10)
        elif height_frac < anvil_start:
            return 1.0 + 0.05 * np.sin(
                np.pi * (height_frac - 0.10) / (anvil_start - 0.10)
            )
        else:  # flare outward above anvil_start
            anvil_frac = (height_frac - anvil_start) / (1.0 - anvil_start)
            return 1.0 + (anvil_flare - 1.0) * anvil_frac**0.5
    return 1.0


def _worley_accept(worley_vals, height_fracs, cloud_type, cfg):
    """Per-candidate keep-probability from the Worley field, by type.

    Carves the cloud's texture: low Worley values (near a feature) are kept
    solidly, higher values are thinned out — with type-specific tweaks (e.g. the
    cumulus dome and the cumulonimbus anvil are treated differently).

    :param worley_vals: (P,) normalised Worley value per candidate
    :param height_fracs: (P,) normalised height per candidate
    :param cloud_type: cloud type being carved
    :param cfg: the resolved preset dict
    :returns: (P,) keep-probability in [0,1]
    """
    thresh = cfg["worley_thresh"]
    if cloud_type == CloudType.CUMULUS:
        in_dome = height_fracs > 0.60
        return np.where(
            in_dome,
            np.where(
                worley_vals <= thresh,
                1.00,
                np.where(worley_vals <= thresh + 0.25, 0.25, 0.05),
            ),
            np.where(worley_vals <= thresh + 0.30, 1.00, 0.40),
        )
    elif cloud_type == CloudType.STRATUS:
        return np.where(worley_vals <= thresh, 1.0, 0.55)
    elif cloud_type == CloudType.CIRRUS:
        return np.where(
            worley_vals <= thresh,
            1.00,
            np.where(worley_vals <= thresh + 0.15, 0.10, 0.00),
        )
    elif cloud_type == CloudType.CUMULONIMBUS:
        anvil_start = cfg.get("anvil_start", 0.72)
        in_anvil = height_fracs >= anvil_start
        return np.where(
            in_anvil,
            np.where(worley_vals <= thresh + 0.15, 0.55, 0.10),
            np.where(
                worley_vals <= thresh,
                1.00,
                np.where(worley_vals <= thresh + 0.20, 0.30, 0.05),
            ),
        )
    return np.ones(len(worley_vals))


def _apply_cirrus_warp(points, cfg, seed):
    """Shear cirrus candidates along Y by a smooth 1-D noise of X, to fake the
    wind-stretched fibrous streaks cirrus is made of.

    :param points: (P,3) candidate positions
    :param cfg: the resolved preset dict (for warp amplitude/frequency)
    :param seed: RNG seed (offset so it differs from the placement seed)
    :returns: (P,3) warped copy of points
    """
    amplitude = cfg.get("fiber_warp_amp", 0.35) * cfg["base_w"]
    frequency = cfg.get("fiber_warp_freq", 0.004)
    y_warp = amplitude * _smooth_noise_1d(points[:, 0] * frequency, seed=seed + 99)
    warped = points.copy()
    warped[:, 1] += y_warp
    return warped


# ── Particle generator ────────────────────────────────────────────────────────


def build_cloud_particles(
    cloud_type: CloudType, seed: int = 42, **overrides
) -> list[dict]:
    """Procedurally place billboard particles for one cloud and assign optical
    properties.  Pure CPU, run once at construction.

    Candidates are rejection-sampled inside the type's envelope (denser toward
    convective tower centres and the cloud core), carved by a Worley field, then
    sub-sampled to n_particles.

    :param cloud_type: which DEFAULTS preset to draw shape/optical params from
    :param seed: RNG seed (distinct seeds give distinct cloud shapes)
    :param overrides: per-key overrides of the type's DEFAULTS
    :returns: list of particle dicts with pos, radius, density, albedo
    """
    cfg = {**DEFAULTS[cloud_type], **overrides}
    base_w, base_d, cloud_h = cfg["base_w"], cfg["base_d"], cfg["cloud_h"]
    n_towers, horiz_falloff = cfg["n_towers"], cfg["horiz_falloff"]
    n_candidates, n_particles = cfg["n_candidates"], cfg["n_particles"]
    rng = np.random.default_rng(seed)

    # Convective tower centres (cumulus/cumulonimbus): candidates cluster around
    # these to give the cloud its bubbly, multi-lobed look.
    tower_centres = []
    if n_towers > 0:
        for _ in range(n_towers):
            angle = rng.uniform(0, 2 * np.pi)
            dist = rng.uniform(0.0, 0.45)
            tower_centres.append(
                (np.cos(angle) * dist * base_w / 2, np.sin(angle) * dist * base_d / 2)
            )
        tower_radius_sq = (cfg["tower_radius"] * base_w / 2) ** 2

    # Rejection-sample candidate positions until we have enough.
    candidates: list[tuple] = []
    while len(candidates) < n_candidates:
        batch = rng.uniform(
            [-base_w / 2, -base_d / 2, 0],
            [base_w / 2, base_d / 2, cloud_h],
            (n_candidates * 2, 3),
        )
        if cloud_type == CloudType.CIRRUS:
            batch = _apply_cirrus_warp(batch, cfg, seed)

        for x, y, z in batch:
            height_frac = z / cloud_h
            envelope = _envelope_radius(height_frac, cloud_type, cfg)
            if envelope <= 0:
                continue

            # Effective horizontal radii at this height; cumulonimbus stretches
            # downwind (+x) above the anvil.
            if cloud_type == CloudType.CUMULONIMBUS:
                anvil_start = cfg.get("anvil_start", 0.72)
                anvil_downwind = cfg.get("anvil_downwind", 0.6)
                if height_frac >= anvil_start and x > 0:
                    stretch = 1.0 + anvil_downwind * (
                        (height_frac - anvil_start) / (1.0 - anvil_start)
                    )
                    radius_x = base_w / 2 * envelope * stretch
                else:
                    radius_x = base_w / 2 * envelope
                radius_y = base_d / 2 * envelope
            else:
                radius_x = base_w / 2 * envelope
                radius_y = base_d / 2 * envelope

            # Inside the elliptical envelope? (normalised radial distance squared)
            norm_x_sq = (x / radius_x) ** 2
            norm_y_sq = (y / radius_y) ** 2
            if norm_x_sq + norm_y_sq > 1.0:
                continue

            # Keep-probability: denser toward the core (horizontally) and the
            # mid-height (vertically), biased toward tower centres if present.
            core_density = np.exp(-horiz_falloff * (norm_x_sq + norm_y_sq))
            vertical_density = np.sin(np.pi * height_frac) ** 0.6
            if n_towers > 0:
                nearest_tower_sq = min(
                    (x - tx) ** 2 + (y - ty) ** 2 for tx, ty in tower_centres
                )
                tower_density = np.exp(-nearest_tower_sq / (2 * tower_radius_sq))
                keep_prob = (
                    0.6 * tower_density + 0.4 * core_density
                ) * vertical_density
            else:
                keep_prob = core_density * vertical_density
            if cloud_type == CloudType.STRATUS:
                keep_prob = core_density * (1.0 - 0.4 * height_frac)
            if cloud_type == CloudType.CIRRUS:
                keep_prob = core_density**0.4

            if rng.random() < keep_prob:
                candidates.append((x, y, z))
                if len(candidates) >= n_candidates:
                    break

    candidate_pos = np.array(candidates[:n_candidates])
    worley_vals = _worley_noise(
        candidate_pos, n_features=cfg["n_worley_feat"], seed=seed
    )
    height_fracs = candidate_pos[:, 2] / cloud_h

    # Carve detail with the Worley field, then trim to the requested count.
    accept_prob = _worley_accept(worley_vals, height_fracs, cloud_type, cfg)
    kept = candidate_pos[rng.random(len(candidate_pos)) < accept_prob]
    if len(kept) > n_particles:
        kept = kept[rng.choice(len(kept), n_particles, replace=False)]

    base_altitude = cfg["cloud_base_z"]
    particles = []
    for x, y, z in kept:
        height_frac = z / cloud_h
        # Particles swell toward mid-height (the cloud's bulkiest part).
        radius = rng.uniform(cfg["p_radius_min"], cfg["p_radius_max"]) * (
            1.0 + cfg["p_radius_var"] * np.sin(np.pi * height_frac)
        )
        particles.append(
            {
                "pos": (float(x), float(y), float(z + base_altitude)),
                "radius": float(radius),
                "density": float(rng.uniform(cfg["density_min"], cfg["density_max"])),
                "albedo": float(rng.uniform(cfg["albedo_min"], cfg["albedo_max"])),
            }
        )
    return particles


# ── Self-shadow shading ───────────────────────────────────────────────────────


def _shade_particles(
    particles: list[dict],
    sun_color: np.ndarray,
    ambient_color: np.ndarray,
    sun_dir: np.ndarray,
) -> np.ndarray:
    """Bake a per-particle RGB colour by a one-off CPU ray-cast self-shadow trace.

    For each particle, accumulates optical depth from the particles between it and
    the sun, converts that to a brightness, and blends sun vs. ambient colour.

    Sign convention: sun_dir points FROM the scene TOWARD the sun.  The
    ordering (sun-side particles first) and the occluder test (proj > 0,
    selecting occluders on the sunward side) both assume that; passing the light's
    travel direction (-sun_dir) would invert the trace (lit shadow side, dark
    sun side).

    :param particles: particle dicts from build_cloud_particles
    :param sun_color: RGB of direct sunlight
    :param ambient_color: RGB of the ambient/sky fill
    :param sun_dir: vector FROM the scene TOWARD the sun (need not be unit)
    :returns: (N,3) per-particle RGB, clipped to [0,1]
    """
    sun_dir = sun_dir / np.linalg.norm(sun_dir)
    pos = np.array([p["pos"] for p in particles])
    densities = np.array([p["density"] for p in particles])
    radii = np.array([p["radius"] for p in particles])
    albedo = np.array([p["albedo"] for p in particles])

    # Process particles from the sun side inward, so a particle's occluders have
    # already had their own transmittance resolved.
    sun_side_order = np.argsort(pos @ (-sun_dir))
    transmittance = np.ones(len(particles))
    for rank, i in enumerate(sun_side_order):
        if rank == 0:
            continue
        sunward = sun_side_order[:rank]  # particles nearer the sun
        to_sunward = pos[sunward] - pos[i]
        proj = to_sunward @ sun_dir  # distance along the sun axis
        perp_sq = np.maximum(np.sum(to_sunward**2, axis=1) - proj**2, 0.0)
        hit = (proj > 0) & (perp_sq < radii[sunward] ** 2)
        if not np.any(hit):
            continue
        # Nearest occluder along the ray; attenuate by Beer-Lambert over its chord.
        nearest = np.argmin(np.where(hit, proj, np.inf))
        occluder = sunward[nearest]
        chord = np.sqrt(max(1.0 - perp_sq[nearest] / radii[occluder] ** 2, 0.0))
        transmittance[i] = transmittance[occluder] * np.exp(
            -densities[occluder] * chord
        )

    brightness = transmittance * albedo
    max_brightness = brightness.max()
    if max_brightness > 1e-9:
        brightness /= max_brightness
    brightness = MIN_BRIGHTNESS + (1.0 - MIN_BRIGHTNESS) * brightness  # floor it
    rgb = np.outer(brightness, sun_color) + np.outer(1.0 - brightness, ambient_color)
    return rgb.clip(0, 1)


# ── Render-ready templates ──────────────────────────────────────────────────────


def build_templates(
    n_templates: int,
    atlas_rects: list,
    sun_color: np.ndarray,
    ambient_color: np.ndarray,
    sun_dir,
    cloud_type=CloudType.CUMULUS,
    density_scale: float = 0.7,
    base_seed: int = 0,
    uv_seed: int = 0,
    overrides: dict = None,
) -> list[dict]:
    """Build distinct shaded cloud *shapes* once, ready for the field to scatter.

    This is the expensive step (generation + self-shadow shading), so a few shapes
    are built and reused across many placements.  Each shape is centred at the
    origin, so a placement's world centroid is just its offset.

    A particle's RGB comes from the self-shadow trace (where albedo belongs);
    its alpha is its optical density x density_scale.  So opacity follows
    density — a type's own density range makes it naturally faint or solid (cirrus
    wispy, cumulus solid) with no per-type opacity knob.  density_scale is the
    single global trim that stops hundreds of overlapping particles compounding to
    fully opaque.

    :param n_templates: number of distinct shapes to build
    :param atlas_rects: sprite atlas rects (u, v, du, dv) to draw sprites from
    :param sun_color: RGB of direct sunlight (for shading)
    :param ambient_color: RGB of the ambient/sky fill (for shading)
    :param sun_dir: vector FROM the scene TOWARD the sun
    :param cloud_type: cloud type to build
    :param density_scale: global multiplier mapping particle density → alpha
    :param base_seed: seed of the first template (template t uses base_seed + t)
    :param uv_seed: seed for the random sprite-rect assignment
    :param overrides: per-key overrides of the type's DEFAULTS
    :returns: list of template dicts with pos (m,3), radii (m,),
        colors (m,4 RGBA) and uv (m,4) arrays
    """
    return list(
        build_templates_iter(
            n_templates,
            atlas_rects,
            sun_color,
            ambient_color,
            sun_dir,
            cloud_type=cloud_type,
            density_scale=density_scale,
            base_seed=base_seed,
            uv_seed=uv_seed,
            overrides=overrides,
        )
    )


def _template_cache_key(
    n_templates,
    atlas_rects,
    sun_color,
    ambient_color,
    sun_dir,
    cloud_type,
    density_scale,
    base_seed,
    uv_seed,
    overrides,
):
    """A content hash of everything that affects the generated templates."""

    def _r(a):
        return tuple(np.round(np.asarray(a, dtype=float).ravel(), 5).tolist())

    payload = repr(
        (
            _TEMPLATE_CACHE_VERSION,
            cloud_type.value,
            int(n_templates),
            round(float(density_scale), 6),
            int(base_seed),
            int(uv_seed),
            tuple(sorted((overrides or {}).items())),
            _r(sun_color),
            _r(ambient_color),
            _r(sun_dir),
            _r([c for rect in atlas_rects for c in rect]),
        )
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _load_cached_templates(key):
    """Return the cached template list for *key*, or None on miss/corruption."""
    path = _TEMPLATE_CACHE_DIR / f"{key}.npz"
    if not path.exists():
        return None
    try:
        with np.load(path) as data:
            n = int(data["n"])
            return [
                dict(
                    pos=data[f"t{i}_pos"],
                    radii=data[f"t{i}_radii"],
                    colors=data[f"t{i}_colors"],
                    uv=data[f"t{i}_uv"],
                )
                for i in range(n)
            ]
    except Exception as exc:  # corrupt / stale-format cache → just regenerate
        LOGGER.warning(f"[cloud-cache] ignoring unreadable cache {path.name}: {exc}")
        return None


def _save_cached_templates(key, templates):
    """Persist a generated template list under *key* (best effort)."""
    try:
        _TEMPLATE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        flat = {"n": np.array(len(templates))}
        for i, template in enumerate(templates):
            flat[f"t{i}_pos"] = template["pos"]
            flat[f"t{i}_radii"] = template["radii"]
            flat[f"t{i}_colors"] = template["colors"]
            flat[f"t{i}_uv"] = template["uv"]
        np.savez(_TEMPLATE_CACHE_DIR / f"{key}.npz", **flat)
    except OSError as exc:
        LOGGER.warning(f"[cloud-cache] could not write cache: {exc}")


def build_templates_iter(
    n_templates: int,
    atlas_rects: list,
    sun_color: np.ndarray,
    ambient_color: np.ndarray,
    sun_dir,
    cloud_type=CloudType.CUMULUS,
    density_scale: float = 0.7,
    base_seed: int = 0,
    uv_seed: int = 0,
    overrides: dict = None,
    use_cache: bool = False,
):
    """
    Generator form of :func:`build_templates`, yielding one finished template
    dict at a time.

    Each template (~18-40 ms of pure-CPU generation + self-shadow shading) is a
    natural unit of work, so a loader can drive this one template per frame to
    spread the cost instead of blocking on the whole field at once.

    :param use_cache: when True, load the whole set from the on-disk template
        cache if present (instant), otherwise generate it and save it for next
        time. Off by default so tests/tools generate fresh and never touch disk.

    See :func:`build_templates` for the other parameters and the return shape.
    """
    key = None
    if use_cache:
        key = _template_cache_key(
            n_templates,
            atlas_rects,
            sun_color,
            ambient_color,
            sun_dir,
            cloud_type,
            density_scale,
            base_seed,
            uv_seed,
            overrides,
        )
        cached = _load_cached_templates(key)
        if cached is not None:
            for template in cached:
                yield template
            return

    sun_dir = np.asarray(sun_dir, dtype=float)
    sun_dir = sun_dir / np.linalg.norm(sun_dir)
    rng = np.random.default_rng(uv_seed)

    generated = [] if use_cache else None
    for t in range(n_templates):
        particles = build_cloud_particles(
            cloud_type, seed=base_seed + t, **(overrides or {})
        )
        rgb = _shade_particles(particles, sun_color, ambient_color, sun_dir)
        local_pos = np.array([p["pos"] for p in particles], dtype=np.float32)
        local_pos -= local_pos.mean(axis=0)  # centre at origin
        radii = np.array([p["radius"] for p in particles], dtype=np.float32)
        densities = np.array([p["density"] for p in particles], dtype=np.float32)
        alpha = np.clip(densities * density_scale, 0.0, 1.0)
        uv = np.array(
            [atlas_rects[rng.integers(len(atlas_rects))] for _ in particles],
            dtype=np.float32,
        )
        template = dict(
            pos=local_pos,
            radii=radii,
            colors=np.column_stack([rgb, alpha]).astype(np.float32),
            uv=uv,
        )
        if use_cache:
            generated.append(template)
        yield template

    if use_cache:
        _save_cached_templates(key, generated)


# ── Sprite atlas ──────────────────────────────────────────────────────────────

_ASSET_DIR = Path(__file__).parent
ATLAS_PNG = _ASSET_DIR / "cloud_atlas.png"
ATLAS_JSON = _ASSET_DIR / "cloud_atlas.json"


def load_cloud_atlas(game):
    """Load the packaged cloud sprite atlas.

    Delegates to :func:`space_flight.fx.load_atlas`, so the texture is loaded
    (and cached) through the game's asset_manager like every other particle
    atlas, instead of going straight to the Panda3D loader.

    :param game: the game object (exposes app.asset_manager)
    :returns: (Texture, rects) where rects is a list of (u, v, du, dv) tuples
    """
    return load_atlas(game, ATLAS_PNG, ATLAS_JSON)
