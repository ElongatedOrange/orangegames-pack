#!/usr/bin/env python3
"""Bake the Bedrock HUD pack (bedrock-hud/) styled to match the Java HUD.

Reads the Java HUD textures (assets/orangegames/textures/hud) for colors and
regenerates:
    font/glyph_E8.png   bar glyphs (health 0xE800.., shield 0xE810..)
    font/glyph_E9.png   0xE900 coords gear (kept), 0xE901 ping dot (white)
    textures/oghud_card.png / oghud_chip.png   from java card_bg / coords_bg
    ui/hud_screen.json  two-label overlay layout (bars behind, text in front)
    manifest.json       deterministic uuid/version from content hash
    dist/oghud_bedrock.zip

String contract with BedrockHUDManager (pitch = one text line, no padding):
    title    = "<gear> X .. Y .. Z ..\n\n\n<healthbar>\n<shieldbar>"
    subtitle = "<sp6><name>\n<sp6><dot> <ping> ms\n Health: N\n Shield: N"
    Subtitle line 2/3 overlay title line 3/4 (the bars) one pixel down.

Glyph sheets are 256x256 (16px cells); bar art sits in the calibrated band
rows y3..y10 so glyphs render text-sized. Segment art 8px wide, caps 4px:
bar = cap + 10 segments + cap. Bump: uuids auto-derive, no manual editing.

Usage: python tools/gen_bedrock_hud.py
"""
import hashlib
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
HUD = REPO / "bedrock-hud"
JAVA_HUD = REPO / "assets" / "orangegames" / "textures" / "hud"

HEALTH = (0xFF, 0x26, 0x20, 0xFF)
SHIELD = (0x35, 0x8A, 0xFF, 0xFF)
CELL = 16
BAND_TOP, BAND_BOT = 3, 10  # inclusive rows of the calibrated art band


def draw_seg(px, cx, cy, w, color, filled, cap=None):
    """Bar glyph art: outline top/bottom always; fill when filled; caps add
    the outer column with rounded corners like the java bar_*_bg outline."""
    for x in range(w):
        for y in range(BAND_TOP, BAND_BOT + 1):
            edge_row = y in (BAND_TOP, BAND_BOT)
            outer_col = (cap == "left" and x == 0) or (cap == "right" and x == w - 1)
            corner = outer_col and edge_row
            if corner:
                continue  # rounded corner notch
            if filled or edge_row or outer_col:
                px[cx + x, cy + y] = color


def bake_glyph_e8():
    img = Image.new("RGBA", (256, 256))
    px = img.load()
    for row, color in ((0xE800, HEALTH), (0xE810, SHIELD)):
        base_row, base_col = (row >> 4) & 0xF, row & 0xF
        cy = ((row >> 4) & 0xFF) * 0  # placeholder, computed below per glyph
        defs = [  # (col offset, width, filled, cap)
            (0, 8, True, None),   # filled segment
            (1, 8, False, None),  # empty segment
            (2, 4, True, "left"),
            (3, 4, False, "left"),
            (4, 4, True, "right"),
            (5, 4, False, "right"),
        ]
        for off, w, filled, cap in defs:
            code = row + off
            cx = (code & 0xF) * CELL
            cy = ((code >> 4) & 0xF) * CELL
            draw_seg(px, cx, cy, w, color, filled, cap)
    img.save(HUD / "font" / "glyph_E8.png")


def bake_glyph_e9():
    p = HUD / "font" / "glyph_E9.png"
    img = Image.open(p).convert("RGBA") if p.exists() else Image.new("RGBA", (256, 256))
    px = img.load()
    # 0xE901: white dot, tinted by the section color of its line
    cx, cy = 1 * CELL, 0 * CELL
    for x in range(1, 6):
        for y in range(BAND_TOP + 1, BAND_BOT):
            if (x, y) in ((1, BAND_TOP + 1), (5, BAND_TOP + 1),
                          (1, BAND_BOT - 1), (5, BAND_BOT - 1)):
                continue
            px[cx + x, cy + y] = (255, 255, 255, 255)
    img.save(p)


def label(name, offset, layer, color=(1.0, 1.0, 1.0)):
    binding = "#hud_title_text_string" if name == "bars" else "#hud_subtitle_text_string"
    return {
        f"oghud_{name}": {
            "type": "label",
            "color": list(color),
            "layer": layer,
            "anchor_from": "top_left",
            "anchor_to": "top_left",
            "offset": list(offset),
            "shadow": True,
            "text": binding,
            "bindings": [{"binding_name": binding, "binding_type": "global"}],
        }
    }


def image(name, texture, offset, size, layer, nineslice=None):
    el = {
        "type": "image",
        "texture": texture,
        "anchor_from": "top_left",
        "anchor_to": "top_left",
        "offset": list(offset),
        "size": list(size),
        "layer": layer,
    }
    if nineslice:
        el["nineslice_size"] = nineslice
    return {f"oghud_{name}": el}


def bake_glyph_ea():
    """0xEA00-0xEA02: the ORANGE rank prefix badge (LuckPerms prefix, chat/
    tab/nametags), sliced across three 16px cells. Bedrock maps glyph-page
    pixels 1:1 to logical pixels, so a big-cell page renders huge (verified
    in game); native-resolution slices in standard 16px cells render
    text-sized, and adjacent glyphs butt seamlessly exactly like the E8 bar
    segments. Java renders the whole badge from 0xEA00 and defines
    0xEA01/0xEA02 as zero-advance spaces, so one prefix string serves both
    editions. Source: textures/hud/orange_prefix.png (41x9)."""
    src = Image.open(JAVA_HUD / "orange_prefix.png").convert("RGBA")
    img = Image.new("RGBA", (256, 256))
    for i in range(3):
        x0 = i * CELL
        slice_w = min(CELL, src.width - x0)
        if slice_w <= 0:
            break
        part = src.crop((x0, 0, x0 + slice_w, src.height))
        img.paste(part, (i * CELL, BAND_TOP), part)  # cells (0,0..2)
    img.save(HUD / "font" / "glyph_EA.png")


def build_ui():
    # geometry: title line pitch is 10px. title lines: coords, blank, blank,
    # healthbar, shieldbar. subtitle: name, ping, " Health: N", " Shield: N".
    controls = [
        image("chip", "textures/oghud_chip", [6, 14], [108, 14], 51, 4),
        image("card", "textures/oghud_card", [6, 30], [122, 46], 51, 4),
        # Bedrock cannot draw a per-player head: its text has no hex colours
        # for the tinted-glyph trick Java uses, and live_player_renderer only
        # runs on the inventory screen. A neutral orange icon it is.
        image("head", "textures/oghud_head", [11, 30], [16, 16], 53),
        label("bars", [10, 18], 52),        # title: coords + bar glyph lines
        label("text", [10, 29], 54),        # subtitle: name/ping + bar text
    ]
    return {
        "namespace": "hud",
        "oghud_panel": {
            "type": "panel",
            "anchor_from": "top_left",
            "anchor_to": "top_left",
            "size": ["100%", "100%"],
            "layer": 50,
            "controls": controls,
        },
        "root_panel": {
            "modifications": [{
                "array_name": "controls",
                "operation": "insert_front",
                "value": [{"oghud@hud.oghud_panel": {}}],
            }],
        },
        "hud_title_text": {"visible": False},
        "hud_actionbar_text": {"visible": False},
    }


def main():
    bake_glyph_e8()
    bake_glyph_e9()
    bake_glyph_ea()
    shutil.copy(JAVA_HUD / "card_bg.png", HUD / "textures" / "oghud_card.png")
    shutil.copy(JAVA_HUD / "coords_bg.png", HUD / "textures" / "oghud_chip.png")
    # the old oghud_head.png was one player's baked skin
    shutil.copy(REPO / "assets" / "orangegames" / "textures" / "hud" / "og_icon.png",
                HUD / "textures" / "oghud_head.png")
    (HUD / "ui" / "hud_screen.json").write_text(
        json.dumps(build_ui(), indent=1), encoding="utf-8")

    h = hashlib.sha256()
    for p in sorted(HUD.rglob("*")):
        if p.is_file() and p.name != "manifest.json" and p.parent.name != "dist":
            h.update(p.relative_to(HUD).as_posix().encode())
            h.update(p.read_bytes())
    digest = h.hexdigest()
    version = [1, int(digest[:4], 16) % 100, int(digest[4:8], 16) % 100]

    def det_uuid(seed):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "orangegames-bedrock-hud:" + seed))

    (HUD / "manifest.json").write_text(json.dumps({
        "format_version": 2,
        "header": {
            "name": "OrangeGames HUD",
            "description": "Generated by gen_bedrock_hud.py",
            "uuid": det_uuid("header:" + digest),
            "version": version,
            "min_engine_version": [1, 16, 100],
        },
        "modules": [{
            "type": "resources",
            "uuid": det_uuid("module:" + digest),
            "version": version,
        }],
    }, indent=1), encoding="utf-8")

    dist = HUD / "dist"
    dist.mkdir(exist_ok=True)
    zip_path = dist / "oghud_bedrock.zip"
    files = sorted(p for p in HUD.rglob("*") if p.is_file() and p.parent.name != "dist")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(str(p.relative_to(HUD)).replace("\\", "/"),
                                   date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    print(f"baked HUD pack -> {zip_path} (version {version})")


if __name__ == "__main__":
    main()
