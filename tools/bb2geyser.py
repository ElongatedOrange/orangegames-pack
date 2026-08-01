#!/usr/bin/env python3
"""Convert ModelEngine .bbmodel blueprints to GeyserModelEngine input folders.

Output structure (what GeyserModelEngineExtension / PackGenerator expects):
    <out>/<model_id>/<model_id>.geo.json    (Bedrock minecraft:geometry)
    <out>/<model_id>/<model_id>.animation.json
    <out>/<model_id>/<texture>.png

Coordinate transforms (Blockbench/Java -> Bedrock entity geometry):
    cube origin   = [-(to_x), from_y, from_z]   (X mirrored)
    pivot         = [-p_x, p_y, p_z]
    cube/bone rot = [-r_x, -r_y, r_z]
    anim rotation = [-x, -y, z]; anim position = [-x, y, z]; scale unchanged

Usage: python bb2geyser.py <bbmodel_dir> <out_dir>
"""
import base64
import json
import sys
from pathlib import Path


def neg(v):
    return -v if isinstance(v, (int, float)) else f"-({v})"


def conv_cube(el):
    fx, fy, fz = el["from"]
    tx, ty, tz = el["to"]
    cube = {
        "origin": [round(-tx, 4), round(fy, 4), round(fz, 4)],
        "size": [round(tx - fx, 4), round(ty - fy, 4), round(tz - fz, 4)],
    }
    if el.get("inflate"):
        cube["inflate"] = el["inflate"]
    if el.get("rotation") and any(el["rotation"]):
        rx, ry, rz = el["rotation"]
        cube["rotation"] = [-rx, -ry, rz]
    if el.get("origin") and (el.get("rotation") and any(el["rotation"])):
        px, py, pz = el["origin"]
        cube["pivot"] = [-px, py, pz]
    faces = {}
    for face, data in el.get("faces", {}).items():
        uv = data.get("uv")
        if not uv or data.get("texture") is None:
            continue
        u0, v0, u1, v1 = uv
        faces[face] = {"uv": [round(u0, 4), round(v0, 4)],
                       "uv_size": [round(u1 - u0, 4), round(v1 - v0, 4)]}
    if faces:
        cube["uv"] = faces
    return cube


def walk_outliner(node, parent, bones, elements_by_uuid, groups_by_uuid):
    """Recursively convert Blockbench outliner groups to Bedrock bones."""
    if isinstance(node, str):  # loose cube at root - goes to parent bone
        return [node]
    # newer bbmodels keep group metadata in a separate "groups" list
    meta = groups_by_uuid.get(node.get("uuid"), {})
    node = {**meta, **{k: v for k, v in node.items() if k != "children"},
            "children": node.get("children", [])}
    name = node.get("name", "bone").lower().replace(" ", "_")
    while any(b["name"] == name for b in bones):
        name += "_"
    px, py, pz = node.get("origin", [0, 0, 0])
    bone = {"name": name, "pivot": [-px, py, pz]}
    if parent:
        bone["parent"] = parent
    rot = node.get("rotation", [0, 0, 0])
    if any(rot):
        bone["rotation"] = [-rot[0], -rot[1], rot[2]]
    cubes_by_tex = {}
    bones.append(bone)
    for child in node.get("children", []):
        if isinstance(child, str):
            el = elements_by_uuid.get(child)
            if el is not None and el.get("type", "cube") == "cube":
                ti = CTX["el_tex"].get(el["uuid"], 0)
                cubes_by_tex.setdefault(ti, []).append(conv_cube(el))
        else:
            walk_outliner(child, name, bones, elements_by_uuid, groups_by_uuid)
    # non-primary textures get synthetic sub-bones so render controllers can
    # split part_visibility per texture
    for ti, cubes in sorted(cubes_by_tex.items()):
        if ti == 0 or CTX["n_tex"] == 1:
            bone["cubes"] = bone.get("cubes", []) + cubes
            CTX["bind"].setdefault(ti, set()).add(name)
        else:
            sub = {"name": f"{name}_t{ti}", "parent": name,
                   "pivot": list(bone["pivot"]), "cubes": cubes}
            bones.append(sub)
            CTX["bind"].setdefault(ti, set()).add(sub["name"])
    return []


CTX = {"el_tex": {}, "n_tex": 1, "bind": {}}


def conv_geometry(bb, model_id):
    res = bb.get("resolution", {"width": 64, "height": 64})
    elements_by_uuid = {e["uuid"]: e for e in bb.get("elements", [])}
    groups_by_uuid = {g["uuid"]: g for g in bb.get("groups", []) if isinstance(g, dict)}
    textures = [t for t in bb.get("textures", []) if t.get("source", "").startswith("data:image")]
    el_tex = {}
    for el in bb.get("elements", []):
        idxs = [f.get("texture") for f in el.get("faces", {}).values() if f.get("texture") is not None]
        el_tex[el["uuid"]] = max(set(idxs), key=idxs.count) if idxs else 0
    CTX.update(el_tex=el_tex, n_tex=len(textures), bind={})
    bones = []
    loose = []
    for node in bb.get("outliner", []):
        loose += walk_outliner(node, None, bones, elements_by_uuid, groups_by_uuid)
    if loose:  # root-level cubes get a synthetic bone
        root = {"name": "root", "pivot": [0, 0, 0],
                "cubes": [conv_cube(elements_by_uuid[u]) for u in loose
                          if u in elements_by_uuid]}
        bones.insert(0, root)
    vb = bb.get("visible_box", [1, 1, 0])
    bindings = {}
    if len(textures) > 1:
        for ti, bset in CTX["bind"].items():
            if ti < len(textures):
                bindings[textures[ti]["name"].replace(".png", "")] = bset
    return bindings, {
        "format_version": "1.16.0",
        "minecraft:geometry": [{
            "description": {
                "identifier": f"geometry.{model_id}",
                "texture_width": res["width"],
                "texture_height": res["height"],
                "visible_bounds_width": vb[0] * 2,
                "visible_bounds_height": vb[1] * 2,
                "visible_bounds_offset": [0, vb[2], 0],
            },
            "bones": bones,
        }],
    }


LOOP = {"loop": True, "hold": "hold_on_last_frame", "once": False}
CHANNEL_XF = {
    "rotation": lambda x, y, z: [neg(x), neg(y), z],
    "position": lambda x, y, z: [neg(x), y, z],
    "scale": lambda x, y, z: [x, y, z],
}


def kf_value(dp):
    def num(v):
        if isinstance(v, str):
            v = v.strip()
            try:
                return float(v)
            except ValueError:
                return v  # molang expression, keep as string
        return v
    return num(dp.get("x", 0)), num(dp.get("y", 0)), num(dp.get("z", 0))


def conv_animations(bb, model_id):
    out = {}
    for anim in bb.get("animations", []):
        bones = {}
        for animator in anim.get("animators", {}).values():
            if animator.get("type", "bone") != "bone":
                continue
            bname = animator["name"].lower().replace(" ", "_")
            channels = {}
            for kf in sorted(animator.get("keyframes", []), key=lambda k: k["time"]):
                ch = kf["channel"]
                if ch not in CHANNEL_XF:
                    continue
                x, y, z = kf_value(kf["data_points"][0])
                val = CHANNEL_XF[ch](x, y, z)
                t = f"{round(kf['time'], 4):g}"
                entry = channels.setdefault(ch, {})
                if kf.get("interpolation") == "catmullrom":
                    entry[t] = {"post": val, "lerp_mode": "catmullrom"}
                else:
                    entry[t] = val
            if channels:
                bones[bname] = channels
        a = {"loop": LOOP.get(anim.get("loop", "once"), False),
             "animation_length": anim.get("length", 1)}
        if bones:
            a["bones"] = bones
        out[anim["name"].replace(" ", "_")] = a
    return {"format_version": "1.8.0", "animations": out} if out else None


def convert(bb_path, out_root):
    bb = json.load(open(bb_path, encoding="utf-8"))
    model_id = bb_path.stem.lower()
    out = out_root / model_id
    out.mkdir(parents=True, exist_ok=True)
    bindings, geo = conv_geometry(bb, model_id)
    json.dump(geo, open(out / f"{model_id}.geo.json", "w", encoding="utf-8"), indent=1)
    anims = conv_animations(bb, model_id)
    if anims:
        json.dump(anims, open(out / f"{model_id}.animation.json", "w", encoding="utf-8"), indent=1)
    for tex in bb.get("textures", []):
        src = tex.get("source", "")
        if src.startswith("data:image"):
            data = base64.b64decode(src.split(",", 1)[1])
            name = tex["name"]
            if not name.endswith(".png"):
                name += ".png"
            (out / name).write_bytes(data)
    if len(bindings) > 1:
        json.dump({"bingingBones": {k: sorted(v) for k, v in bindings.items()}},
                  open(out / "config.json", "w", encoding="utf-8"), indent=1)
    n_anim = len(anims["animations"]) if anims else 0
    print(f"{model_id}: {sum(len(b.get('cubes', [])) for b in geo['minecraft:geometry'][0]['bones'])} cubes, "
          f"{len(geo['minecraft:geometry'][0]['bones'])} bones, {n_anim} animations")


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "input")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "converted")
    for f in sorted(src.glob("*.bbmodel")):
        convert(f, dst)
