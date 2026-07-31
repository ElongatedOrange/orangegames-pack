#!/usr/bin/env python3
"""Generate the OrangeGames native HUD fonts + Java glyph constants.

The plugin composes bossbar text from these fonts; the betterhud_* overlay
shaders decode the position encoding (element id in the high bits of glyph Y):

    ascent(id, y) = -(((1024 + id) << 13) + 4105 + y - 9 + CALIB)

id semantics baked into all overlay shaders' switch tables:
  1 = absolute from left edge, base layer
  2 = absolute from left edge, layer +1 (draws on top)
  3 = right-anchored

CRITICAL metric rule: Minecraft computes a bitmap glyph's advance from the
RIGHTMOST NON-TRANSPARENT COLUMN, not the image width:
    advance = int(0.5 + trimmed_w * height / tex_h) + 1
Transparent left padding still renders (shifts the art right) but adds no
advance. We therefore measure both from the alpha channel and emit exact
per-glyph advances + left pads, so every element's net width is exactly zero
and the boss bar string stays center-anchored.
"""
import json
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "orangegames" / "font"
TEX = ROOT / "assets" / "orangegames" / "textures" / "hud"
JAVA = Path(r"C:\Users\jackh\Development\OrangeGames\src\main\java\com\elongatedorange\orangegames\hud\HudGlyphs.java")
VANILLA_JAR = Path(r"C:\Users\jackh\AppData\Local\Temp\claude\C--Users-jackh-Development-OrangeGames\cbaa0dc5-d2fa-4126-82a0-a75043f4f380\scratchpad\vanilla\client-1.21.11.jar")

CALIB = 10  # global vertical calibration (screenshots showed -10px drift)


def enc(elem_id, y):
    return -(((1024 + elem_id) << 13) + 4105 + y - 9 + CALIB)


def tex_path(ref):
    ns, _, p = ref.partition(":")
    return ROOT / "assets" / ns / "textures" / p


def alpha_cols(im):
    """(leftmost, rightmost+1) columns containing any non-transparent pixel."""
    a = im.convert("RGBA").split()[-1]
    w, h = im.size
    cols = [x for x in range(w) if any(a.getpixel((x, y)) > 0 for y in range(h))]
    if not cols:
        return 0, w
    return cols[0], cols[-1] + 1


# ---------------------------------------------------------------- player head
def bake_head():
    TEX.mkdir(parents=True, exist_ok=True)
    out = TEX / "head.png"
    try:
        import base64, io
        prof = json.load(urllib.request.urlopen(
            "https://api.mojang.com/users/profiles/minecraft/Elongated_Orange", timeout=10))
        sess = json.load(urllib.request.urlopen(
            "https://sessionserver.mojang.com/session/minecraft/profile/" + prof["id"], timeout=10))
        tex_b64 = next(p for p in sess["properties"] if p["name"] == "textures")["value"]
        url = json.loads(base64.b64decode(tex_b64))["textures"]["SKIN"]["url"]
        skin = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=10).read())).convert("RGBA")
        head = skin.crop((8, 8, 16, 16))
        head.alpha_composite(skin.crop((40, 8, 48, 16)))
        head.save(out)
        return "fetched skin for Elongated_Orange"
    except Exception as e:
        import shutil
        shutil.copy2(tex_path("betterhud:glyph_online.png"), out)
        return f"head fetch failed ({type(e).__name__}) - placeholder used"


# ------------------------------------------------------------------- builders
SPACE_POWERS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
cp_next = [0xE800]


def nextcp():
    cp_next[0] += 1
    return cp_next[0]


spaces = {" ": 4}
for p in SPACE_POWERS:
    spaces[chr(nextcp())] = p
for p in SPACE_POWERS:
    spaces[chr(nextcp())] = -p

img_providers = []
java_glyphs = []  # (NAME, char, mc_advance, left_pad)


def add_img(name, ref, elem_id, y, height=None):
    im = Image.open(tex_path(ref))
    w, h = im.size
    height = height if height is not None else h
    scale = height / h
    left, right = alpha_cols(im)
    adv = int(0.5 + right * scale) + 1
    padl = round(left * scale)
    ch = chr(nextcp())
    img_providers.append({
        "type": "bitmap", "file": ref, "ascent": enc(elem_id, y),
        "height": height, "chars": [ch],
    })
    java_glyphs.append((name, ch, adv, padl))


# --- pre-scaled textures so target boxes are exact ---
print(bake_head())


def load(ref):
    return Image.open(tex_path(ref)).convert("RGBA")


def save(img, name):
    img.save(TEX / name)
    return "orangegames:hud/" + name


# coords chip background: left cap + tiled body + right cap = 90x14
chip = Image.new("RGBA", (90, 14))
chip.paste(load("betterhud:background_background_left.png"), (0, 0))
for i in range(13):
    chip.paste(load("betterhud:background_background_body.png"), (6 + 6 * i, 0))
chip.paste(load("betterhud:background_background_right.png"), (84, 0))
coords_bg = save(chip, "coords_bg.png")

# bars resized to exact boxes: bg 89x8, fills inside 87x6
bar_refs = {}
for key, (bg_ref, fill_ref) in {
    "HEALTH": ("betterhud:image_xp.png", "betterhud:image_image_xpbar_left_25_{}.png"),
    "SHIELD": ("betterhud:image_shield.png", "betterhud:image_image_shield_bar_left_25_{}.png"),
}.items():
    bar_refs[key] = save(load(bg_ref).resize((100, 9), Image.NEAREST), f"bar_{key.lower()}_bg.png")
    fills = []
    for i in range(1, 26):
        f = load(fill_ref.format(i))
        w = max(1, round(f.width * 98 / 121))
        fills.append(save(f.resize((w, 7), Image.NEAREST), f"fill_{key.lower()}_{i}.png"))
    bar_refs[key + "_FILLS"] = fills

# --- element glyphs (layout measured from the reference screenshot) ---
add_img("COORDS_BG", coords_bg, 1, 3)                                  # left 12
add_img("LOCATION", "betterhud:glyph_location.png", 2, 6, height=8)    # left 15
add_img("CARD_BG", "betterhud:image_top.png", 1, 20, height=56)        # w106, left 12
add_img("HEAD", "orangegames:hud/head.png", 2, 25, height=24)          # left 17
add_img("PING_GREEN", "betterhud:glyph_ping_green.png", 2, 39, height=6)   # left 46
add_img("PING_YELLOW", "betterhud:glyph_ping_yellow.png", 2, 39, height=6)
add_img("PING_RED", "betterhud:glyph_ping_red.png", 2, 39, height=6)
add_img("HEALTH_BG", bar_refs["HEALTH"], 1, 50)                        # left 15
add_img("SHIELD_BG", bar_refs["SHIELD"], 1, 62)                        # left 15
for i in range(1, 26):
    add_img(f"HEALTH_FILL_{i}", bar_refs["HEALTH_FILLS"][i - 1], 2, 51)  # left 16
for i in range(1, 26):
    add_img(f"SHIELD_FILL_{i}", bar_refs["SHIELD_FILLS"][i - 1], 2, 63)  # left 16

# ------------------------------------------------------------------ ascii font
ASCII_ROWS = [
    "\u00c0\u00c1\u00c2\u00c8\u00ca\u00cb\u00cd\u00d3\u00d4\u00d5\u00da\u00df\u00e3\u00f5\u011f\u0130",
    "\u0131\u0152\u0153\u015e\u015f\u0174\u0175\u017e\u0207\u0000\u0000\u0000\u0000\u0000\u0000\u0000",
    "\u0000!\"#$%&'()*+,-./",
    "0123456789:;<=>?",
    "@ABCDEFGHIJKLMNO",
    "PQRSTUVWXYZ[\\]^_",
    "`abcdefghijklmno",
    "pqrstuvwxyz{|}~\u0000",
] + ["\u0000" * 16] * 8

TEXT_YS = {"COORDS": 7, "NAME": 27, "PING": 39, "HEALTH": 51, "SHIELD": 63}

FONT.mkdir(parents=True, exist_ok=True)
space_provider = {"type": "space", "advances": {c: v for c, v in spaces.items()}}
json.dump({"providers": [space_provider] + img_providers},
          open(FONT / "hud.json", "w", encoding="utf-8"), ensure_ascii=False)
for name, y in TEXT_YS.items():
    prov = [space_provider, {
        "type": "bitmap", "file": "minecraft:font/ascii.png",
        "ascent": enc(2, y), "height": 8, "chars": ASCII_ROWS,
    }]
    json.dump({"providers": prov},
              open(FONT / f"text_{name.lower()}.json", "w", encoding="utf-8"), ensure_ascii=False)

# ----------------------------------------------- exact vanilla ascii advances
# Measure each glyph cell of vanilla ascii.png the way Minecraft does.
import io as _io
ascii_png = Image.open(_io.BytesIO(
    zipfile.ZipFile(VANILLA_JAR).read("assets/minecraft/textures/font/ascii.png"))).convert("RGBA")
cw, chh = ascii_png.width // 16, ascii_png.height // 16
ascii_adv = [6] * 96  # printable ' '..DEL, default 6
ascii_adv[0] = 4      # space comes from the space provider
for row in range(2, 8):
    for col in range(16):
        ch = ASCII_ROWS[row][col]
        if ch in ("\u0000", " "):
            continue
        cell = ascii_png.crop((col * cw, row * chh, (col + 1) * cw, (row + 1) * chh))
        _, right = alpha_cols(cell)
        code = ord(ch)
        if 32 <= code < 128:
            ascii_adv[code - 32] = int(0.5 + right * 8 / chh) + 1


# ------------------------------------------------------------------ Java const
def jstr(ch):
    return '"' + "".join("\\u%04x" % ord(u) for u in ch) + '"'


lines = [
    "package com.elongatedorange.orangegames.hud;",
    "",
    "/** GENERATED by orangegames-pack/tools/gen_hud.py - do not edit by hand. */",
    "public final class HudGlyphs {",
    "    private HudGlyphs() {}",
    "",
    "    public static final String FONT_HUD = \"orangegames:hud\";",
]
for name in TEXT_YS:
    lines.append(f"    public static final String FONT_TEXT_{name} = \"orangegames:text_{name.lower()}\";")
lines += [
    "",
    "    // space advances: POS[i]/NEG[i] moves the cursor +/- (1 << i) pixels",
    "    public static final String[] POS = {"
    + ", ".join(jstr(c) for c, v in spaces.items() if v > 0 and c != " ") + "};",
    "    public static final String[] NEG = {"
    + ", ".join(jstr(c) for c, v in spaces.items() if v < 0 and c != " ") + "};",
    "",
    "    // exact advances for vanilla ascii.png glyphs at height 8 (' '..'~')",
    "    public static final int[] ASCII_ADV = {" + ", ".join(map(str, ascii_adv)) + "};",
    "",
]
for name, ch, adv, padl in java_glyphs:
    if "_FILL_" in name:
        continue
    lines.append(f"    public static final String {name} = {jstr(ch)}; "
                 f"public static final int {name}_ADV = {adv}; public static final int {name}_PADL = {padl};")
for key in ("HEALTH", "SHIELD"):
    chars = [jstr(ch) for n, ch, a, p in java_glyphs if n.startswith(key + "_FILL_")]
    advs = [str(a) for n, ch, a, p in java_glyphs if n.startswith(key + "_FILL_")]
    lines.append(f"    public static final String[] {key}_FILL = {{" + ", ".join(chars) + "};")
    lines.append(f"    public static final int[] {key}_FILL_ADV = {{" + ", ".join(advs) + "};")
lines.append("}")
JAVA.parent.mkdir(parents=True, exist_ok=True)
JAVA.write_text("\n".join(lines), encoding="utf-8")

print(f"wrote hud.json ({len(img_providers)} image glyphs), {len(TEXT_YS)} text fonts, HudGlyphs.java")
