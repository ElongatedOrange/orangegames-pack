#!/usr/bin/env python3
"""Repair GeyserModelEngineExtension's generated_pack.zip cross-references.

Fixes (extension bugs in unhashed mode):
  1. entity textures.default points at "textures/entity/<model>" but files are
     written flat as "textures/entity/<texture_name>.png" -> rewrite paths.
  2. Multi-texture models get only ONE render controller (the last texture);
     rebuild the RC file with one controller per texture, part_visibility from
     the input config.json bindings, and wire both into the entity.

Usage: python fix_genpack.py <generated_pack.zip> <input_dir> <out_zip>
"""
import json
import sys
import zipfile
from pathlib import Path

src, input_dir, dst = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
zin = zipfile.ZipFile(src)
files = {n: zin.read(n) for n in zin.namelist()}

tex_stems = {n.split("/")[-1].removesuffix(".png"): n.removesuffix(".png")
             for n in files if n.startswith("textures/entity/")}

models = [n.split("/")[-1].removesuffix(".json") for n in files if n.startswith("entity/")]
for model in models:
    ent = json.loads(files[f"entity/{model}.json"])
    desc = ent["minecraft:client_entity"]["description"]
    # custom materials break on modern RenderDragon clients -> vanilla material
    desc["materials"] = {k: "entity_alphatest" for k in desc.get("materials", {"default": 1})}

    # textures present in the input folder for this model, in stable order
    mdir = input_dir / model
    model_texs = sorted(t.stem for t in mdir.glob("*.png")) if mdir.exists() else []
    model_texs = [t for t in model_texs if t in tex_stems]
    bindings = {}
    cfg = mdir / "config.json"
    if cfg.exists():
        bindings = json.loads(cfg.read_text()).get("bingingBones", {})

    if not model_texs:
        continue

    if len(model_texs) == 1:
        desc["textures"] = {"default": tex_stems[model_texs[0]]}
    else:
        # geometry bone list for part_visibility defaults
        geo = json.loads(files[f"models/entity/{model}.json"])
        all_bones = [b["name"] for b in geo["minecraft:geometry"][0]["bones"]]
        desc["textures"] = {t: tex_stems[t] for t in model_texs}
        controllers = {}
        rc_refs = []
        for t in model_texs:
            bones = bindings.get(t) or all_bones
            cid = f"controller.render.meg_{model}_{t}"
            controllers[cid] = {
                "geometry": f"Geometry.{model}",
                "materials": [{"*": "Material.default"}],
                "textures": [f"Texture.{t}"],
                "part_visibility": [{"*": False}] + [{b: True} for b in bones],
            }
            rc_refs.append(cid)
        files[f"render_controllers/{model}.json"] = json.dumps(
            {"format_version": "1.8.0", "render_controllers": controllers}, indent=1).encode()
        desc["render_controllers"] = rc_refs

    files[f"entity/{model}.json"] = json.dumps(ent, indent=1).encode()

# fresh manifest identity so Bedrock clients never reuse a stale cached pack
import uuid
mani = json.loads(files["manifest.json"])
mani["header"]["uuid"] = str(uuid.uuid4())
old_ver = mani["header"].get("version", [0, 0, 1])
new_ver = [old_ver[0], old_ver[1], old_ver[2] + 1]
mani["header"]["version"] = new_ver
for mod in mani.get("modules", []):
    mod["uuid"] = str(uuid.uuid4())
    mod["version"] = new_ver
files["manifest.json"] = json.dumps(mani, indent=1).encode()

# ---- verification pass: every entity texture/geometry/RC must resolve ----
problems = []
for model in models:
    d = json.loads(files[f"entity/{model}.json"])["minecraft:client_entity"]["description"]
    for key, path in d["textures"].items():
        if path + ".png" not in files:
            problems.append(f"{model}: texture {key} -> {path}.png MISSING")
    rc_ids = set()
    for n, data in files.items():
        if n.startswith("render_controllers/"):
            rc_ids |= set(json.loads(data)["render_controllers"].keys())
    for rc in d["render_controllers"]:
        if rc not in rc_ids:
            problems.append(f"{model}: RC {rc} MISSING")
    geo_ids = {json.loads(data)["minecraft:geometry"][0]["description"]["identifier"]
               for n, data in files.items() if n.startswith("models/entity/")}
    for g in d["geometry"].values():
        if g not in geo_ids:
            problems.append(f"{model}: geometry {g} MISSING")

if problems:
    print("PROBLEMS:")
    [print(" ", p) for p in problems]
    sys.exit(1)

with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for n, data in files.items():
        zout.writestr(n, data)
print(f"OK: {len(files)} files -> {dst} (all cross-references verified)")
