"""
In-scene billboard clouds.

    noise.py  — what a cloud type looks like: its density field (DensityField)
                and the tileable 3D value-noise volume it is built from.
    cloud.py  — where a type's billboards go (sample_field_particles), presets
                (PRESETS, CloudSpec) and quality scaling (CloudQuality).
    field.py  — the drawable field (CloudField: geometry, sorting, wind, live
                set_sun / set_optics / set_coverage) and the game wrapper (Clouds).

A billboard is a sample of a volume, not a sprite, and a cloud type is one density
field over a slab of sky whose features are the clouds. Design notes:
docs/source/scenes.md; profiling and an open alternative: view_aligned_slicing.md.
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
