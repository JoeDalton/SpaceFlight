"""
build_atlas.py
==============
Dev-time tool — run once (or whenever sprites change).

Produces:
    sprites/fire_atlas.png   + sprites/fire_atlas.json
    sprites/smoke_atlas.png  + sprites/smoke_atlas.json

Each JSON is a list of {u_min, v_min, u_size, v_size} dicts (UV in 0..1)
corresponding to each sprite, in the order they were found on disk.

Usage:
    python build_atlas.py
"""

import json
from pathlib import Path

from PIL import Image

TILE_SIZE = 256  # all sprites are resized to this before packing
PADDING = 2  # pixels between tiles (avoids bilinear bleed)
FIRE_DIR = Path("sprites/fire")
SMOKE_DIR = Path("sprites/smoke")
OUT_DIR = Path("sprites")


def next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def build_atlas(sprite_dir: Path, out_stem: str):
    paths = sorted(sprite_dir.glob("*.png"))
    if not paths:
        raise FileNotFoundError(f"No PNGs found in {sprite_dir}")

    n = len(paths)
    pad = PADDING
    tile = TILE_SIZE

    # Pack into a single row — works well for small counts (≤24)
    # Atlas width: n tiles + padding between + on edges
    aw_raw = n * tile + (n + 1) * pad
    ah_raw = tile + 2 * pad
    aw = next_pow2(aw_raw)
    ah = next_pow2(ah_raw)

    atlas = Image.new("RGBA", (aw, ah), (0, 0, 0, 0))
    rects = []

    for i, path in enumerate(paths):
        img = Image.open(path).convert("RGBA")
        img = img.resize((tile, tile), Image.LANCZOS)

        x = pad + i * (tile + pad)
        y = pad
        atlas.paste(img, (x, y))

        # Flip V for OpenGL/Panda3D convention (V=0 at bottom)
        v_min_gl = 1.0 - (y + tile) / ah
        v_max_gl = 1.0 - y / ah

        rects.append(
            {
                "u_min": x / aw,
                "v_min": v_min_gl,
                "u_size": tile / aw,
                "v_size": v_max_gl - v_min_gl,
                "name": path.name,
            }
        )

    atlas_path = OUT_DIR / f"{out_stem}_atlas.png"
    json_path = OUT_DIR / f"{out_stem}_atlas.json"

    atlas.save(atlas_path)
    with open(json_path, "w") as f:
        json.dump(rects, f, indent=2)

    print(f"[atlas] {out_stem}: {n} tiles → {atlas_path} ({aw}×{ah})")
    return atlas_path, json_path


if __name__ == "__main__":
    build_atlas(FIRE_DIR, "fire")
    build_atlas(SMOKE_DIR, "smoke")
    print("Done.")
