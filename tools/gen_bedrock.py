#!/usr/bin/env python3
"""Generate Geyser custom item mappings + Bedrock resource pack from this repo.

Source of truth:
    assets/orangegames/items/*.json        custom item definitions (item_model)
    assets/orangecosmetics/items/*.json    cosmetic hat definitions
    ../OrangeGames plugin source           base vanilla Material per item

Output (fully generated, do not hand-edit):
    bedrock-items/geyser_mappings.json     -> proxy custom_mappings/geyser_mappings.json
    bedrock-items/pack/                    unzipped pack for inspection
    bedrock-items/og_items.zip             -> proxy plugins/Geyser-Velocity/packs/og_items.zip

3D Java models become attachables using the java2bedrock bone convention:
    geyser_custom (pivot [0,8,0], slot binding) > _x > _y > _z (cubes)
    cube origin = [8 - to_x, from_y, from_z - 8]; rot = [-rx, -ry, rz]
    display transforms -> per-context animations (base offsets from java2bedrock)

Inventory icons for 3D models are software-rendered with the model's gui
display transform (painter-free z-buffer rasterizer, Pillow only).

Usage: python tools/gen_bedrock.py [--plugin-src ../OrangeGames]
"""
import argparse
import hashlib
import io
import json
import math
import re
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "bedrock-items"
PACK = OUT / "pack"

PACK_NAME = "OrangeGames Items"
ICON_SIZE = 32          # rendered inventory icon size for 3D models
ICON_SUPER = 4          # supersampling factor while rasterizing

# items referenced by the plugin that have no art in the pack (legacy, vanilla look)
# -> intentionally skipped, they render as their base item on both editions
KNOWN_ARTLESS = {
    "bandage", "battle_axe", "berserk_rage", "boomerang", "chainsaw",
    "energy_bar", "elixir_of_life", "angelic_elixir", "flame_lance",
    "iron_skin_elixir", "regen_potion", "soul_reaper", "strength_potion",
    "venom_dart", "thundergods_hammer",
}

# base materials for models applied outside ItemBuilder chains (listeners etc.)
EXTRA_MATERIALS = {
    "pebble": ("SNOWBALL", "UTILITY"),
    "chainsaw_active": ("NETHERITE_AXE", "MELEE"),
}

ARMOR_SLOTS = {  # EquipmentSlot -> (bedrock geometry slot, layer-visibility var, java layer dir, tex suffix)
    "HEAD": ("helmet", "helmet_layer_visible", "humanoid", "_1"),
    "CHEST": ("chestplate", "chest_layer_visible", "humanoid", "_1"),
    "LEGS": ("leggings", "leg_layer_visible", "humanoid_leggings", "_2"),
    "FEET": ("boots", "boot_layer_visible", "humanoid", "_1"),
}

CATEGORY_MAP = {  # plugin ItemCategory -> bedrock creative_category
    "MELEE": "equipment", "RANGED": "equipment", "HYBRID": "equipment",
    "ARMOR": "equipment", "TOOL": "equipment",
    "CONSUMABLE": "items", "UTILITY": "items",
}


# ---------------------------------------------------------------- manifest ----

def parse_plugin(plugin_src: Path):
    """model ref ('orangegames:club') -> (java item id, creative category)."""
    out = {}
    impl = plugin_src / "src/main/java/com/elongatedorange/orangegames/items/impl"
    for f in sorted(impl.glob("*.java")):
        text = f.read_text(encoding="utf-8")
        cat = None
        m = re.search(r"ItemCategory\.(\w+)", text)
        if m:
            cat = m.group(1)
        builders = [(m.start(), m.group(1))
                    for m in re.finditer(r"new ItemBuilder\(Material\.(\w+)", text)]
        for m in re.finditer(r'\.itemModel\("([\w:]+)"\)', text):
            prior = [b for b in builders if b[0] < m.start()]
            if not prior:
                continue
            out[m.group(1)] = ("minecraft:" + prior[-1][1].lower(),
                               CATEGORY_MAP.get(cat, "items"))
    for name, (mat, cat) in EXTRA_MATERIALS.items():
        out.setdefault("orangegames:" + name,
                       ("minecraft:" + mat.lower(), CATEGORY_MAP.get(cat, "items")))
    return out


def parse_armor(plugin_src: Path):
    """def name -> (EquipmentSlot, equipment asset id) for worn-armor rendering."""
    out = {}
    impl = plugin_src / "src/main/java/com/elongatedorange/orangegames/items/impl"
    for f in sorted(impl.glob("*.java")):
        text = f.read_text(encoding="utf-8")
        model = re.search(r'\.itemModel\("orangegames:([\w]+)"\)', text)
        slot = re.search(r"EquipmentSlot\.(\w+)", text)
        asset = re.search(r'assetId\(Key\.key\("orangegames:([\w]+)"\)', text)
        if model and slot and asset and slot.group(1) in ARMOR_SLOTS:
            out[model.group(1)] = (slot.group(1), asset.group(1))
    return out


def build_armor_attachable(ident, slot, tex_path):
    geo_slot, layer_var, _, _ = ARMOR_SLOTS[slot]
    return {
        "format_version": "1.8.0",
        "minecraft:attachable": {
            "description": {
                "identifier": ident,
                "materials": {"default": "armor", "enchanted": "armor_enchanted"},
                "textures": {"default": tex_path,
                             "enchanted": "textures/misc/enchanted_actor_glint"},
                "geometry": {"default": f"geometry.humanoid.armor.{geo_slot}"},
                "scripts": {"parent_setup": f"variable.{layer_var} = 0.0;"},
                "render_controllers": ["controller.render.armor"],
            },
        },
    }


def collect_defs():
    """Yield (namespace, def name, primary model ref, def path)."""
    for ns in ("orangegames", "orangecosmetics"):
        d = REPO / "assets" / ns / "items"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            yield ns, f.stem, primary_model(data.get("model", {})), f


def primary_model(node):
    """First (non-blocking) model ref in an item definition tree."""
    if not isinstance(node, dict):
        return None
    if node.get("type") == "minecraft:condition":
        return primary_model(node.get("on_false") or node.get("on_true"))
    if isinstance(node.get("model"), str):
        return node["model"]
    for v in node.values():
        if isinstance(v, dict):
            r = primary_model(v)
            if r:
                return r
    return None


def resolve_model(ref):
    ns, path = ref.split(":", 1)
    return REPO / "assets" / ns / "models" / (path + ".json")


def resolve_texture(ref):
    ns, path = ref.split(":", 1)
    return REPO / "assets" / ns / "textures" / (path + ".png")


def load_texture(ref):
    """Load a texture; animated (mcmeta) textures are cropped to frame 0."""
    p = resolve_texture(ref)
    img = Image.open(p).convert("RGBA")
    if p.with_suffix(".png.mcmeta").exists() and img.height > img.width:
        img = img.crop((0, 0, img.width, img.width))
    return img


# ------------------------------------------------------- geometry conversion ----

AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def build_atlas(model):
    """Stitch the model's face textures into one image.

    Returns (atlas image, {texture key -> (x_off, y_off, w, h)}).
    UVs in java models are 0..16 over each texture regardless of resolution.
    """
    refs = {}
    for key, ref in model.get("textures", {}).items():
        if key == "particle" and ref in model.get("textures", {}).values():
            pass  # particle usually duplicates a face texture; keep all keys
        refs[key] = ref
    # dedupe by ref so shared textures occupy one atlas slot
    unique = []
    for ref in refs.values():
        if ref not in unique:
            unique.append(ref)
    images = {ref: load_texture(ref) for ref in unique}
    width = max(im.width for im in images.values())
    height = sum(im.height for im in images.values())
    atlas = Image.new("RGBA", (width, height))
    place = {}
    y = 0
    for ref in unique:
        im = images[ref]
        atlas.paste(im, (0, y))
        place[ref] = (0, y, im.width, im.height)
        y += im.height
    key_place = {key: place[ref] for key, ref in refs.items()}
    return atlas, key_place


def face_uv_px(uv, slot):
    """Java 0..16 face uv -> atlas pixel uv + uv_size (flips preserved)."""
    x_off, y_off, w, h = slot
    u0, v0, u1, v1 = uv
    sx, sy = w / 16.0, h / 16.0
    return ([round(u0 * sx + x_off, 4), round(v0 * sy + y_off, 4)],
            [round((u1 - u0) * sx, 4), round((v1 - v0) * sy, 4)])


def convert_geometry(model, geo_id, atlas_size, key_place):
    cubes = []
    for el in model.get("elements", []):
        fx, fy, fz = el["from"]
        tx, ty, tz = el["to"]
        cube = {
            "origin": [round(8 - tx, 4), round(fy, 4), round(fz - 8, 4)],
            "size": [round(tx - fx, 4), round(ty - fy, 4), round(tz - fz, 4)],
        }
        rot = el.get("rotation")
        if rot and rot.get("angle"):
            r = [0.0, 0.0, 0.0]
            r[AXIS_INDEX[rot["axis"]]] = rot["angle"]
            cube["rotation"] = [-r[0], -r[1], r[2]]
            px, py, pz = rot.get("origin", [8, 8, 8])
            cube["pivot"] = [round(8 - px, 4), round(py, 4), round(pz - 8, 4)]
        faces = {}
        for face, data in el.get("faces", {}).items():
            uv = data.get("uv")
            tex = data.get("texture", "#0").lstrip("#")
            if uv is None or tex not in key_place:
                continue
            uv_px, uv_size = face_uv_px(uv, key_place[tex])
            faces[face] = {"uv": uv_px, "uv_size": uv_size}
        if faces:
            cube["uv"] = faces
        cubes.append(cube)
    bones = [
        {"name": "geyser_custom", "pivot": [0, 8, 0],
         "binding": "c.item_slot == 'head' ? 'head' : q.item_slot_to_bone_name(c.item_slot)"},
        {"name": "geyser_custom_x", "parent": "geyser_custom", "pivot": [0, 8, 0]},
        {"name": "geyser_custom_y", "parent": "geyser_custom_x", "pivot": [0, 8, 0]},
        {"name": "geyser_custom_z", "parent": "geyser_custom_y", "pivot": [0, 8, 0],
         "cubes": cubes},
    ]
    return {
        "format_version": "1.16.0",
        "minecraft:geometry": [{
            "description": {
                "identifier": geo_id,
                "texture_width": atlas_size[0],
                "texture_height": atlas_size[1],
                "visible_bounds_width": 4,
                "visible_bounds_height": 4.5,
                "visible_bounds_offset": [0, 0.75, 0],
            },
            "bones": bones,
        }],
    }


# ------------------------------------------------- display -> attachable anim ----

def display_bones(disp, scale_mult=1.0):
    """Sub-bone values replicating a java display transform (java2bedrock math)."""
    rot = disp.get("rotation", [0, 0, 0])
    tr = disp.get("translation", [0, 0, 0])
    sc = disp.get("scale")
    bones = {}
    if any(rot):
        bones["geyser_custom_x"] = {"rotation": [-rot[0], 0, 0]}
        bones["geyser_custom_y"] = {"rotation": [0, -rot[1], 0]}
        bones["geyser_custom_z"] = {"rotation": [0, 0, rot[2]]}
    x = bones.setdefault("geyser_custom_x", {})
    if any(tr) or scale_mult != 1.0:
        x["position"] = [round(-tr[0] * scale_mult, 4),
                         round(tr[1] * scale_mult, 4),
                         round(tr[2] * scale_mult, 4)]
    if sc is not None:
        x["scale"] = [round(s * scale_mult, 4) for s in sc]
    elif scale_mult != 1.0:
        x["scale"] = scale_mult
    return {k: v for k, v in bones.items() if v}


def build_animations(model, anim_prefix):
    disp = model.get("display", {})
    tp_r = disp.get("thirdperson_righthand", {})
    tp_l = disp.get("thirdperson_lefthand", tp_r)
    fp_r = disp.get("firstperson_righthand", {})
    fp_l = disp.get("firstperson_lefthand", fp_r)
    head = disp.get("head", {})

    def ctx(base, java_disp, scale_mult=1.0):
        bones = display_bones(java_disp, scale_mult)
        if base:
            bones["geyser_custom"] = base
        return {"loop": True, "bones": bones} if bones else {"loop": True}

    anims = {
        "third_person_main_hand": ctx({"rotation": [90, 0, 0], "position": [0, 13, -3]}, tp_r),
        "third_person_off_hand": ctx({"rotation": [90, 0, 0], "position": [0, 13, -3]}, tp_l),
        "first_person_main_hand": ctx(
            {"rotation": [90, 60, -40], "position": [4, 10, 4], "scale": 1.5}, fp_r),
        "first_person_off_hand": ctx(
            {"rotation": [90, 60, -40], "position": [4, 10, 4], "scale": 1.5}, fp_l),
        "head": ctx({"position": [0, 19.9, 0]}, head, 0.625),
    }
    return {"format_version": "1.8.0",
            "animations": {f"{anim_prefix}.{k}": v for k, v in anims.items()}}


def build_attachable(ident, geo_id, anim_prefix, tex_path):
    contexts = {
        "third_person_main_hand": "v.main_hand && !c.is_first_person",
        "third_person_off_hand": "v.off_hand && !c.is_first_person",
        "first_person_main_hand": "v.main_hand && c.is_first_person",
        "first_person_off_hand": "v.off_hand && c.is_first_person",
        "head": "v.head",
    }
    return {
        "format_version": "1.10.0",
        "minecraft:attachable": {
            "description": {
                "identifier": ident,
                "materials": {"default": "entity_alphatest",
                              "enchanted": "entity_alphatest_glint"},
                "textures": {"default": tex_path,
                             "enchanted": "textures/misc/enchanted_actor_glint"},
                "geometry": {"default": geo_id},
                "animations": {k: f"{anim_prefix}.{k}" for k in contexts},
                "scripts": {
                    "pre_animation": [
                        "v.main_hand = c.item_slot == 'main_hand';",
                        "v.off_hand = c.item_slot == 'off_hand';",
                        "v.head = c.item_slot == 'head';",
                    ],
                    "animate": [{k: v} for k, v in contexts.items()],
                },
                "render_controllers": ["controller.render.item_default"],
            },
        },
    }


# ------------------------------------------------------------ icon renderer ----

def rot_matrix_xyz(rx, ry, rz):
    """Vanilla display rotation: Quaternionf().rotationXYZ -> R = Rx*Ry*Rz."""
    rx, ry, rz = (math.radians(a) for a in (rx, ry, rz))
    cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                              math.sin(ry), math.cos(rz), math.sin(rz))
    # Rx*Ry*Rz
    return [
        [cy * cz, -cy * sz, sy],
        [cz * sx * sy + cx * sz, cx * cz - sx * sy * sz, -cy * sx],
        [-cx * cz * sy + sx * sz, cz * sx + cx * sy * sz, cx * cy],
    ]


def mat_vec(m, v):
    return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]


def axis_rot_matrix(axis, angle):
    a = {"x": (angle, 0, 0), "y": (0, angle, 0), "z": (0, 0, angle)}[axis]
    return rot_matrix_xyz(*a)


FACE_CORNERS = {
    # (vertex selector per corner) in UV order: (u0,v0) (u1,v0) (u1,v1) (u0,v1)
    # java face uv corners map: top-left, top-right, bottom-right, bottom-left
    "north": lambda f, t: [(t[0], t[1], f[2]), (f[0], t[1], f[2]),
                           (f[0], f[1], f[2]), (t[0], f[1], f[2])],
    "south": lambda f, t: [(f[0], t[1], t[2]), (t[0], t[1], t[2]),
                           (t[0], f[1], t[2]), (f[0], f[1], t[2])],
    "west": lambda f, t: [(f[0], t[1], f[2]), (f[0], t[1], t[2]),
                          (f[0], f[1], t[2]), (f[0], f[1], f[2])],
    "east": lambda f, t: [(t[0], t[1], t[2]), (t[0], t[1], f[2]),
                          (t[0], f[1], f[2]), (t[0], f[1], t[2])],
    "up": lambda f, t: [(f[0], t[1], f[2]), (t[0], t[1], f[2]),
                        (t[0], t[1], t[2]), (f[0], t[1], t[2])],
    "down": lambda f, t: [(f[0], f[1], t[2]), (t[0], f[1], t[2]),
                          (t[0], f[1], f[2]), (f[0], f[1], f[2])],
}
FACE_SHADE = {"up": 1.0, "down": 0.5, "north": 0.8, "south": 0.8,
              "west": 0.6, "east": 0.6}


def render_icon(model, atlas, key_place, size=ICON_SIZE):
    """Rasterize the model with its gui display transform to an RGBA icon."""
    gui = model.get("display", {}).get("gui", {})
    rot = gui.get("rotation", [30, 225, 0])
    tr = gui.get("translation", [0, 0, 0])
    sc = gui.get("scale", [0.625, 0.625, 0.625])
    guimat = rot_matrix_xyz(*rot)

    tris = []  # (verts2d, depth per vert, uv per vert, shade)
    for el in model.get("elements", []):
        f, t = el["from"], el["to"]
        elrot = el.get("rotation")
        for face, data in el.get("faces", {}).items():
            uv = data.get("uv")
            tex = data.get("texture", "#0").lstrip("#")
            if uv is None or tex not in key_place:
                continue
            corners = [list(c) for c in FACE_CORNERS[face](f, t)]
            if elrot and elrot.get("angle"):
                m = axis_rot_matrix(elrot["axis"], elrot["angle"])
                o = elrot.get("origin", [8, 8, 8])
                corners = [[a + b for a, b in
                            zip(mat_vec(m, [c[i] - o[i] for i in range(3)]), o)]
                           for c in corners]
            # gui transform around model center, then screen-space translation
            pts = []
            for c in corners:
                v = [(c[i] - 8) * sc[i] for i in range(3)]
                v = mat_vec(guimat, v)
                pts.append([v[0] + tr[0], v[1] + tr[1], v[2] + tr[2]])
            # rotate uv for MC uv-lock corner order (java uv already oriented)
            x_off, y_off, w, h = key_place[tex]
            sx, sy = w / 16.0, h / 16.0
            u0, v0, u1, v1 = uv
            uvs = [(u0 * sx + x_off, v0 * sy + y_off),
                   (u1 * sx + x_off, v0 * sy + y_off),
                   (u1 * sx + x_off, v1 * sy + y_off),
                   (u0 * sx + x_off, v1 * sy + y_off)]
            if "rotation" in data:
                turns = (data["rotation"] // 90) % 4
                uvs = uvs[turns:] + uvs[:turns]
            shade = FACE_SHADE[face]
            for a, b, c in ((0, 1, 2), (0, 2, 3)):
                tris.append(([pts[i] for i in (a, b, c)],
                             [uvs[i] for i in (a, b, c)], shade))

    canvas = size * ICON_SUPER
    half = canvas / 2.0
    # model spans 16px in a 16px gui slot at scale 1; leave a small margin
    factor = canvas / 19.0
    off_x = off_y = 0.0

    # Models larger than the standard 16-unit cube (long weapons, tools) would
    # project off-canvas. Shrink and recentre those to fit; models that already
    # fit are left exactly as they were.
    if tris:
        xs_all = [p[0] for pts, _, _ in tris for p in pts]
        ys_all = [p[1] for pts, _, _ in tris for p in pts]
        span = max(max(xs_all) - min(xs_all), max(ys_all) - min(ys_all))
        if span * factor > canvas * 0.94:
            factor = canvas * 0.94 / span
            off_x = (max(xs_all) + min(xs_all)) / 2.0
            off_y = (max(ys_all) + min(ys_all)) / 2.0
    px = [[(0, 0, 0, 0)] * canvas for _ in range(canvas)]
    zbuf = [[-1e9] * canvas for _ in range(canvas)]
    apx = atlas.load()
    aw, ah = atlas.size
    for pts, uvs, shade in tris:
        xs = [half + (p[0] - off_x) * factor for p in pts]
        ys = [half - (p[1] - off_y) * factor for p in pts]
        zs = [p[2] for p in pts]
        minx = max(int(min(xs)), 0)
        maxx = min(int(max(xs)) + 1, canvas - 1)
        miny = max(int(min(ys)), 0)
        maxy = min(int(max(ys)) + 1, canvas - 1)
        if minx > maxx or miny > maxy:
            continue
        x0, y0, x1, y1, x2, y2 = xs[0], ys[0], xs[1], ys[1], xs[2], ys[2]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-9:
            continue
        for yy in range(miny, maxy + 1):
            for xx in range(minx, maxx + 1):
                l0 = ((y1 - y2) * (xx + 0.5 - x2) + (x2 - x1) * (yy + 0.5 - y2)) / denom
                l1 = ((y2 - y0) * (xx + 0.5 - x2) + (x0 - x2) * (yy + 0.5 - y2)) / denom
                l2 = 1 - l0 - l1
                if l0 < -1e-6 or l1 < -1e-6 or l2 < -1e-6:
                    continue
                z = l0 * zs[0] + l1 * zs[1] + l2 * zs[2]
                if z <= zbuf[yy][xx]:
                    continue
                u = l0 * uvs[0][0] + l1 * uvs[1][0] + l2 * uvs[2][0]
                v = l0 * uvs[0][1] + l1 * uvs[1][1] + l2 * uvs[2][1]
                tu = min(max(int(u), 0), aw - 1)
                tv = min(max(int(v), 0), ah - 1)
                r, g, b, a = apx[tu, tv]
                if a < 128:
                    continue
                zbuf[yy][xx] = z
                px[yy][xx] = (int(r * shade), int(g * shade), int(b * shade), 255)
    img = Image.new("RGBA", (canvas, canvas))
    img.putdata([p for row in px for p in row])
    return img.resize((size, size), Image.BOX)


# ------------------------------------------------------------------- output ----

def det_uuid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "orangegames-bedrock:" + seed))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def zip_pack(pack_dir, zip_path):
    files = sorted(p for p in pack_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(str(p.relative_to(pack_dir)).replace("\\", "/"),
                                   date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())


def title(slug):
    return slug.replace("_", " ").title()


def main():
    ap = argparse.ArgumentParser()
    # since the multi-module split the paper sources live one level down
    ap.add_argument("--plugin-src",
                    default=str(REPO.parent / "OrangeGames" / "orangegames-paper"))
    args = ap.parse_args()

    materials = parse_plugin(Path(args.plugin_src))
    armor = parse_armor(Path(args.plugin_src))
    if PACK.exists():
        shutil.rmtree(PACK)
    (PACK / "textures" / "items" / "og").mkdir(parents=True)
    count_armor = 0

    mappings = {}          # java item id -> [definitions]
    texture_data = {}      # item_texture.json entries
    warnings = []
    count_flat = count_3d = 0

    for ns, name, model_ref, def_path in collect_defs():
        component = f"{ns}:{name}"
        ident = component
        icon_key = f"{ns}.{name}"
        if not model_ref:
            warnings.append(f"{def_path.name}: no model ref found, skipped")
            continue
        model_path = resolve_model(model_ref)
        if not model_path.exists():
            warnings.append(f"{component}: model {model_ref} missing, skipped")
            continue
        model = json.loads(model_path.read_text(encoding="utf-8"))

        if ns == "orangecosmetics":
            java_item, category = "minecraft:stick", "equipment"
        elif component in materials:
            java_item, category = materials[component]
        else:
            warnings.append(f"{component}: no plugin material found, skipped")
            continue

        is_3d = bool(model.get("elements"))
        handheld = model.get("parent") == "minecraft:item/handheld"

        if is_3d:
            count_3d += 1
            atlas, key_place = build_atlas(model)
            geo_id = f"geometry.og.{name}"
            anim_prefix = f"animation.og.{name}"
            tex_rel = f"textures/attachables/og/{name}"
            geo = convert_geometry(model, geo_id, atlas.size, key_place)
            write_json(PACK / "models" / "entity" / f"og_{name}.geo.json", geo)
            write_json(PACK / "animations" / f"og_{name}.animation.json",
                       build_animations(model, anim_prefix))
            write_json(PACK / "attachables" / f"og_{name}.json",
                       build_attachable(ident, geo_id, anim_prefix, tex_rel))
            (PACK / "textures" / "attachables" / "og").mkdir(parents=True, exist_ok=True)
            atlas.save(PACK / (tex_rel + ".png"))
            icon = render_icon(model, atlas, key_place)
            icon.save(PACK / "textures" / "items" / "og" / f"{name}.png")
        else:
            count_flat += 1
            layer0 = model.get("textures", {}).get("layer0")
            if not layer0:
                warnings.append(f"{component}: flat model without layer0, skipped")
                continue
            src = resolve_texture(layer0)
            if not src.exists():
                warnings.append(f"{component}: texture {layer0} missing, skipped")
                continue
            shutil.copy(src, PACK / "textures" / "items" / "og" / f"{name}.png")

        # worn-armor rendering: vanilla-style armor attachable over the java
        # equipment layer texture (bedrock uses the same 64x32 layout)
        if name in armor:
            slot, asset = armor[name]
            _, _, layer_dir, suffix = ARMOR_SLOTS[slot]
            layer_src = (REPO / "assets" / "orangegames" / "textures" / "entity"
                         / "equipment" / layer_dir / f"{asset}.png")
            if layer_src.exists():
                count_armor += 1
                tex_rel = f"textures/models/armor/og/{asset}{suffix}"
                dst = PACK / (tex_rel + ".png")
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(layer_src, dst)
                write_json(PACK / "attachables" / f"og_armor_{name}.json",
                           build_armor_attachable(ident, slot, tex_rel))
            else:
                warnings.append(f"{component}: armor asset {asset} has no "
                                f"{layer_dir} layer texture, worn look skipped")

        texture_data[icon_key] = {"textures": [f"textures/items/og/{name}"]}
        entry = {
            "type": "definition",
            "model": component,
            "bedrock_identifier": ident,
            "display_name": title(name),
            "bedrock_options": {
                "icon": icon_key,
                "allow_offhand": True,
                "display_handheld": bool(is_3d or handheld),
                "creative_category": category,
            },
        }
        mappings.setdefault(java_item, []).append(entry)

    write_json(PACK / "textures" / "item_texture.json", {
        "resource_pack_name": PACK_NAME,
        "texture_name": "atlas.items",
        "texture_data": dict(sorted(texture_data.items())),
    })

    # deterministic manifest: uuids/version derive from content so any change
    # busts the Bedrock client cache automatically
    h = hashlib.sha256()
    for p in sorted(PACK.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(PACK).as_posix().encode())
            h.update(p.read_bytes())
    digest = h.hexdigest()
    version = [1, int(digest[:4], 16) % 100, int(digest[4:8], 16) % 100]
    write_json(PACK / "manifest.json", {
        "format_version": 2,
        "header": {
            "name": PACK_NAME,
            "description": "Generated from orangegames-pack (gen_bedrock.py)",
            "uuid": det_uuid("header:" + digest),
            "version": version,
            "min_engine_version": [1, 16, 100],
        },
        "modules": [{
            "type": "resources",
            "uuid": det_uuid("module:" + digest),
            "version": version,
        }],
    })

    write_json(OUT / "geyser_mappings.json", {
        "format_version": 2,
        "items": {k: mappings[k] for k in sorted(mappings)},
    })
    zip_pack(PACK, OUT / "og_items.zip")

    # ------------------------------------------------------------ validation
    errors = []
    for java_item, entries in mappings.items():
        for e in entries:
            icon = e["bedrock_options"]["icon"]
            if icon not in texture_data:
                errors.append(f"{e['model']}: icon {icon} not in item_texture.json")
            for tex in texture_data.get(icon, {}).get("textures", []):
                if not (PACK / (tex + ".png")).exists():
                    errors.append(f"{e['model']}: texture file {tex}.png missing")
    for att in (PACK / "attachables").glob("*.json"):
        desc = json.loads(att.read_text(encoding="utf-8"))["minecraft:attachable"]["description"]
        if att.stem.startswith("og_armor_"):  # vanilla geometry, only check texture
            if not (PACK / (desc["textures"]["default"] + ".png")).exists():
                errors.append(f"{att.name}: armor layer texture missing")
            continue
        geo_file = PACK / "models" / "entity" / (att.stem + ".geo.json")
        geo = json.loads(geo_file.read_text(encoding="utf-8"))["minecraft:geometry"][0]
        if geo["description"]["identifier"] != desc["geometry"]["default"]:
            errors.append(f"{att.name}: geometry id mismatch")
        if not (PACK / (desc["textures"]["default"] + ".png")).exists():
            errors.append(f"{att.name}: attachable texture missing")
        tw, th = geo["description"]["texture_width"], geo["description"]["texture_height"]
        for bone in geo["bones"]:
            for cube in bone.get("cubes", []):
                for face, fuv in cube.get("uv", {}).items():
                    for lo, span, limit in ((fuv["uv"][0], fuv["uv_size"][0], tw),
                                            (fuv["uv"][1], fuv["uv_size"][1], th)):
                        a, b = sorted((lo, lo + span))
                        if a < -0.01 or b > limit + 0.01:
                            errors.append(f"{att.name}: uv out of bounds on {face}")

    total = sum(len(v) for v in mappings.values())
    print(f"mapped {total} items ({count_3d} 3D, {count_flat} flat, "
          f"{count_armor} with worn-armor attachables) across {len(mappings)} base items")
    for w in warnings:
        expected = any(k in w for k in KNOWN_ARTLESS)
        print(("  [expected] " if expected else "  [warn] ") + w)
    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print("validation OK ->", OUT)


if __name__ == "__main__":
    main()
