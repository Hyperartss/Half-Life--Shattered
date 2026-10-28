#!/usr/bin/env python3
"""Rebuild the deagle viewmodel on HL2's pistol (v_pistol) skeleton.

The deagle used to borrow the .357 revolver's rig and animations. This puts
the same deagle mesh and Adrian Shephard's arms onto v_pistol's skeleton, so
the pistol's sequences (fire, reload with slide and magazine, empty variants,
recoil 1-3, dry fire) drive it, and the shipping model can $includemodel
weapons/v_pistol.mdl.

  * Arms: each arm piece of the current deagle is matched to the player model
    (tools/fit_shephard_arms.py does the fitting), and every vertex is moved
    from the bone it rides in the deagle to the same bone in v_pistol's bind
    pose. v_pistol's right hand has thumb and index bones only, so the
    other fingers get bones of their own (ValveBiped.Bip01_R_Finger2/21/22/3)
    keeping the deagle's grip.
  * Gun: placed in v_pistol's right hand exactly as it sat in the deagle's,
    then turned about the grip so its bore lines up with the USP's (the slide
    and magazine animations move along the USP's axes). Parts:
        frame, grip, pins      -> ValveBiped.base
        slide                  -> ValveBiped.square   (v_pistol's slide)
        hammer                 -> ValveBiped.hammer
        magazine               -> ValveBiped.clip
        barrel, trigger, slide stop -> Deagle_Barrel / Deagle_Trigger /
                                  Deagle_SlideStop, new bones under base

Writes Blender/v_deagle/ (ref, every pistol sequence, the QC) and
modelsrc/v_deagle/v_deagle_ref.smd; the .357-based versions are kept in
Blender/_backup_deagle_357/ and modelsrc/v_deagle/v_deagle_ref.357.smd.

Run with Blender (the player model is an FBX):

    ~/.local/bin/blender -b --python-exit-code 1 --python tools/build_deagle_on_pistol.py
"""
import os
import shutil
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fit_shephard_arms as F  # noqa: E402
from fit_shephard_arms import Smd, apply, bname, matrix_to_smd  # noqa: E402

MOD = F.MOD
PART_TO_PISTOL = {
    "Deagle_Gun": "ValveBiped.base",
    "Deagle_Slide": "ValveBiped.square",
    "Deagle_Hammer": "ValveBiped.hammer",
    "Deagle_Mag": "ValveBiped.clip",
}
EXTRA_GUN_BONES = ("Deagle_Barrel", "Deagle_Trigger", "Deagle_SlideStop")
ARM_MATERIAL = F.ARM_MATERIAL

QC_HEADER = """// Deagle on HL2's v_pistol skeleton (tools/build_deagle_on_pistol.py).
// Compiles to models/sl_animtest/v_deagle.mdl, not to models/weapons/v_deagle.mdl
// Import in Blender with Blender Source Tools
// (File > Import > Source Engine QC) for the rig plus one action per sequence.
$modelname "sl_animtest/v_deagle.mdl"
$cdmaterials "models/weapons/v_deagle/"
$cdmaterials "models/weapons/v_wrench/"
$model "v_deagle" "anims/ref.smd"
"""


def rotation_about(point, R):
    m = np.eye(4)
    m[:3, :3] = R
    return F._about(point, m)


def bore_axis(smd, bone_names):
    """Unit vector from the rear of the slide/barrel to the muzzle (bind pose)."""
    idx = {smd.index(n) for n in bone_names if smd.index(n) is not None}
    P = np.array([v["pos"] for m, vs in smd.tris if not m.startswith("bone_") for v in vs
                  if max(v["links"], key=lambda l: l[1])[0] in idx])
    c = P.mean(0)
    _u, _s, vt = np.linalg.svd(P - c, full_matrices=False)
    a = vt[0]
    return a if a[1] < 0 else -a  # forward is -Y


def build(player, root=MOD, log=print):
    deagle_dir = os.path.join(root, "Blender", "v_deagle")
    old = Smd(os.path.join(deagle_dir, "anims", "ref.smd"))
    if old.index("ValveBiped.base") is not None:
        log("v_deagle is already on the pistol skeleton")
        return None
    if old.index("Deagle_Gun") is None:
        raise RuntimeError("run tools/split_gun_parts.py v_deagle first")
    pistol = Smd(os.path.join(root, "Blender", "v_pistol", "anims", "ref.smd"))
    P = pistol.worlds(0)

    # ---- new skeleton: v_pistol's, mesh dropped -----------------------------
    new = Smd(os.path.join(root, "Blender", "v_pistol", "anims", "ref.smd"))
    new.tris = []
    extra = []  # (name, parent, world)

    def add(name, parent, world):
        W = new.worlds(0)
        new.add_bone(name, new.index(parent), world, W[new.index(parent)])
        extra.append((name, parent, world))

    # ---- arms -------------------------------------------------------------
    fits = {}
    for corners in F.arm_pieces(old):
        fit, other = F.best_fit(player, corners, old)
        fits[fit.side] = (fit, corners)
        log("deagle %s arm: fit %.3f (other side %.3f), %d corners" % (fit.side, fit.residual, other.residual, len(corners)))
    if set(fits) != {"L", "R"}:
        raise RuntimeError("expected both arms in the deagle, found %s" % sorted(fits))

    r_fit = fits["R"][0]
    r_hand_deagle = r_fit.world("Hand")
    r_hand_pistol = P[pistol.index(bname("R", "Hand"))]

    # right-hand fingers v_pistol does not have (middle + the rest): start from
    # the player's straight finger in v_pistol's hand, then curl each joint
    # the way v_pistol's index finger is curled around its grip
    hand_rest = player.rest[bname("R", "Hand")]
    curl_from = {"Finger2": "Finger1", "Finger21": "Finger11", "Finger22": "Finger12", "Finger3": "Finger1"}
    for part in F.FINGERS:
        name = bname("R", part)
        if new.index(name) is not None or name not in player.rest:
            continue
        parent_part = F.finger_parent(part)
        parent_name = bname("R", parent_part)
        W = new.worlds(0)
        parent_world = W[new.index(parent_name)]
        # straight player finger, relative to its (already placed) parent
        rest_local = np.linalg.inv(player.rest[parent_name]) @ player.rest[name]
        world = parent_world @ rest_local
        ref_part = curl_from.get(part)
        if ref_part and new.index(bname("R", ref_part)) is not None:
            ref_name = bname("R", ref_part)
            ref_parent = bname("R", F.finger_parent(ref_part))
            posed = np.linalg.inv(W[new.index(ref_parent)]) @ W[new.index(ref_name)]
            straight = np.linalg.inv(player.rest[ref_parent]) @ player.rest[ref_name]
            bend = straight[:3, :3].T @ posed[:3, :3]  # the joint's curl, in its own frame
            world[:3, :3] = world[:3, :3] @ bend
        add(name, parent_name, world)

    W = new.worlds(0)

    def target_bone(side, part):
        part = F.HELPERS.get(part, part)
        name = bname(side, part)
        while new.index(name) is None:
            # fall back up the player hierarchy (e.g. a finger v_pistol lacks)
            parent = player.parent.get(name, "")
            if not parent:
                return new.index(bname(side, "Hand"))
            name = parent
        return new.index(name)

    arm_tris = []
    for side, (fit, corners) in sorted(fits.items()):
        weights = fit.corner_weights(corners, old)
        def fitted(key):
            """A bone the old deagle actually had vertices for: the part
            itself, else the forearm (for an upper arm cut off at the elbow),
            else up the finger chain to the hand. A part with no vertices of
            its own has no trustworthy fit."""
            while not fit.has_data(key) and key != "Hand":
                key = "Forearm" if key == "UpperArm" else (F.finger_parent(key) if key in F.FINGERS else "Hand")
            return key

        delta = {}
        for part in set(p for ws in weights for p in ws):
            b = target_bone(side, part)
            key = fitted(F.HELPERS.get(part, part))
            kb = target_bone(side, key)
            delta[part] = (b, W[kb] @ np.linalg.inv(fit.world(key)))
        for c in range(0, len(corners), 3):
            verts = []
            for (ti, k), parts in zip(corners[c:c + 3], weights[c:c + 3]):
                v = old.tris[ti][1][k]
                m = np.zeros((4, 4))
                acc = defaultdict(float)
                for part, w in parts.items():
                    b, D = delta[part]
                    m += w * D
                    acc[b] += w
                links = sorted(acc.items(), key=lambda kv: -kv[1])[:3]
                tot = sum(w for _b, w in links) or 1.0
                links = [(b, w / tot) for b, w in links if w / tot > 1e-4]
                nrm = m[:3, :3] @ v["nrm"]
                nrm /= np.linalg.norm(nrm) or 1.0
                verts.append({"parent": links[0][0], "pos": apply(m, v["pos"]), "nrm": nrm, "uv": v["uv"], "links": links})
            arm_tris.append((ARM_MATERIAL, verts))

    # ---- gun --------------------------------------------------------------
    # The deagle goes where the USP is: barrel along the USP's barrel, side to
    # side along the model's X, and its hammer pivot on the USP's hammer pivot
    # (where the web of the hand sits). Placing it as the .357's hand held it
    # would leave it pointing tens of degrees off the USP, i.e. off the
    # crosshair.
    def frame(bore):
        lat = np.array([1.0, 0.0, 0.0])
        lat = lat - bore * (lat @ bore)
        lat /= np.linalg.norm(lat)
        up = np.cross(lat, bore)
        return np.column_stack([lat, bore, up])

    usp = bore_axis(pistol, ["ValveBiped.square"])
    d_bore = bore_axis(old, ["Deagle_Slide", "Deagle_Barrel"])
    R = frame(usp) @ frame(d_bore).T
    d_pivot = old.worlds(0)[old.index("Deagle_Hammer")][:3, 3]
    u_pivot = P[pistol.index("ValveBiped.hammer")][:3, 3]
    G = np.eye(4)
    G[:3, :3] = R
    G[:3, 3] = u_pivot - R @ d_pivot
    deagle_axis = R @ d_bore
    part_turn = F.rotation_between(usp, deagle_axis)
    angle = np.degrees(np.arccos(np.clip(np.dot(deagle_axis, usp), -1, 1)))
    log("gun: lined up with the USP (bore %.2f deg off), hammer pivot on the USP's" % angle)

    OW = old.worlds(0)
    base = new.index("ValveBiped.base")
    for name in EXTRA_GUN_BONES:
        oi = old.index(name)
        if oi is None:
            continue
        add(name, "ValveBiped.base", G @ OW[oi])
    W = new.worlds(0)
    gun_bone = {}
    for i, (name, _p) in enumerate(old.nodes):
        if name in PART_TO_PISTOL:
            gun_bone[i] = new.index(PART_TO_PISTOL[name])
        elif name in EXTRA_GUN_BONES:
            gun_bone[i] = new.index(name)
    gun_tris = []
    for material, verts in old.tris:
        if material == ARM_MATERIAL or material.startswith("bone_"):
            continue
        out = []
        for v in verts:
            links = [(gun_bone.get(b, base), w) for b, w in v["links"]]
            nrm = G[:3, :3] @ v["nrm"]
            out.append({"parent": links[0][0], "pos": apply(G, v["pos"]), "nrm": nrm, "uv": v["uv"], "links": links})
        gun_tris.append((material, out))

    new.tris = gun_tris + arm_tris
    # muzzle for the QC attachment, in base's space
    muzzle_old = OW[old.index("muzzle")] if old.index("muzzle") is not None else None
    muzzle = None
    if muzzle_old is not None:
        world = G @ muzzle_old
        muzzle = np.linalg.inv(W[base]) @ world
    return new, extra, muzzle, part_turn


def retarget_parts(seq_path, ref, part_turn, bones=("ValveBiped.square", "ValveBiped.clip")):
    """Turn the slide/magazine motion of a pistol sequence onto the deagle's axes.

    The motion of each bone relative to its bind pose (offset and rotation, in
    its parent's space) is rotated by the bore difference, so the deagle's slide
    runs along its own barrel and its magazine drops out of its own grip.
    """
    seq = Smd(seq_path)
    W = ref.worlds(0)
    for name in bones:
        ri, si = ref.index(name), seq.index(name)
        if ri is None or si is None:
            continue
        Rp = W[ref.nodes[ri][1]][:3, :3]
        C = Rp.T @ part_turn @ Rp
        L0 = F.local_matrix(ref.frames[0][1][ri])
        for _t, frame in seq.frames:
            if si not in frame:
                continue
            Lf = F.local_matrix(frame[si])
            out = np.eye(4)
            out[:3, 3] = L0[:3, 3] + C @ (Lf[:3, 3] - L0[:3, 3])
            out[:3, :3] = C @ (Lf[:3, :3] @ L0[:3, :3].T) @ C.T @ L0[:3, :3]
            frame[si] = matrix_to_smd(out)
    seq.write(seq_path)


def add_markers(smd):
    """One tiny triangle per bone no vertex uses (studiomdl drops such bones)."""
    used = {b for _m, vs in smd.tris for v in vs for b, _w in v["links"]}
    W = smd.worlds(0)
    for i, (name, _p) in enumerate(smd.nodes):
        if i in used:
            continue
        o = W[i][:3, 3]
        verts = []
        for d in ((0, 0, 0), (0.01, 0, 0), (0, 0.01, 0)):
            verts.append({"parent": i, "pos": o + np.array(d), "nrm": np.array([0.0, 0.0, 1.0]), "uv": (0.0, 1.0), "links": [(i, 1.0)]})
        smd.tris.append(("bone_" + name, verts))


def write(new, extra, muzzle, part_turn, root=MOD, log=print):
    deagle_dir = os.path.join(root, "Blender", "v_deagle")
    anims = os.path.join(deagle_dir, "anims")
    pistol_anims = os.path.join(root, "Blender", "v_pistol", "anims")
    backup = os.path.join(root, "Blender", "_backup_deagle_357")
    if not os.path.exists(backup):
        shutil.copytree(deagle_dir, backup)
    for f in os.listdir(anims):
        os.remove(os.path.join(anims, f))
    shipping_mesh = Smd.__new__(Smd)
    shipping_mesh.nodes = [list(n) for n in new.nodes]
    shipping_mesh.frames = [(t, dict(b)) for t, b in new.frames]
    shipping_mesh.tris = list(new.tris)
    add_markers(new)
    new.write(os.path.join(anims, "ref.smd"))
    seqs = sorted(f for f in os.listdir(pistol_anims) if f.endswith(".smd") and f != "ref.smd")
    for f in seqs:
        F.add_bones_to_sequence(os.path.join(pistol_anims, f), extra, new, os.path.join(anims, f))
        retarget_parts(os.path.join(anims, f), new, part_turn)
    qc = open(os.path.join(root, "Blender", "v_pistol", "v_pistol_anims.qc")).read()
    lines = [l for l in qc.splitlines() if l.startswith("$sequence")]
    with open(os.path.join(deagle_dir, "v_deagle_anims.qc"), "w") as fh:
        fh.write(QC_HEADER + "\n" + "\n".join(lines) + "\n")
    # shipping mesh
    src = os.path.join(root, "modelsrc", "v_deagle", "v_deagle_ref.smd")
    keep = os.path.join(root, "modelsrc", "v_deagle", "v_deagle_ref.357.smd")
    if os.path.exists(src) and not os.path.exists(keep):
        shutil.copy2(src, keep)
    shipping_mesh.write(src)
    log("wrote Blender/v_deagle (%d pistol sequences) and modelsrc/v_deagle/v_deagle_ref.smd" % len(seqs))
    if muzzle is not None:
        x, y, z, rx, ry, rz = matrix_to_smd(muzzle)
        log('muzzle attachment for the QC: $attachment "muzzle" "ValveBiped.base" %.4f %.4f %.4f' % (x, y, z))
    return seqs


def main(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    fbx = F.DEFAULT_FBX
    if "--fbx" in args:
        fbx = args[args.index("--fbx") + 1]
    player = F.load_player(fbx)
    result = build(player)
    if result is None:
        return 0
    new, extra, muzzle, part_turn = result
    if "--dry-run" not in args:
        write(new, extra, muzzle, part_turn)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
