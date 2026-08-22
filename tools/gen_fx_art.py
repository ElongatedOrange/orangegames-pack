#!/usr/bin/env python3
"""Paint textures and write models + item defs for the shader-FX weapons.

Deterministic; rerun after any change. Pillow only.

Marker convention (shared with tools/gen_fx_shaders.py):
    tint RGB (255, 254 - sub, 255 - FXID)   sub = 0..54 element sub-index (bolt segment, spark index)
    FX ids: 1 prism core, 2 prism slash, 3 nova orb, 4 nova ring, 5 tesla bolt,
            6 tesla coil orb, 10 screen overlay, 11 gpu sparks, 12 blade ghost, 13 holo edge,
            14 nova sphere (ray-cast billboard, end-portal starfield)
FX elements carry tintindex k; the item def's tints[k] is the marker colour.
Textures under the marker are drawn to look right UNSHADED (Bedrock, old Java).
"""
import colorsys
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
TEX = REPO / "assets/orangegames/textures/item"
MODELS = REPO / "assets/orangegames/models/item"
ITEMS = REPO / "assets/orangegames/items"


def marker(fxid, sub=0):
    """Constant tint the shader recognises: (255, 254 - sub, 255 - fxid) -> near-white unshaded."""
    assert 1 <= fxid <= 15 and 0 <= sub <= 54
    return (255 << 16) | ((254 - sub) << 8) | (255 - fxid)


def save(img, name):
    TEX.mkdir(parents=True, exist_ok=True)
    img.save(TEX / f"{name}.png")


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def item_def(name, tints):
    write_json(ITEMS / f"{name}.json", {
        "model": {"type": "minecraft:model", "model": f"orangegames:item/{name}",
                  "tints": [{"type": "minecraft:constant", "value": t} for t in tints]}})


def shade(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def cube(frm, to, tex, uv=None, tint=None, faces=("north", "south", "east", "west", "up", "down"),
         rot=None):
    e = {"from": list(frm), "to": list(to), "faces": {}}
    if rot:
        e["rotation"] = rot
    for f in faces:
        face = {"uv": list(uv) if uv else [0, 0, 16, 16], "texture": f"#{tex}"}
        if tint is not None:
            face["tintindex"] = tint
        e["faces"][f] = face
    return e


# --------------------------------------------------------------- textures ----

def tex_solid(name, rgb, size=16, bands=True, rivets=False):
    im = Image.new("RGBA", (size, size), rgb + (255,))
    d = ImageDraw.Draw(im)
    if bands:
        d.line([(0, 0), (size - 1, 0)], fill=shade(rgb, 1.3) + (255,))
        d.line([(0, 1), (size - 1, 1)], fill=shade(rgb, 1.15) + (255,))
        d.line([(0, size - 1), (size - 1, size - 1)], fill=shade(rgb, 0.65) + (255,))
        d.line([(0, size - 2), (size - 1, size - 2)], fill=shade(rgb, 0.8) + (255,))
        d.line([(0, 0), (0, size - 1)], fill=shade(rgb, 1.1) + (255,))
        d.line([(size - 1, 0), (size - 1, size - 1)], fill=shade(rgb, 0.75) + (255,))
    if rivets:
        for (x, y) in ((3, 3), (size - 4, 3), (3, size - 4), (size - 4, size - 4)):
            im.putpixel((x, y), shade(rgb, 0.55) + (255,))
            im.putpixel((x + 1, y), shade(rgb, 1.35) + (255,))
    save(im, name)


def tex_rainbow(name, size=16):
    """Hue encodes the position along v; the shader reads hue back as the phase."""
    im = Image.new("RGBA", (size, size))
    for y in range(size):
        r, g, b = colorsys.hsv_to_rgb(y / size, 0.85, 1.0)
        for x in range(size):
            edge = 0.85 if x in (0, size - 1) else 1.0
            im.putpixel((x, y), (int(r * 255 * edge), int(g * 255 * edge), int(b * 255 * edge), 255))
    save(im, name)


def tex_radial(name, size=32, inner=(255, 255, 255), outer=(90, 160, 255), hard=False, power=0.6):
    im = Image.new("RGBA", (size, size))
    c = (size - 1) / 2
    for y in range(size):
        for x in range(size):
            dist = math.hypot(x - c, y - c) / c
            t = max(0.0, min(1.0, dist))
            rgb = tuple(int(inner[i] * (1 - t) + outer[i] * t) for i in range(3))
            if hard:
                a = 255 if dist <= 1.0 else 0
            else:
                a = int(255 * max(0.0, 1 - t) ** power) if dist <= 1.0 else 0
            im.putpixel((x, y), rgb + (a,))
    save(im, name)


def tex_crescent(name, size=32):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([1, 1, size - 2, size - 2], fill=(255, 255, 255, 235))
    d.ellipse([2, 2, size - 3, size - 3], fill=(235, 245, 255, 235))
    d.ellipse([8, -4, size + 6, size - 9], fill=(0, 0, 0, 0))  # bite -> crescent
    save(im, name)


def tex_ring(name, size=32):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, size - 1, size - 1], fill=(200, 230, 255, 220))
    d.ellipse([2, 2, size - 3, size - 3], fill=(255, 255, 255, 240))
    d.ellipse([6, 6, size - 7, size - 7], fill=(0, 0, 0, 0))
    save(im, name)


def tex_bolt(name, w=64, h=8):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.line([(0, h // 2), (w - 1, h // 2)], fill=(160, 200, 255, 120), width=5)
    d.line([(0, h // 2), (w - 1, h // 2)], fill=(255, 255, 255, 255), width=2)
    save(im, name)


def paint_all():
    tex_solid("prism_hilt", (70, 50, 90), rivets=True)
    tex_solid("prism_guard", (225, 200, 110))
    tex_solid("prism_edge", (235, 240, 255))
    tex_rainbow("prism_core")
    tex_solid("nova_body", (60, 70, 90), rivets=True)
    tex_solid("nova_barrel", (125, 135, 155))
    tex_solid("nova_vent", (120, 220, 255), bands=False)
    tex_solid("nova_grip", (45, 32, 30))
    tex_solid("tesla_base", (90, 70, 50), rivets=True)
    tex_solid("tesla_column", (200, 140, 80))
    tex_solid("tesla_ring", (235, 205, 120))
    tex_radial("tesla_orb", 16, (255, 255, 255), (120, 200, 255), hard=True)
    tex_crescent("fx_prism_slash")
    tex_radial("fx_nova_orb", 32, (255, 255, 255), (80, 150, 255), power=0.45)
    tex_ring("fx_nova_ring")
    tex_bolt("fx_tesla_bolt")
    tex_radial("fx_screen", 16, (255, 255, 255), (255, 255, 255), hard=True)   # plain white, shader paints it
    tex_radial("fx_spark", 8, (255, 255, 255), (255, 230, 160), hard=True)


# ----------------------------------------------------------------- models ----

# vanilla item/handheld (the diagonal "sword" framing); models built diagonal to match
HANDHELD = {
    "thirdperson_righthand": {"rotation": [0, -90, 55], "translation": [0, 4, 0.5], "scale": [0.85, 0.85, 0.85]},
    "thirdperson_lefthand": {"rotation": [0, 90, -55], "translation": [0, 4, 0.5], "scale": [0.85, 0.85, 0.85]},
    "firstperson_righthand": {"rotation": [0, -90, 25], "translation": [1.13, 3.2, 1.13], "scale": [0.68, 0.68, 0.68]},
    "firstperson_lefthand": {"rotation": [0, 90, -25], "translation": [1.13, 3.2, 1.13], "scale": [0.68, 0.68, 0.68]},
    "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [0.5, 0.5, 0.5]},
    "head": {"rotation": [0, 180, 0], "translation": [0, 13, 7], "scale": [1, 1, 1]},
    "fixed": {"rotation": [0, 180, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
}

# forward-pointing tool along -z (same framing the owner tuned for the chainsaw)
FORWARD_TOOL = {
    "thirdperson_righthand": {"rotation": [75.75, 0, 0], "translation": [0, 2.5, -5.75], "scale": [0.75, 0.75, 0.75]},
    "thirdperson_lefthand": {"rotation": [75.75, 0, 0], "translation": [0, 2.5, -5.75], "scale": [0.75, 0.75, 0.75]},
    "firstperson_righthand": {"rotation": [0, 0, 0], "translation": [1.5, 3, 2], "scale": [0.5, 0.5, 0.5]},
    "firstperson_lefthand": {"rotation": [0, 0, 0], "translation": [1.5, 3, 2], "scale": [0.5, 0.5, 0.5]},
    "gui": {"rotation": [30, 225, 0], "translation": [0, 1.5, 0], "scale": [0.5, 0.5, 0.5]},
    "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [0.3, 0.3, 0.3]},
    "head": {"rotation": [0, 180, 0], "translation": [0, 13, 7], "scale": [1, 1, 1]},
    "fixed": {"rotation": [0, 180, 0], "translation": [0, 0, 0], "scale": [0.4, 0.4, 0.4]},
}

UPRIGHT = {
    "thirdperson_righthand": {"rotation": [0, 0, 0], "translation": [0, 3, 1], "scale": [0.5, 0.5, 0.5]},
    "thirdperson_lefthand": {"rotation": [0, 0, 0], "translation": [0, 3, 1], "scale": [0.5, 0.5, 0.5]},
    "firstperson_righthand": {"rotation": [0, 45, 0], "translation": [1.5, 1, 1.5], "scale": [0.5, 0.5, 0.5]},
    "firstperson_lefthand": {"rotation": [0, 45, 0], "translation": [1.5, 1, 1.5], "scale": [0.5, 0.5, 0.5]},
    "gui": {"rotation": [30, 45, 0], "translation": [0, 0, 0], "scale": [0.75, 0.75, 0.75]},
    "ground": {"rotation": [0, 0, 0], "translation": [0, 2, 0], "scale": [0.4, 0.4, 0.4]},
    "head": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
    "fixed": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1, 1, 1]},
}


def model(name, textures, elements, display=None, gui_light=None):
    m = {"credit": "OrangeGames tools/gen_fx_art.py", "texture_size": [16, 16],
         "textures": {k: f"orangegames:item/{v}" for k, v in textures.items()}}
    if gui_light:
        m["gui_light"] = gui_light
    if display:
        m["display"] = display
    m["elements"] = elements
    write_json(MODELS / f"{name}.json", m)


DIAG = {"angle": -45, "axis": "z", "origin": [8, 8, 8]}  # vertical -> sprite diagonal


def build_models():
    # Prism Blade: built vertical (+y), every element tilted -45 about z so it
    # lies on the handheld sprite diagonal and vanilla handheld transforms apply.
    blade_tex = {"hilt": "prism_hilt", "guard": "prism_guard", "edge": "prism_edge", "core": "prism_core"}
    blade_elems = [
        cube([7.25, 0, 7.25], [8.75, 1, 8.75], "guard", rot=DIAG),                 # pommel
        cube([7.3, 1, 7.4], [8.7, 4.5, 8.6], "hilt", rot=DIAG),                    # grip
        cube([5.5, 4.5, 7], [10.5, 5.8, 9], "guard", rot=DIAG),                    # crossguard
        cube([6.6, 5.8, 7.6], [9.4, 14.2, 8.4], "edge", tint=1, rot=DIAG),         # blade (holo edge, FX 13)
        cube([7.35, 5.8, 7.3], [8.65, 13.6, 8.7], "core", tint=0, rot=DIAG),       # rainbow core (FX 1)
        cube([7.0, 14.2, 7.7], [9.0, 15.2, 8.3], "edge", tint=1, rot=DIAG),        # taper
        cube([7.5, 15.2, 7.8], [8.5, 16.2, 8.2], "edge", tint=1, rot=DIAG),        # tip
    ]
    model("prism_blade", blade_tex, blade_elems,
          {**HANDHELD, "gui": {"rotation": [0, 0, 0], "translation": [0, 0, 0], "scale": [1.3, 1.3, 1.3]}})
    # swing ghost: identical geometry, every face tinted -> one marker (FX 12), no display section
    ghost = json.loads(json.dumps(blade_elems))
    for e in ghost:
        for f in e["faces"].values():
            f["tintindex"] = 0
    model("fx_prism_ghost", blade_tex, ghost, gui_light="front")

    # Nova Cannon: barrel along -z (forward), chainsaw-style framing.
    model("nova_cannon",
          {"body": "nova_body", "barrel": "nova_barrel", "vent": "nova_vent", "grip": "nova_grip"}, [
              cube([5, 6, 2], [11, 11, 12], "body"),                                     # receiver
              cube([6.25, 7, -6], [9.75, 10.5, 2], "barrel"),                            # barrel
              cube([5.75, 6.5, -7.5], [10.25, 11, -6], "barrel"),                        # muzzle flare
              cube([6.5, 7.5, -8], [9.5, 10, -7.5], "vent"),                             # muzzle core
              cube([6.5, 11, 4], [9.5, 12, 10], "vent"),                                 # top vent strip
              cube([4.5, 7.5, 4], [5, 9.5, 10], "vent"),                                 # side vents
              cube([11, 7.5, 4], [11.5, 9.5, 10], "vent"),
              cube([6.5, 2, 8], [9.5, 6, 11], "grip"),                                   # grip
              cube([6.5, 4.5, 12], [9.5, 9, 14], "body"),                                # stock
          ], FORWARD_TOOL)

    # Tesla Coil: upright; the orb is the marker (FX 6). Also the placed prop model.
    model("tesla_coil",
          {"base": "tesla_base", "col": "tesla_column", "ring": "tesla_ring", "orb": "tesla_orb"}, [
              cube([4, 0, 4], [12, 2, 12], "base"),
              cube([5.5, 2, 5.5], [10.5, 3, 10.5], "base"),
              cube([7, 3, 7], [9, 11, 9], "col"),
              cube([5.5, 4, 5.5], [10.5, 5, 10.5], "ring"),
              cube([6, 6.5, 6], [10, 7.5, 10], "ring"),
              cube([6.5, 9, 6.5], [9.5, 10, 9.5], "ring"),
              cube([6, 11, 6], [10, 15, 10], "orb", tint=0),
          ], UPRIGHT)

    # ---- FX meshes: no display section, rendered with ItemDisplayTransform.NONE,
    # model space 0..16 maps to -0.5..0.5 around the entity position.
    model("fx_prism_slash", {"t": "fx_prism_slash"},
          [cube([0, 0, 8], [16, 16, 8], "t", tint=0, faces=("north", "south"))], gui_light="front")
    # nova orb: a single 2x2-block quad; FX 14 billboards it in view space and ray-casts a sphere
    # (radius from the charge param) whose surface is a parallax starfield "window"
    model("fx_nova_orb", {"t": "fx_nova_orb"},
          [cube([-8, -8, 8], [24, 24, 8], "t", tint=0, faces=("north", "south"))], gui_light="front")
    model("fx_nova_ring", {"t": "fx_nova_ring"},
          [cube([0, 8, 0], [16, 8, 16], "t", tint=0, faces=("up", "down"))], gui_light="front")
    # bolt: 8 zero-thickness segments along +x, element i -> tintindex i -> marker sub i
    segs = []
    for i in range(8):
        segs.append(cube([i * 2, 7, 8], [i * 2 + 2, 9, 8], "t",
                         uv=[i * 2, 0, i * 2 + 2, 16], tint=i, faces=("north", "south")))
    model("fx_tesla_bolt", {"t": "fx_tesla_bolt"}, segs, gui_light="front")
    # screen overlay: one double-sided quad; the vsh re-positions it across the viewport (FX 10)
    model("fx_screen", {"t": "fx_screen"},
          [cube([0, 0, 8], [16, 16, 8], "t", tint=0, faces=("north", "south"))], gui_light="front")
    # gpu sparks: 48 micro-cubes at the origin, element i -> tintindex i -> marker sub i (FX 11);
    # the vsh scatters each cube along its own hashed trajectory
    sparks = [cube([7.4, 7.4, 7.4], [8.6, 8.6, 8.6], "t", tint=i) for i in range(48)]
    model("fx_sparks", {"t": "fx_spark"}, sparks, gui_light="front")


def build_defs():
    item_def("prism_blade", [marker(1), marker(13)])
    item_def("fx_prism_ghost", [marker(12)])
    item_def("fx_screen", [marker(10)])
    item_def("fx_sparks", [marker(11, i) for i in range(48)])
    item_def("nova_cannon", [])
    item_def("tesla_coil", [marker(6)])
    item_def("fx_prism_slash", [marker(2)])
    item_def("fx_nova_orb", [marker(14)])
    item_def("fx_nova_ring", [marker(4)])
    item_def("fx_tesla_bolt", [marker(5, i) for i in range(8)])


if __name__ == "__main__":
    paint_all()
    build_models()
    build_defs()
    print("fx art: 18 textures, 10 models, 10 item defs written")
