"""
In-scene billboard clouds.

Three modules:
    noise.py  — what a cloud type LOOKS like: its density field (DensityField),
                and the tileable 3D value-noise volume it is built from.
    cloud.py  — where a type's billboards go: rejection-sampled against that very
                field (sample_field_particles), grouped into spatial cells.
    field.py  — a field of clouds: geometry, shaders, depth-sorting, wind +
                recycling (CloudField), and the game wrapper (Clouds).

And one design note, view_aligned_slicing.md: whether the billboards could be
replaced by full-screen slices at exponentially spaced depths. Open question, not
implemented — but it carries the profiling that says this deck's cost is
per-billboard and per-frame-CPU rather than fill-bound, which is worth reading
before optimising anything here.

The design in two lines. A billboard is a *sample of a volume*, not a sprite: its
geometry says where in the volume it is and how much volume sits behind each of
its pixels, while shape, opacity and colour are continuous functions of world
position evaluated per fragment. And a cloud is not an object: a cloud TYPE is one
density field spanning a slab of sky, and the clouds you see are its features —
which is why they can shadow each other, and why their silhouettes are as crisp
as the field is.

Public API:
    Clouds          — game-facing wrapper (parent under game.root_node, per-frame
                      update via game.method_lists, clean()).
    CloudField      — the engine field: build from CloudLayers, draw, animate,
                      and move the sun with set_sun().
    CloudLayer      — one type's worth of sky (cloud_type, field, optics, …).
    CloudType       — CUMULUS / STRATUS / CIRRUS / CUMULONIMBUS presets.
    DensityField    — a type's SHAPE: slab, feature size, coverage, profile.
                      Drives placement, so changing it needs a rebuild — except
                      coverage, which CloudField.set_coverage can sweep live
                      downward (see there for why only downward).
    CloudOptics     — a type's LIGHT: sun march, powder, phase, optical-depth
                      cap. Shading only, so CloudField.set_optics changes it live.
    PRESETS         — the per-type CloudSpec table to start from or override.
    CloudQuality    — LOW / MID / HIGH / ULTRA. HIGH is what PRESETS ship; the
                      others scale a type's COST via at_quality(). CloudField
                      reads the player's setting unless given one explicitly.

How much cloud there is: a type's ``coverage`` is the fraction of sky its own slab
fills, measured zenith-projected — a column counts if there is cloud at any height
in it. It is authored; the smoothstep window the shader actually uses is DERIVED
from it by measuring the field (see noise.resolve_field), because which raw fbm
value corresponds to a given coverage depends on the noise volume, and therefore
on the seed. That inversion is exact rather than fitted, and it is what stops a
change to the octave weights — a shape decision — from silently changing how much
cloud there is.
"""

from space_flight.scenes.cloud.cloud import (
    PRESETS,
    QUALITY_SCALES,
    CloudQuality,
    CloudSpec,
    CloudType,
    at_quality,
)
from space_flight.scenes.cloud.field import CloudField, CloudLayer, Clouds
from space_flight.scenes.cloud.noise import (
    CloudOptics,
    DensityField,
    build_noise_texture,
    measure_coverage,
    resolve_field,
)

__all__ = [
    "Clouds",
    "CloudField",
    "CloudLayer",
    "CloudType",
    "CloudSpec",
    "CloudOptics",
    "CloudQuality",
    "DensityField",
    "PRESETS",
    "QUALITY_SCALES",
    "at_quality",
    "build_noise_texture",
    "measure_coverage",
    "resolve_field",
]
