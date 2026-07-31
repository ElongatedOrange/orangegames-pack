#!/usr/bin/env python3
"""Generate the OrangeGames native HUD fonts + Java glyph constants.

Replaces the BetterHud runtime: the plugin composes bossbar text using these
fonts; the existing betterhud_* overlay shaders decode the same position
encoding BetterHud used (element id in the high bits of glyph Y):

    ascent(id, y) = -(((1024 + id) << 13) + 4105 + y - 9)

id semantics baked into all overlay shaders' switch tables:
  1 = absolute from left edge, base layer
  2 = absolute from left edge, layer +1 (draws on top)
  3 = right-anchored

Outputs:
  assets/orangegames/font/hud.json            (images + space advances)
  assets/orangegames/font/text_<y>.json       (vanilla-ascii text at fixed y)
  assets/orangegames/textures/hud/head.png    (baked player head, if fetchable)
  <plugin>/hud/HudGlyphs.java                 (generated constants)
"""
import json
import struct
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "assets" / "orangegames" / "font"
TEX = ROOT / "assets" / "orangegames" / "textures" / "hud"
JAVA = Path(r"C:\Users\jackh\Development\OrangeGames\src\main\java\com\elongatedorange\orangegames\hud\HudGlyphs.java")

CALIB = 0  # global vertical calibration, adjust after in-game screenshot


def enc(elem_id, y):
    return -(((1024 + elem_id) << 13) + 4105 + y - 9 + CALIB)


def png_size(path):
    d = open(path, "rb").read(24)
    return struct.unpack(">II", d[16:24])


def tex_path(ref):
    ns, _, p = ref.partition(":")
    return ROOT / "assets" / ns / "textures" / p


# ---------------------------------------------------------------- player head
def bake_head():
    TEX.mkdir(parents=True, exist_ok=True)
    out = TEX / "head.png"
    try:
        from PIL import Image
        import base64, io
        prof = json.load(urllib.request.urlopen(
            "https://api.mojang.com/users/profiles/minecraft/Elongated_Orange", timeout=10))
        sess = json.load(urllib.request.urlopen(
            "https://sessionserver.mojang.com/session/minecraft/profile/" + prof["id"], timeout=10))
        tex_b64 = next(p for p in sess["properties"] if p["name"] == "textures")["value"]
        url = json.loads(base64.b64decode(tex_b64))["textures"]["SKIN"]["url"]
        skin = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=10).read())).convert("RGBA")
        head = skin.crop((8, 8, 16, 16))
        hat = skin.crop((40, 8, 48, 16))
        head.alpha_composite(hat)
        head.save(out)
        return "fetched skin for Elongated_Orange"
    except Exception as e:
        # fallback: reuse an existing 8x8 glyph so the pack stays valid
        import shutil
        shutil.copy2(tex_path("betterhud:glyph_online.png"), out)
        return f"head fetch failed ({type(e).__name__}: {e}) - placeholder used"


# ------------------------------------------------------------------- builders
SPACE_POWERS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
cp_next = [0xE800]


def nextcp():
    cp_next[0] += 1
    return cp_next[0]


spaces = {}
for p in SPACE_POWERS:
    spaces[chr(nextcp())] = p
for p in SPACE_POWERS:
    spaces[chr(nextcp())] = -p

img_providers = []
java_glyphs = []  # (NAME, char, advance)


def add_img(name, ref, elem_id, y, height=None):
    w, h = png_size(tex_path(ref))
    height = height if height is not None else h
    ch = chr(nextcp())
    adv = round(w * height / h) + 1
    img_providers.append({
        "type": "bitmap", "file": ref, "ascent": enc(elem_id, y),
        "height": height, "chars": [ch],
    })
    java_glyphs.append((name, ch, adv))


# --- element images (positions from the proven BetterHud default layout) ---
print(bake_head())

add_img("CARD_BG", "betterhud:image_top.png", 1, 29)            # 136x72, left 12
add_img("HEAD", "orangegames:hud/head.png", 2, 64, height=16)   # left 11
add_img("PING_GREEN", "betterhud:glyph_ping_green.png", 2, 90)  # left 58
add_img("PING_YELLOW", "betterhud:glyph_ping_yellow.png", 2, 90)
add_img("PING_RED", "betterhud:glyph_ping_red.png", 2, 90)
add_img("LOCATION", "betterhud:glyph_location.png", 2, 48)      # left 12
add_img("HEALTH_BG", "betterhud:image_xp.png", 1, 104)          # 122x11, left 19
add_img("SHIELD_BG", "betterhud:image_shield.png", 1, 116)      # left 19
for i in range(1, 26):
    add_img(f"HEALTH_FILL_{i}", f"betterhud:image_image_xpbar_left_25_{i}.png", 2, 105)
for i in range(1, 26):
    add_img(f"SHIELD_FILL_{i}", f"betterhud:image_image_shield_bar_left_25_{i}.png", 2, 117)

# ------------------------------------------------------------------ ascii font
ASCII_ROWS = [
    "\u00c0\u00c1\u00c2\u00c8\u00ca\u00cb\u00cd\u00d3\u00d4\u00d5\u00da\u00df\u00e3\u00f5\u011f\u0130",
    "\u0131\u0152\u0153\u015e\u015f\u0174\u0175\u017e\u0207\u0000\u0000\u0000\u0000\u0000\u0000\u0000",
    " !\"#$%&'()*+,-./",
    "0123456789:;<=>?",
    "@ABCDEFGHIJKLMNO",
    "PQRSTUVWXYZ[\\]^_",
    "`abcdefghijklmno",
    "pqrstuvwxyz{|}~\u0000",
] + ["\u0000" * 16] * 8

TEXT_YS = {"COORDS": 48, "NAME": 74, "PING": 90, "HEALTH": 110, "SHIELD": 122}

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

# ------------------------------------------------------------------ Java const
esc = lambda c: "\\u%04x" % ord(c) if ord(c) <= 0xFFFF else repr(c)


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
    + ", ".join(jstr(c) for c, v in spaces.items() if v > 0) + "};",
    "    public static final String[] NEG = {"
    + ", ".join(jstr(c) for c, v in spaces.items() if v < 0) + "};",
    "",
]
for name, ch, adv in java_glyphs:
    if "_FILL_" in name:
        continue
    lines.append(f"    public static final String {name} = {jstr(ch)}; public static final int {name}_W = {adv - 1};")
hf = [jstr(ch) for n, ch, a in java_glyphs if n.startswith("HEALTH_FILL_")]
sf = [jstr(ch) for n, ch, a in java_glyphs if n.startswith("SHIELD_FILL_")]
lines.append("    public static final String[] HEALTH_FILL = {" + ", ".join(hf) + "};")
lines.append("    public static final String[] SHIELD_FILL = {" + ", ".join(sf) + "};")
lines.append("}")
JAVA.parent.mkdir(parents=True, exist_ok=True)
JAVA.write_text("\n".join(lines), encoding="utf-8")


print(f"wrote hud.json ({len(img_providers)} image glyphs), {len(TEXT_YS)} text fonts, HudGlyphs.java")
