#!/usr/bin/env python3
"""Build the six premium 3D hats (Phase M1 launch batch).

Programmatically authors, for each hat id:
    assets/orangecosmetics/textures/item/<id>.png   32x32 solid-swatch atlas
    assets/orangecosmetics/models/item/<id>.json    Blockbench-style element model
    assets/orangecosmetics/items/<id>.json          item definition

Each hat is defined as a list of axis-aligned cuboids with a named color per
cuboid (optionally overridden per face). Every distinct color used by a hat
gets one 4x4-pixel swatch in that hat's 32x32 atlas; swatches carry slight
per-pixel shade noise so faces don't render dead flat. Faces are UV-mapped to
the interior of their swatch (0.25 uv inset) to avoid atlas bleed.

Display/groups boilerplate matches cap_hat.json (the house baseline);
orange_halo raises the head translation so it floats above the head.

Usage: python tools/build_premium_hats.py
"""
import json
import random
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "assets" / "orangecosmetics" / "models" / "item"
TEXTURES = REPO / "assets" / "orangecosmetics" / "textures" / "item"
ITEMS = REPO / "assets" / "orangecosmetics" / "items"

ATLAS_PX = 32          # atlas is 32x32 px; java uv space is 0..16 over it
SWATCH_PX = 4          # one 4x4 px swatch per distinct color
COLS = ATLAS_PX // SWATCH_PX
UV_PER_PX = 16.0 / ATLAS_PX   # 0.5 uv units per pixel
INSET = 0.25                  # uv inset into each swatch (half a pixel)

FACES = ("north", "east", "south", "west", "up", "down")


def hexc(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def shade(c, f):
    return tuple(max(0, min(255, int(round(x * f)))) for x in c)


# --------------------------------------------------------------- palettes ----
# Sampled with Pillow from the leftover 16x16 sprites before overwriting:
#   golden_crown : #daa147 gold, #fbd775 highlight, #7d4124 shadow
#   orange_halo  : #d0ac3b gold, #be761e orange (sprite outline browns ignored)
#   neon_visor   : #191924/#302e3a dark frame, #be501b orange visor
#   royal_beret  : #4e3451 purple, #6f4564 light, #3a2842 dark
#   citrus_wreath: #d7741f orange, #528024 green, #3d5616 dark green
#   blood_crown  : brief directive: dark iron greys + deep red + near-black gems
PALETTES = {
    "golden_crown": {
        "gold": "#daa147", "gold_light": "#fbd775", "gold_dark": "#a06a2c",
        "gem": "#c14a1e", "gem_light": "#e8703a",
    },
    "blood_crown": {
        "iron": "#3a3a3e", "iron_light": "#54545a", "iron_dark": "#26262a",
        "red": "#8b0e0e", "gem": "#141216",
    },
    "orange_halo": {
        "gold": "#e0b435", "glow": "#ffe98a", "gold_dark": "#b57e1e",
    },
    "neon_visor": {
        "frame": "#24222e", "frame_light": "#464451",
        "neon": "#ff6a1e", "neon_dark": "#cf4b12", "cyan": "#35e0e6",
    },
    "royal_beret": {
        "purple": "#4e3451", "purple_light": "#6f4564", "purple_dark": "#3a2842",
        "trim": "#d4a83c",
    },
    "citrus_wreath": {
        "orange": "#d7741f", "orange_light": "#f0903a",
        "green": "#528024", "green_dark": "#3d5616",
    },
}


# --------------------------------------------------------------- geometry ----

class Hat:
    def __init__(self, hat_id):
        self.id = hat_id
        self.cuboids = []   # (from, to, base color name, {face: color name})
        self.head_translation = [0, 13, 0.75]   # cap_hat baseline

    def add(self, frm, to, color, faces=None):
        self.cuboids.append((list(frm), list(to), color, dict(faces or {})))


def crown(hat, band, band_top, spike, spike_tip, gem, spike_h, mid_h):
    """Shared circlet geometry: square band ring + 5 tipped spikes + 3 gems."""
    y0, y1 = 2.5, 5.5
    tip_h = 1.3
    # band ring, walls 1 thick, footprint x/z 3..13; darker top edge so the
    # spikes read against it
    bt = {"up": band_top}
    hat.add([3, y0, 3], [13, y1, 4], band, bt)     # north (front)
    hat.add([3, y0, 12], [13, y1, 13], band, bt)   # south
    hat.add([3, y0, 4], [4, y1, 12], band, bt)     # west
    hat.add([12, y0, 4], [13, y1, 12], band, bt)   # east
    # corner spikes with contrasting tip segments
    for cx, cz in ((3, 3), (12, 3), (3, 12), (12, 12)):
        hat.add([cx, y1, cz], [cx + 1, y1 + spike_h - tip_h, cz + 1], spike)
        hat.add([cx, y1 + spike_h - tip_h, cz],
                [cx + 1, y1 + spike_h, cz + 1], spike_tip)
    # front-center spike (taller), tipped too
    hat.add([7.5, y1, 3], [8.5, y1 + mid_h - tip_h, 4], spike)
    hat.add([7.5, y1 + mid_h - tip_h, 3], [8.5, y1 + mid_h, 4], spike_tip)
    # gems on the front band face, protruding slightly past z=3
    hat.add([7.1, 3.3, 2.6], [8.9, 4.9, 3.1], gem)
    hat.add([4.5, 3.5, 2.6], [5.7, 4.6, 3.1], gem)
    hat.add([10.3, 3.5, 2.6], [11.5, 4.6, 3.1], gem)


def build_hats():
    hats = {}

    h = Hat("golden_crown")
    crown(h, "gold", "gold_dark", "gold", "gold_light", "gem", 3.2, 4.2)
    hats[h.id] = h

    h = Hat("blood_crown")
    crown(h, "iron", "iron_dark", "iron", "red", "gem", 4.5, 5.5)
    hats[h.id] = h

    h = Hat("orange_halo")
    t = 1.25
    y0, y1 = 6, 7.25
    glow = {"up": "glow", "down": "gold_dark"}
    h.add([3.5, y0, 3.5], [12.5, y1, 3.5 + t], "gold", glow)      # north
    h.add([3.5, y0, 12.5 - t], [12.5, y1, 12.5], "gold", glow)    # south
    h.add([3.5, y0, 3.5 + t], [3.5 + t, y1, 12.5 - t], "gold", glow)    # west
    h.add([12.5 - t, y0, 3.5 + t], [12.5, y1, 12.5 - t], "gold", glow)  # east
    h.head_translation = [0, 17, 0.75]   # floats ~4 above baseline
    hats[h.id] = h

    h = Hat("neon_visor")
    # bright faceplate across the front at the face line (the star of the show)
    h.add([3, 0.6, 2.2], [13, 3.9, 3.2], "neon", {"down": "neon_dark"})
    # cyan accent stripe, slightly proud of the faceplate
    h.add([3.4, 3.1, 2.0], [12.6, 3.9, 2.25], "cyan")
    # slim dark frame bar over the top
    h.add([2.6, 3.9, 2.0], [13.4, 4.7, 3.4], "frame", {"up": "frame_light"})
    # slim side arms going back along the head
    h.add([2.6, 2.9, 3.2], [3.6, 4.3, 12], "frame")
    h.add([12.4, 2.9, 3.2], [13.4, 4.3, 12], "frame")
    hats[h.id] = h

    h = Hat("royal_beret")
    # gold trim band at the base, a sliver wider than the felt so it shows
    h.add([3.3, 2.5, 3.3], [12.7, 3.5, 12.7], "trim")
    # bottom felt slab
    h.add([3.5, 3.5, 3.5], [12.5, 5.3, 12.5], "purple", {"up": "purple_dark"})
    # top slab, pushed well to one side for the classic tilt
    h.add([2.2, 5.3, 2.8], [9.6, 6.9, 10.2], "purple_light",
          {"down": "purple_dark", "north": "purple", "west": "purple"})
    # stem, sitting on the tilted top
    h.add([5.4, 6.9, 5.9], [6.6, 8.1, 7.1], "purple_dark")
    hats[h.id] = h

    h = Hat("citrus_wreath")
    y0, y1 = 2.5, 4.7
    # oranges (cubes) at the edge midpoints
    for cx, cz in ((8, 3.7), (8, 12.3), (3.7, 8), (12.3, 8)):
        s = 1.15
        h.add([cx - s, y0, cz - s], [cx + s, y0 + 2.2, cz + s], "orange",
              {"up": "orange_light"})
    # leaves (flatter slabs) at the corners
    for cx, cz in ((4.2, 4.2), (11.8, 4.2), (4.2, 11.8), (11.8, 11.8)):
        s = 1.3
        h.add([cx - s, y0 + 0.2, cz - s], [cx + s, y0 + 1.9, cz + s], "green",
              {"down": "green_dark"})
    hats[h.id] = h

    return hats


# ------------------------------------------------------------------ atlas ----

def paint_atlas(hat, palette):
    """One 4x4 noisy swatch per distinct color; returns (image, color->uv rect)."""
    used = []
    for _, _, base, faces in hat.cuboids:
        for name in [base] + list(faces.values()):
            if name not in used:
                used.append(name)
    if len(used) > COLS * COLS:
        raise SystemExit(f"{hat.id}: too many colors for atlas")

    rng = random.Random(hat.id)   # deterministic per hat
    img = Image.new("RGBA", (ATLAS_PX, ATLAS_PX), (0, 0, 0, 0))
    px = img.load()
    uv_map = {}
    for i, name in enumerate(used):
        base = hexc(palette[name])
        col, row = i % COLS, i // COLS
        x0, y0 = col * SWATCH_PX, row * SWATCH_PX
        for dy in range(SWATCH_PX):
            for dx in range(SWATCH_PX):
                f = rng.choice((0.92, 1.0, 1.0, 1.06))
                px[x0 + dx, y0 + dy] = shade(base, f) + (255,)
        u0, v0 = x0 * UV_PER_PX, y0 * UV_PER_PX
        u1, v1 = u0 + SWATCH_PX * UV_PER_PX, v0 + SWATCH_PX * UV_PER_PX
        uv_map[name] = [round(u0 + INSET, 4), round(v0 + INSET, 4),
                        round(u1 - INSET, 4), round(v1 - INSET, 4)]
    return img, uv_map


# ------------------------------------------------------------------ model ----

def build_model(hat, uv_map):
    elements = []
    for frm, to, base, face_colors in hat.cuboids:
        faces = {}
        for face in FACES:
            faces[face] = {"uv": uv_map[face_colors.get(face, base)],
                           "texture": "#0"}
        elements.append({
            "from": frm,
            "to": to,
            "rotation": {"angle": 0, "axis": "y", "origin": [8, 8, 8]},
            "faces": faces,
        })
    return {
        "format_version": "1.21.6",
        "texture_size": [32, 32],
        "textures": {"0": f"orangecosmetics:item/{hat.id}"},
        "elements": elements,
        "gui_light": "front",
        "display": {
            "thirdperson_righthand": {
                "rotation": [-45, 0, 0],
                "translation": [0, 0.25, -4],
                "scale": [0.7, 0.7, 0.7],
            },
            "thirdperson_lefthand": {
                "rotation": [-45, 0, 0],
                "translation": [0, 0.25, -4],
                "scale": [0.7, 0.7, 0.7],
            },
            "firstperson_righthand": {
                "rotation": [160, 60, 160],
                "translation": [0.25, 4, 1],
                "scale": [0.5, 0.5, 0.5],
            },
            "firstperson_lefthand": {
                "rotation": [160, 60, 160],
                "translation": [0.25, 4, 1],
                "scale": [0.5, 0.5, 0.5],
            },
            "ground": {"scale": [0.6, 0.6, 0.6]},
            "gui": {
                "rotation": [-149.25, -35, -180],
                "translation": [0, 3.25, 0],
            },
            "head": {
                "rotation": [5, 0, 0],
                "translation": hat.head_translation,
                "scale": [1.65, 1.65, 1.65],
            },
            "fixed": {
                "rotation": [-90, 0, 0],
                "translation": [0, 0, -11],
                "scale": [2, 2, 2],
            },
        },
        "groups": [{
            "name": hat.id,
            "origin": [8, 8, 8],
            "color": 0,
            "children": list(range(len(elements))),
        }],
    }


def build_item_def(hat_id):
    return {
        "model": {
            "type": "minecraft:model",
            "model": f"orangecosmetics:item/{hat_id}",
            "tints": [],
        }
    }


def main():
    hats = build_hats()
    for hat_id, hat in hats.items():
        atlas, uv_map = paint_atlas(hat, PALETTES[hat_id])
        model = build_model(hat, uv_map)
        # sanity: coords in the 16-unit cube, uvs inside the texture
        for el in model["elements"]:
            for a, b in zip(el["from"], el["to"]):
                assert 0 <= a <= b <= 16, f"{hat_id}: bad cuboid {el['from']}"
            for face in el["faces"].values():
                assert all(0 <= u <= 16 for u in face["uv"]), \
                    f"{hat_id}: uv out of range {face['uv']}"
        atlas.save(TEXTURES / f"{hat_id}.png")
        (MODELS / f"{hat_id}.json").write_text(
            json.dumps(model, indent="\t") + "\n", encoding="utf-8")
        (ITEMS / f"{hat_id}.json").write_text(
            json.dumps(build_item_def(hat_id), indent=4) + "\n", encoding="utf-8")
        print(f"{hat_id}: {len(hat.cuboids)} cuboids, "
              f"{len(uv_map)} colors -> atlas/model/item written")


if __name__ == "__main__":
    main()
