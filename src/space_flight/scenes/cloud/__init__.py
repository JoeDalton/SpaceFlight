"""
In-scene billboard clouds.

Two modules:
    cloud.py  — a cloud's data: procedural generation, CPU self-shadow shading,
                render-ready templates (build_templates), and the sprite atlas.
    field.py  — a field of clouds: geometry, shaders, depth-sorting, wind +
                recycling (CloudField), and the game wrapper (Clouds).

Public API:
    Clouds          — game-facing wrapper (parent under game.root_node, per-frame
                      update via game.method_lists, clean()).
    CloudField      — the engine field: build from CloudLayers, draw, animate.
    CloudLayer      — per-type spec (cloud_type, count, altitude, …).
    CloudType       — CUMULUS / STRATUS / CIRRUS / CUMULONIMBUS shape presets.
    load_cloud_atlas / build_templates — lower-level building blocks.
"""

from .cloud import CloudType, build_templates, load_cloud_atlas
from .field import CloudField, CloudLayer, Clouds

__all__ = [
    "Clouds",
    "CloudField",
    "CloudLayer",
    "CloudType",
    "load_cloud_atlas",
    "build_templates",
]
