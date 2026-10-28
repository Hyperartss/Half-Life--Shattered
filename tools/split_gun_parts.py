#!/usr/bin/env python3
"""Put each viewmodel's gun on bones of its own, with one bone per moving part.

The weapon meshes came in rigid on a hand bone (the deagle on `Hand`, the
wrench on `ValveBiped.Bip01_R_Hand`). This adds a gun bone (child of that
hand, at the bind pose, so every existing sequence looks exactly the same)
and moves the weapon's vertices onto it, then gives each moving part --
found as a connected piece of the mesh -- its own bone under the gun bone,
at a pivot that suits how the part moves:

  v_deagle   Deagle_Gun   frame, grip, pins (at the old `Python` bone, so the
                          muzzle attachment keeps the same numbers)
               Deagle_Slide      slide + rear sight + safeties (slides along Y)
               Deagle_Barrel     barrel + front sight
               Deagle_Hammer     pivot at the hammer pin (rotate about X)
               Deagle_Trigger    pivot at the top of the trigger
               Deagle_Mag        magazine base plate (drops along -Z)
               Deagle_SlideStop  slide stop lever
  v_wrench   Wrench       handle + fixed heel jaw (pivot at the grip)
               Wrench_HookJaw    hook jaw + threaded shank (slides along Z)
               Wrench_Nut        adjusting nut (spins about Z)

New bones have no rotation relative to the model (local X right/left, Y along
the barrel, Z up), except Deagle_Gun which copies `Python`.

    python3 tools/split_gun_parts.py v_deagle v_wrench          # in place
    python3 tools/split_gun_parts.py --dry-run v_wrench

Works on Blender/<weapon>/anims (ref + every sequence) and on the shipping
mesh modelsrc/<weapon>/<weapon>_ref.smd. Originals go to
Blender/_backup_before_gun_bones/ and *.before_gun_bones.smd. A weapon that
already has its gun bone is skipped.
"""
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_shephard_arms import Smd, add_bones_to_sequence, matrix_to_smd  # noqa: E402

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_MATERIALS = ("shephard_arms",)

# Parts are picked by the centre of a connected piece of the mesh (bind pose,
# model units). `pivot` is where the bone sits, as a fraction of the part's
# bounding box (0 = min, 1 = max on each axis), or "centre".
RECIPES = {
    "v_deagle": {
        "gun": "Deagle_Gun",
        "on": "Hand",
        "gun_matrix_from": "Python",
        # tools/build_deagle_on_pistol.py moves these parts onto v_pistol's
        # gun bones; after that there is nothing left to split
        "done_if": ("ValveBiped.base",),
        "parts": [
            ("Deagle_Slide", [(-5.7, -24.7, 61.8), (-5.7, -23.4, 62.9), (-4.8, -23.7, 62.1), (-6.5, -23.7, 62.2),
                              (-4.9, -23.4, 62.0), (-6.5, -23.4, 62.1), (-6.6, -23.4, 62.1), (-4.8, -23.4, 62.0),
                              (-6.4, -24.3, 61.9), (-4.9, -24.3, 61.9), (-4.9, -24.0, 61.7), (-6.4, -24.0, 61.8),
                              (-5.7, -22.7, 61.8)], "centre"),
            ("Deagle_Barrel", [(-5.6, -32.0, 63.2), (-5.6, -33.5, 63.9)], "centre"),
            ("Deagle_Hammer", [(-5.7, -22.4, 61.4), (-5.7, -22.4, 60.7)], (0.5, 0.15, 0.1)),
            ("Deagle_Trigger", [(-5.7, -26.3, 60.0)], (0.5, 0.5, 1.0)),
            ("Deagle_Mag", [(-5.8, -25.2, 55.8)], "centre"),
            ("Deagle_SlideStop", [(-6.3, -27.6, 60.9), (-5.1, -27.6, 60.9)], "centre"),
        ],
    },
    "v_wrench": {
        "gun": "Wrench",
        "on": "ValveBiped.Bip01_R_Hand",
        "gun_pivot": "parent",  # pivot at the wrist, where the hand holds it
        "parts": [
            ("Wrench_HookJaw", [(-5.4, -51.0, 75.1), (-5.4, -49.5, 68.3)], "centre"),
            ("Wrench_Nut", [(-5.4, -49.5, 70.4)], "centre"),
        ],
    },
}
MATCH = 0.25  # how close a piece's centre must be to the recipe's


def pieces(smd):
    """Connected pieces of the weapon mesh: lists of triangle indices."""
    tris = [ti for ti, (m, _v) in enumerate(smd.tris) if m not in SKIP_MATERIALS and not m.startswith("bone_")]
    key, parent = {}, []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    tri_ids = []
    for ti in tris:
        ids = []
        for v in smd.tris[ti][1]:
            q = tuple(np.round(v["pos"] * 1000).astype(int))
            if q not in key:
                key[q] = len(parent)
                parent.append(len(parent))
            ids.append(key[q])
        tri_ids.append(ids)
    for a, b, c in tri_ids:
        parent[find(b)] = find(a)
        parent[find(c)] = find(a)
    groups = {}
    for ti, ids in zip(tris, tri_ids):
        groups.setdefault(find(ids[0]), []).append(ti)
    out = []
    for g in groups.values():
        P = np.array([v["pos"] for ti in g for v in smd.tris[ti][1]])
        out.append({"tris": g, "centre": P.mean(0), "min": P.min(0), "max": P.max(0)})
    return out


def split(smd, recipe, report):
    if smd.index(recipe["gun"]) is not None or any(smd.index(b) is not None for b in recipe.get("done_if", ())):
        report.append("already split, skipped")
        return []
    hand = smd.index(recipe["on"])
    if hand is None:
        raise RuntimeError("no bone %s" % recipe["on"])
    worlds = smd.worlds(0)
    all_pieces = pieces(smd)
    on_hand = [p for p in all_pieces if any(b == hand for ti in p["tris"] for v in smd.tris[ti][1] for b, _w in v["links"])]

    # gun bone
    if "gun_matrix_from" in recipe:
        gun_world = worlds[smd.index(recipe["gun_matrix_from"])].copy()
    else:
        gun_world = np.eye(4)
        if recipe.get("gun_pivot") == "parent":
            gun_world[:3, 3] = worlds[hand][:3, 3]
        else:
            P = np.array([p["centre"] for p in on_hand])
            gun_world[:3, 3] = P.mean(0)
    new = []
    gun = smd.add_bone(recipe["gun"], hand, gun_world, worlds[hand])
    new.append((recipe["gun"], recipe["on"], gun_world))
    owner = {id(p): gun for p in on_hand}

    worlds = smd.worlds(0)
    for name, centres, pivot in recipe["parts"]:
        chosen = []
        for c in centres:
            best = min(on_hand, key=lambda p: np.linalg.norm(p["centre"] - np.array(c)))
            d = np.linalg.norm(best["centre"] - np.array(c))
            if d > MATCH:
                report.append("! %s: no piece near %s (closest %.2f away)" % (name, c, d))
                continue
            if best not in chosen:
                chosen.append(best)
        if not chosen:
            continue
        lo = np.min([p["min"] for p in chosen], 0)
        hi = np.max([p["max"] for p in chosen], 0)
        at = (lo + hi) / 2 if pivot == "centre" else lo + (hi - lo) * np.array(pivot)
        world = np.eye(4)
        world[:3, 3] = at
        index = smd.add_bone(name, gun, world, worlds[gun])
        new.append((name, recipe["gun"], world))
        tri_count = 0
        for p in chosen:
            owner[id(p)] = index
            tri_count += len(p["tris"])
        report.append("%-18s %4d triangles, pivot %s" % (name, tri_count, np.round(at, 2)))

    moved = 0
    for p in on_hand:
        bone = owner[id(p)]
        for ti in p["tris"]:
            for v in smd.tris[ti][1]:
                if any(b == hand for b, _w in v["links"]):
                    v["links"] = [(bone if b == hand else b, w) for b, w in v["links"]]
                    if v["parent"] == hand:
                        v["parent"] = bone
                    moved += 1
    report.insert(0, "%s under %s: %d weapon vertices moved off the hand" % (recipe["gun"], recipe["on"], moved))
    return new


def match_to(smd, new_bones, reference):
    """Same bind pose for the new bones as in `reference` (the decoded ref)."""
    ref_w = reference.worlds(0)
    for name, _parent, _world in new_bones:
        si, ri = smd.index(name), reference.index(name)
        cur = smd.worlds(0)
        local = np.linalg.inv(cur[smd.nodes[si][1]]) @ ref_w[ri]
        smd.frames[0][1][si] = matrix_to_smd(local)


def process(name, dry=False, root=MOD):
    recipe = RECIPES[name]
    anims = os.path.join(root, "Blender", name, "anims")
    ref_path = os.path.join(anims, "ref.smd")
    ref = Smd(ref_path)
    report = []
    new = split(ref, recipe, report)
    print("== %s" % name)
    for line in report:
        print("   " + line)
    if not new:
        return
    ship_path = os.path.join(root, "modelsrc", name, name + "_ref.smd")
    ship = None
    if os.path.exists(ship_path):
        ship = Smd(ship_path)
        ship_report = []
        ship_new = split(ship, recipe, ship_report)
        if ship_new:
            match_to(ship, ship_new, ref)
            print("   shipping mesh: %s" % ship_report[0])
    if dry:
        return
    backup = os.path.join(root, "Blender", "_backup_before_gun_bones", name, "anims")
    if not os.path.exists(backup):
        os.makedirs(backup)
        for f in os.listdir(anims):
            shutil.copy2(os.path.join(anims, f), backup)
    seqs = [f for f in os.listdir(anims) if f.endswith(".smd") and f != "ref.smd"]
    for f in seqs:
        add_bones_to_sequence(os.path.join(anims, f), new, ref, os.path.join(anims, f))
    ref.write(ref_path)
    if ship is not None:
        keep = ship_path[:-4] + ".before_gun_bones.smd"
        if not os.path.exists(keep):
            shutil.copy2(ship_path, keep)
        ship.write(ship_path)
    print("   written (%d sequences)" % len(seqs))


def main(argv):
    args = argv[1:]
    dry = "--dry-run" in args
    names = [a for a in args if not a.startswith("--")] or list(RECIPES)
    for name in names:
        process(name, dry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
