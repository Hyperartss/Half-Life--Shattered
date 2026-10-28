#!/usr/bin/env python3
"""Put Adrian Shephard's real arm rig (both arms, every finger) on the viewmodels.

The arms in the viewmodels are the GMod Adrian Shephard player model's arms,
posed and then frozen: the organic rifle has both arms rigid on `Base`, the
deagle's right hand and the wrench's right hand have no finger bones, and the
wrench has no left arm at all. Every arm vertex still carries the player
model's UVs (left and right are mirrored, so each UV names exactly one vertex
per side), which gives an exact vertex correspondence. From that this script:

  1. picks the side of each arm piece (the wrong side does not fit rigidly),
  2. fits the player's bone transforms to the posed piece by skinning (LBS)
     least squares, so every bone -- fingers included -- lands where the
     posed mesh says it is,
  3. adds the missing bones (ValveBiped.Bip01_<side>_*) and re-skins the arm
     vertices with the player model's own weights,
  4. writes the new bones into every decoded sequence SMD with their bind
     pose, so they ride along with their parents and the stock animations
     look exactly as before.

What happens per weapon (RECIPES below):

  v_ar2_organic  both arms become full arm chains (UpperArm/Forearm/Hand +
                 15 finger bones each), parented to Base
  v_deagle       left arm already is a full chain and is left alone; the
                 right hand gets its 15 finger bones under `Hand`
  v_wrench       right hand gets its finger bones; a left arm is grafted in,
                 taken from the deagle's left arm in eye space at idle (it is
                 off-screen there, as on the deagle) and parented to Spine4

Existing bones are never moved and no existing bone changes parent, so models
that still use $includemodel keep working, and the bind pose mesh is
unchanged except for the grafted arm.

Run with Blender (it needs Blender's FBX importer for the player model):

    ~/.local/bin/blender -b --python-exit-code 1 --python tools/fit_shephard_arms.py -- \
        v_ar2_organic v_deagle v_wrench

Options:
    --fbx PATH        player model (default: the Asset Library copy)
    --dry-run         fit and report, write nothing
    --out DIR         write to DIR/<weapon>/... instead of in place

Originals are copied to Blender/_backup_before_arms/<weapon>/ (and the
modelsrc ref next to itself as *.before_arms.smd) before anything is written.
Running it twice is safe: a weapon that already has the bones is skipped.
"""
import math
import os
import shutil
import sys
from collections import defaultdict

import numpy as np

MOD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FBX = (
    "/media/hyper/Storage HDD/Asset Library/Models/Sketchfab/Characters/"
    "adrian-shephard-gmod/source/adrian shephard gmod.fbx"
)
ARM_MATERIAL = "shephard_arms"

FINGERS = ["Finger%s" % k for k in ("0", "01", "02", "1", "11", "12", "2", "21", "22", "3", "31", "32", "4", "41", "42")]
MAIN = ["UpperArm", "Forearm", "Hand"]
# helper (twist/volume) bones on the player model and the main bone whose
# motion they get on the viewmodel
HELPERS = {"Ulna": "Forearm", "Wrist": "Forearm", "Elbow": "Forearm", "Clavicle": "UpperArm"}

RECIPES = {
    # the rifle and both arms move to a new `Gun` bone under Base: Base is
    # the root, and root animation does not survive studiomdl's root yaw
    "v_ar2_organic": {"L": "new", "R": "new", "gun_bone": ("Gun", "Base"), "new_parent": "Gun"},
    "v_deagle": {"L": "keep", "R": "fingers"},
    "v_wrench": {
        "R": "fingers",
        "graft_L": {"donor": "v_deagle", "donor_seq": "idle01", "seq": "idle01",
                    "parent": "ValveBiped.Bip01_Spine4", "park_pitch": 15.0},
    },
}


def bname(side, part):
    return "ValveBiped.Bip01_%s_%s" % (side, part)


# --------------------------------------------------------------------------
# SMD
# --------------------------------------------------------------------------
def euler_to_matrix(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return np.array([
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy, sx * cy, cx * cy],
    ])


def matrix_to_euler(m):
    sy = -m[2, 0]
    if abs(sy) < 0.999999:
        ry = math.asin(sy)
        rx = math.atan2(m[2, 1], m[2, 2])
        rz = math.atan2(m[1, 0], m[0, 0])
    else:  # gimbal lock
        ry = math.copysign(math.pi / 2, sy)
        rx = math.atan2(-m[1, 2], m[1, 1])
        rz = 0.0
    return rx, ry, rz


def local_matrix(v):
    m = np.eye(4)
    m[:3, :3] = euler_to_matrix(*v[3:6])
    m[:3, 3] = v[:3]
    return m


def matrix_to_smd(m):
    rx, ry, rz = matrix_to_euler(m[:3, :3])
    return (m[0, 3], m[1, 3], m[2, 3], rx, ry, rz)


class Smd:
    """Just enough SMD to read, edit and write viewmodel refs and sequences."""

    def __init__(self, path):
        self.path = path
        self.nodes = []  # [name, parent index]
        self.frames = []  # [(time, {index: 6 floats})]
        self.tris = []  # [(material, [vertex dict] * 3)]
        mode = None
        tri = None
        for raw in open(path, errors="ignore"):
            line = raw.strip()
            if line in ("nodes", "skeleton", "triangles"):
                mode = line
                continue
            if line == "end":
                mode = None
                continue
            if not line or mode is None:
                continue
            parts = line.split()
            if mode == "nodes":
                name = line[line.index('"') + 1: line.rindex('"')]
                self.nodes.append([name, int(parts[-1])])
            elif mode == "skeleton":
                if parts[0] == "time":
                    self.frames.append((int(parts[1]), {}))
                else:
                    self.frames[-1][1][int(parts[0])] = tuple(map(float, parts[1:7]))
            elif mode == "triangles":
                if tri is None:
                    tri = (line, [])
                    continue
                f = parts
                n = int(f[9]) if len(f) > 9 else 0
                links = [(int(f[10 + 2 * i]), float(f[11 + 2 * i])) for i in range(n)]
                if not links:
                    links = [(int(f[0]), 1.0)]
                tri[1].append({
                    "parent": int(f[0]),
                    "pos": np.array(list(map(float, f[1:4]))),
                    "nrm": np.array(list(map(float, f[4:7]))),
                    "uv": (float(f[7]), float(f[8])),
                    "links": links,
                })
                if len(tri[1]) == 3:
                    self.tris.append(tri)
                    tri = None

    def index(self, name):
        for i, (n, _p) in enumerate(self.nodes):
            if n == name:
                return i
        return None

    def worlds(self, frame=0):
        """World matrix per bone at a frame (missing bones fall back to frame 0)."""
        base = dict(self.frames[0][1])
        base.update(self.frames[frame][1])
        out = {}

        def get(i):
            if i in out:
                return out[i]
            local = local_matrix(base[i])
            parent = self.nodes[i][1]
            out[i] = local if parent < 0 else get(parent) @ local
            return out[i]

        for i in range(len(self.nodes)):
            get(i)
        return out

    def add_bone(self, name, parent, world_ref, parent_world_ref):
        """Append a bone; its bind local goes into every frame."""
        local = np.linalg.inv(parent_world_ref) @ world_ref
        values = matrix_to_smd(local)
        self.nodes.append([name, parent])
        index = len(self.nodes) - 1
        for _t, bones in self.frames:
            bones[index] = values
        return index

    def write(self, path):
        out = ["version 1", "nodes"]
        for i, (name, parent) in enumerate(self.nodes):
            out.append('%d "%s" %d' % (i, name, parent))
        out += ["end", "skeleton"]
        for t, bones in self.frames:
            out.append("time %d" % t)
            for i in sorted(bones):
                out.append("%d %.6f %.6f %.6f %.6f %.6f %.6f" % ((i,) + tuple(bones[i])))
        out.append("end")
        if self.tris:
            out.append("triangles")
            for material, verts in self.tris:
                out.append(material)
                for v in verts:
                    links = v["links"]
                    out.append(
                        "%d %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %d %s" % (
                            v["parent"], *v["pos"], *v["nrm"], v["uv"][0], v["uv"][1], len(links),
                            " ".join("%d %.6f" % (b, w) for b, w in links),
                        )
                    )
            out.append("end")
        with open(path, "w") as fh:
            fh.write("\n".join(out) + "\n")


# --------------------------------------------------------------------------
# player model
# --------------------------------------------------------------------------
class Player:
    def __init__(self, data):
        self.pos = data["pos"]
        self.W = data["W"]
        self.groups = list(data["groups"])
        self.rest = dict(zip(data["bones"], data["bone_mats"]))
        self.parent = dict(zip(data["bones"], data["bone_parents"]))
        self.uv_side = {"L": {}, "R": {}}
        for vi, u, v in data["loop_uv"]:
            vi = int(vi)
            side = self.side(vi)
            if side:
                self.uv_side[side][(round(u, 3), round(v, 3))] = vi

    def side(self, v):
        name = self.groups[int(self.W[v].argmax())]
        return "L" if "_L_" in name else "R" if "_R_" in name else None

    def side_groups(self, side):
        return [i for i, g in enumerate(self.groups) if "_%s_" % side in g]


def load_player(fbx):
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    from io_scene_fbx import import_fbx

    original = import_fbx.blen_read_light

    def safe_light(*args):
        # the lamp in this file trips a Cycles attribute on builds without
        # Cycles; the lamp is irrelevant here
        try:
            return original(*args)
        except AttributeError:
            return bpy.data.lights.new("fbx_light", "POINT")

    import_fbx.blen_read_light = safe_light
    try:
        bpy.ops.import_scene.fbx(filepath=fbx)
    finally:
        import_fbx.blen_read_light = original

    mesh = next(o for o in bpy.data.objects if o.type == "MESH" and o.find_armature())
    armature = mesh.find_armature()
    mw = mesh.matrix_world
    groups = [g.name for g in mesh.vertex_groups]
    W = np.zeros((len(mesh.data.vertices), len(groups)))
    for v in mesh.data.vertices:
        for g in v.groups:
            W[v.index, g.group] = g.weight
    uv = mesh.data.uv_layers.active.data
    loop_uv = [(mesh.data.loops[i].vertex_index, uv[i].uv[0], uv[i].uv[1]) for i in range(len(mesh.data.loops))]
    bones = list(armature.data.bones)
    return Player({
        "pos": np.array([(mw @ v.co)[:] for v in mesh.data.vertices]),
        "W": W,
        "groups": groups,
        "bones": [b.name for b in bones],
        "bone_mats": [np.array(armature.matrix_world @ b.matrix_local) for b in bones],
        "bone_parents": [b.parent.name if b.parent else "" for b in bones],
        "loop_uv": loop_uv,
    })


# --------------------------------------------------------------------------
# fitting
# --------------------------------------------------------------------------
def kabsch(src, dst, w=None):
    if w is None:
        w = np.ones(len(src))
    w = w / w.sum()
    ms, md = w @ src, w @ dst
    H = ((src - ms) * w[:, None]).T @ (dst - md)
    U, _S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    R = Vt.T @ np.diag([1, 1, d]) @ U.T
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = md - R @ ms
    return T


def apply(T, p):
    return p @ T[:3, :3].T + T[:3, 3]


def arm_pieces(smd):
    """Connected pieces of the arm material, as lists of (tri, corner)."""
    corners = [(ti, k) for ti, (m, _v) in enumerate(smd.tris) if m == ARM_MATERIAL for k in range(3)]
    key = {}
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    ids = []
    for ti, k in corners:
        q = tuple(np.round(smd.tris[ti][1][k]["pos"] * 1000).astype(int))
        if q not in key:
            key[q] = len(parent)
            parent.append(len(parent))
        ids.append(key[q])
    for c in range(0, len(ids), 3):
        a, b, d = ids[c:c + 3]
        parent[find(b)] = find(a)
        parent[find(d)] = find(a)
    pieces = defaultdict(list)
    for corner, i in zip(corners, ids):
        pieces[find(i)].append(corner)
    return [p for p in pieces.values() if len(p) >= 30]


class Fit:
    """Player side bones fitted onto one posed arm piece."""

    def __init__(self, player, side, corners, smd):
        self.player, self.side = player, side
        verts = [smd.tris[ti][1][k] for ti, k in corners]
        # The decoder writes V flipped relative to the source SMDs; take
        # whichever convention actually matches the player model's UVs.
        table = player.uv_side[side]
        best = None
        for flip in (True, False):
            found = [table.get((round(v["uv"][0], 3), round(1.0 - v["uv"][1] if flip else v["uv"][1], 3))) for v in verts]
            hits = sum(f is not None for f in found)
            if best is None or hits > best[0]:
                best = (hits, found)
        self.corner_player = best[1]  # player vertex per corner (or None)
        matched = defaultdict(list)
        for v, pv in zip(verts, self.corner_player):
            if pv is not None:
                matched[pv].append(v["pos"])
        self.pv = np.array(sorted(matched))
        self.X = player.pos[self.pv] if len(self.pv) else np.zeros((0, 3))
        self.Y = np.array([np.mean(matched[p], 0) for p in self.pv]) if len(self.pv) else np.zeros((0, 3))
        self.groups = player.side_groups(side)
        Wm = player.W[self.pv][:, self.groups] if len(self.pv) else np.zeros((0, len(self.groups)))
        sums = Wm.sum(1, keepdims=True)
        sums[sums == 0] = 1
        self.Wm = Wm / sums
        self.T = {}
        self.residual = float("inf")
        if len(self.pv) >= 20:
            self._solve()

    def _gname(self, gi):
        return self.player.groups[self.groups[gi]]

    def _parent_T(self, name):
        p = self.player.parent.get(name, "")
        while p:
            if p in self.T:
                return self.T[p]
            p = self.player.parent.get(p, "")
        return None

    def _solve(self, iterations=40):
        order = sorted(range(len(self.groups)), key=lambda g: self._depth(self._gname(g)))
        # initial rigid fits from strongly weighted vertices
        for g in order:
            name = self._gname(g)
            sel = self.Wm[:, g] >= 0.5
            if sel.sum() >= 4:
                self.T[name] = kabsch(self.X[sel], self.Y[sel])
            else:
                parent = self._parent_T(name)
                if parent is not None:
                    self.T[name] = parent.copy()
        if not self.T:
            return
        anyT = next(iter(self.T.values()))
        for g in order:
            self.T.setdefault(self._gname(g), anyT.copy())
        # skinning least squares, one bone at a time
        for _ in range(iterations):
            for g in order:
                name = self._gname(g)
                w = self.Wm[:, g]
                sel = w > 0.05
                if sel.sum() < 4:
                    continue
                others = self.predict(exclude=g)
                target = (self.Y[sel] - others[sel]) / w[sel, None]
                self.T[name] = kabsch(self.X[sel], target, w[sel] ** 2)
        self.residual = float(np.sqrt(((self.predict() - self.Y) ** 2).sum(1).mean()))

    def _depth(self, name):
        d = 0
        p = self.player.parent.get(name, "")
        while p:
            d += 1
            p = self.player.parent.get(p, "")
        return d

    def predict(self, exclude=None):
        out = np.zeros_like(self.Y)
        for g in range(len(self.groups)):
            if g == exclude:
                continue
            w = self.Wm[:, g]
            if not w.any():
                continue
            out += w[:, None] * apply(self.T[self._gname(g)], self.X)
        return out

    def has_data(self, part):
        name = bname(self.side, part)
        if name not in self.player.groups:
            return False
        g = self.player.groups.index(name)
        if g not in self.groups:
            return False
        return (self.Wm[:, self.groups.index(g)] > 0.3).sum() >= 4

    def world(self, part):
        """Fitted bind-pose matrix of a player bone (falls back to its parent)."""
        name = bname(self.side, part)
        T = self.T.get(name)
        if T is None:
            T = self._parent_T(name)
        return T @ self.player.rest[name]

    def corner_weights(self, corners, smd):
        """Player weights (main bone part -> weight) for every corner."""
        part_of = {}
        for g in self.groups:
            name = self.player.groups[g]
            part = name.split("_%s_" % self.side, 1)[1]
            part_of[g] = HELPERS.get(part, part) if part in HELPERS or part in MAIN or part in FINGERS else None
        result = [None] * len(corners)
        known = []
        for i, pv in enumerate(self.corner_player):
            if pv is None:
                continue
            acc = defaultdict(float)
            for g in self.groups:
                w = self.player.W[pv, g]
                if w > 0 and part_of[g]:
                    acc[part_of[g]] += w
            if acc:
                result[i] = dict(acc)
                known.append(i)
        # corners without a UV match copy their nearest matched neighbour
        if known:
            P = np.array([smd.tris[ti][1][k]["pos"] for ti, k in corners])
            K = P[known]
            for i in range(len(result)):
                if result[i] is None:
                    j = known[int(((K - P[i]) ** 2).sum(1).argmin())]
                    result[i] = dict(result[j])
        return result


def best_fit(player, corners, smd):
    fits = [Fit(player, s, corners, smd) for s in ("L", "R")]
    fits.sort(key=lambda f: f.residual)
    return fits[0], fits[1]


# --------------------------------------------------------------------------
# rig building
# --------------------------------------------------------------------------
def finger_parent(part):
    """Finger0 -> Hand, Finger01 -> Finger0, Finger02 -> Finger01."""
    digits = part[len("Finger"):]
    if len(digits) == 1:
        return "Hand"
    return "Finger" + digits[:-1] if len(digits) == 2 and digits[-1] == "1" else "Finger" + digits[0] + str(int(digits[1]) - 1)


def set_weights(smd, corners, weights, bone_of_part):
    for (ti, k), parts in zip(corners, weights):
        acc = defaultdict(float)
        for part, w in parts.items():
            acc[bone_of_part(part)] += w
        links = sorted(acc.items(), key=lambda kv: -kv[1])[:3]
        total = sum(w for _b, w in links) or 1.0
        links = [(b, w / total) for b, w in links if w / total > 1e-4]
        v = smd.tris[ti][1][k]
        v["links"] = links
        v["parent"] = links[0][0]


def placed_upper_arm(fit, elbow_world, wrist_world, up=np.array([0.0, 0.0, 1.0])):
    """Upper arm for an arm piece cut at the elbow: no vertices to fit, so it
    hangs the shoulder above and behind the elbow, giving the elbow a bend
    that points down, as viewmodel arms do."""
    forearm_dir = (elbow_world[:3, 3] - wrist_world[:3, 3])
    forearm_dir /= np.linalg.norm(forearm_dir)
    # mostly up from the elbow: an elbow bent ~100 degrees leaves the IK room
    # to push the hand forward as well as pull it back
    back = 0.35 * forearm_dir + up
    back /= np.linalg.norm(back)
    shoulder = elbow_world[:3, 3] + back * 12.0
    rest = fit.player.rest[bname(fit.side, "UpperArm")]
    rest_forearm = fit.player.rest[bname(fit.side, "Forearm")]
    # start from the player's straight arm hanging off the fitted forearm
    m = elbow_world @ np.linalg.inv(rest_forearm) @ rest
    y = m[:3, 1] / np.linalg.norm(m[:3, 1])
    want = elbow_world[:3, 3] - shoulder
    want /= np.linalg.norm(want)
    R = rotation_between(y, want)
    out = np.eye(4)
    out[:3, :3] = R @ m[:3, :3]
    out[:3, 3] = shoulder
    return out


def _about(point, m):
    t = np.eye(4)
    t[:3, 3] = point
    ti = np.eye(4)
    ti[:3, 3] = -point
    return t @ m @ ti


def rotation_between(a, b):
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


class Weapon:
    def __init__(self, name, root=MOD, ref_path=None):
        self.name = name
        self.root = root
        self.dir = os.path.join(root, "Blender", name)
        self.ref_path = ref_path or os.path.join(self.dir, "anims", "ref.smd")
        self.ref = Smd(self.ref_path)
        self.seq_paths = sorted(
            os.path.join(self.dir, "anims", f) for f in os.listdir(os.path.join(self.dir, "anims"))
            if f.endswith(".smd") and f != "ref.smd"
        )
        self.new_bones = []  # (name, parent name, world)
        self.report = []

    def add(self, name, parent, world):
        if self.ref.index(name) is not None:
            raise RuntimeError("%s already has %s" % (self.name, name))
        worlds = self.ref.worlds()
        p = self.ref.index(parent)
        index = self.ref.add_bone(name, p, world, worlds[p])
        self.new_bones.append((name, parent, world))
        return index


def rig_fingers(weapon, fit, corners, weights, part_bone):
    """Existing arm bones stay; any part with no bone of its own gets one."""
    smd = weapon.ref
    hand_bone = part_bone["Hand"]
    created = {}
    for part in FINGERS:
        if part in part_bone or bname(fit.side, part) not in fit.player.rest:
            continue
        parent_part = finger_parent(part)
        parent = created.get(parent_part) or part_bone.get(parent_part) or hand_bone
        name = bname(fit.side, part)
        weapon.add(name, parent, fit.world(part))
        created[part] = name
    # Keep every existing weight (the stock animations must deform exactly as
    # before) and only split what sits on the hand bone between the hand and
    # its new fingers, in the player model's proportions.
    hand_index = smd.index(hand_bone)
    hand_parts = {"Hand": hand_index}
    for part, name in created.items():
        hand_parts[part] = smd.index(name)
    for part in FINGERS:
        if part in part_bone and part not in hand_parts:
            hand_parts[part] = smd.index(part_bone[part])
    for (ti, k), parts in zip(corners, weights):
        v = smd.tris[ti][1][k]
        on_hand = sum(w for b, w in v["links"] if b == hand_index)
        share = {p: w for p, w in parts.items() if p in hand_parts}
        total = sum(share.values())
        if on_hand <= 0 or total <= 0:
            continue
        acc = defaultdict(float)
        for b, w in v["links"]:
            if b != hand_index:
                acc[b] += w
        for p, w in share.items():
            acc[hand_parts[p]] += on_hand * w / total
        links = sorted(acc.items(), key=lambda kv: -kv[1])[:3]
        norm = sum(w for _b, w in links) or 1.0
        v["links"] = [(b, w / norm) for b, w in links if w / norm > 1e-4]
        v["parent"] = v["links"][0][0]
    return created


def existing_part_bones(weapon, fit, corners, weights):
    """Player part -> existing bone, by name first, else by what the posed
    vertices are weighted to today (the deagle's right arm is `Arm`/`Hand`)."""
    smd = weapon.ref
    out = {}
    for part in MAIN + FINGERS:
        if smd.index(bname(fit.side, part)) is not None:
            out[part] = bname(fit.side, part)
        elif smd.index("Bip01_%s_%s" % (fit.side, part)) is not None:
            out[part] = "Bip01_%s_%s" % (fit.side, part)
    votes = defaultdict(lambda: defaultdict(float))
    for (ti, k), parts in zip(corners, weights):
        v = smd.tris[ti][1][k]
        bone = smd.nodes[max(v["links"], key=lambda l: l[1])[0]][0]
        for part, w in parts.items():
            votes[part][bone] += w
    for part in MAIN:
        if part not in out and votes.get(part):
            out[part] = max(votes[part].items(), key=lambda kv: kv[1])[0]
    return out


def rig_new_arm(weapon, fit, corners, weights, parent):
    smd = weapon.ref
    hand = fit.world("Hand")
    forearm = fit.world("Forearm")
    if fit.has_data("UpperArm"):
        upper = fit.world("UpperArm")
    else:
        upper = placed_upper_arm(fit, forearm, hand)
    weapon.add(bname(fit.side, "UpperArm"), parent, upper)
    weapon.add(bname(fit.side, "Forearm"), bname(fit.side, "UpperArm"), forearm)
    weapon.add(bname(fit.side, "Hand"), bname(fit.side, "Forearm"), hand)
    for part in FINGERS:
        if bname(fit.side, part) not in fit.player.rest:
            continue
        p = finger_parent(part)
        weapon.add(bname(fit.side, part), bname(fit.side, p), fit.world(part))

    def bone_of_part(part):
        return smd.index(bname(fit.side, HELPERS.get(part, part)))

    set_weights(smd, corners, weights, bone_of_part)


def graft_arm(weapon, player, donor_name, donor_seq, seq, parent, side="L", park_pitch=0.0):
    """Copy the donor's arm into this model at the same place in eye space."""
    donor = Weapon(donor_name, weapon.root)
    dsmd = donor.ref
    pieces = arm_pieces(dsmd)
    pick = None
    for corners in pieces:
        fit, _other = best_fit(player, corners, dsmd)
        if fit.side == side:
            pick = (fit, corners)
            break
    if pick is None:
        raise RuntimeError("%s has no %s arm to graft" % (donor_name, side))
    fit, corners = pick
    weights = fit.corner_weights(corners, dsmd)

    # donor bind pose -> donor idle pose, per donor bone (vertices by skinning)
    d_ref = dsmd.worlds(0)
    d_anim = Smd(os.path.join(donor.dir, "anims", donor_seq + ".smd"))
    d_idle_by_name = {d_anim.nodes[i][0]: m for i, m in d_anim.worlds(0).items()}
    delta = {}
    for i, (name, _p) in enumerate(dsmd.nodes):
        if name in d_idle_by_name:
            delta[i] = d_idle_by_name[name] @ np.linalg.inv(d_ref[i])
        else:
            delta[i] = np.eye(4)

    # eye space -> this model's bind pose, through the parent bone
    r_ref = weapon.ref.worlds(0)
    r_anim = Smd(os.path.join(weapon.dir, "anims", seq + ".smd"))
    r_idle = {r_anim.nodes[i][0]: m for i, m in r_anim.worlds(0).items()}
    p_index = weapon.ref.index(parent)
    to_ref = r_ref[p_index] @ np.linalg.inv(r_idle[parent])

    # the donor bone each player part rides on
    donor_part = existing_part_bones(donor, fit, corners, weights)

    def part_delta(part):
        name = donor_part.get(part) or donor_part.get(HELPERS.get(part, ""), None) or donor_part.get("Hand")
        return delta[dsmd.index(name)]

    # park it: swing the arm down about the shoulder (eye space pitch) so the
    # stock animations, which don't know about this arm, never show it
    shoulder = (part_delta("UpperArm") @ fit.world("UpperArm"))[:3, 3]
    a = math.radians(park_pitch)
    pitch = np.eye(4)
    pitch[:3, :3] = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    to_ref = to_ref @ _about(shoulder, pitch)

    # bones
    names = {}
    for part in MAIN + FINGERS:
        if bname(side, part) not in player.rest:
            continue
        world = to_ref @ part_delta(part) @ fit.world(part)
        if part == "UpperArm":
            bone_parent = parent
        elif part in MAIN:
            bone_parent = bname(side, MAIN[MAIN.index(part) - 1])
        else:
            bone_parent = bname(side, finger_parent(part))
        names[part] = weapon.add(bname(side, part), bone_parent, world)

    # mesh: the donor's posed arm, moved into place
    new_tris = []
    for c in range(0, len(corners), 3):
        tri_verts = []
        for (ti, k), parts in zip(corners[c:c + 3], weights[c:c + 3]):
            v = dsmd.tris[ti][1][k]
            m = np.zeros((4, 4))
            for b, w in v["links"]:
                m += w * delta[b]
            m = to_ref @ m
            nrm = m[:3, :3] @ v["nrm"]
            nrm /= np.linalg.norm(nrm) or 1.0
            tri_verts.append({
                "parent": 0, "pos": apply(m, v["pos"]), "nrm": nrm, "uv": v["uv"], "links": [], "_parts": parts,
            })
        new_tris.append((ARM_MATERIAL, tri_verts))
    smd = weapon.ref
    for _m, verts in new_tris:
        for v in verts:
            acc = defaultdict(float)
            for part, w in v.pop("_parts").items():
                acc[smd.index(bname(side, HELPERS.get(part, part)))] += w
            links = sorted(acc.items(), key=lambda kv: -kv[1])[:3]
            total = sum(w for _b, w in links) or 1.0
            v["links"] = [(b, w / total) for b, w in links if w / total > 1e-4]
            v["parent"] = v["links"][0][0]
    smd.tris.extend(new_tris)
    weapon.report.append("grafted %s arm from %s (%d triangles, fit %.3f)" % (side, donor_name, len(new_tris), fit.residual))


def process(weapon_name, player, root=MOD, ref_path=None):
    recipe = RECIPES[weapon_name]
    weapon = Weapon(weapon_name, root, ref_path)
    smd = weapon.ref
    if any(smd.index(bname(s, "Finger0")) is not None for s in "LR"):
        weapon.report.append("already rigged, skipped")
        return weapon, False
    gun = recipe.get("gun_bone")
    if gun:
        name, root_bone = gun
        r = smd.index(root_bone)
        g = weapon.add(name, root_bone, smd.worlds()[r])
        moved = 0
        for material, verts in smd.tris:
            if material.startswith("bone_"):
                continue
            for v in verts:
                if any(b == r for b, _w in v["links"]):
                    v["links"] = [(g if b == r else b, w) for b, w in v["links"]]
                    v["parent"] = g if v["parent"] == r else v["parent"]
                    moved += 1
        weapon.report.append("added %s under %s, moved %d vertices onto it" % (name, root_bone, moved))
    for corners in arm_pieces(smd):
        fit, other = best_fit(player, corners, smd)
        mode = recipe.get(fit.side, "keep")
        weapon.report.append(
            "%s arm piece: %d corners, side fit %.3f (other side %.3f) -> %s"
            % (fit.side, len(corners), fit.residual, other.residual, mode)
        )
        if mode == "keep":
            continue
        weights = fit.corner_weights(corners, smd)
        if mode == "new":
            rig_new_arm(weapon, fit, corners, weights, recipe["new_parent"])
        elif mode == "fingers":
            part_bone = existing_part_bones(weapon, fit, corners, weights)
            weapon.report.append("  existing bones used: %s" % {k: v for k, v in part_bone.items() if k in MAIN})
            rig_fingers(weapon, fit, corners, weights, part_bone)
    graft = recipe.get("graft_L")
    if graft:
        graft_arm(weapon, player, graft["donor"], graft["donor_seq"], graft["seq"], graft["parent"],
                  park_pitch=graft.get("park_pitch", 0.0))
    return weapon, True


def add_bones_to_sequence(path, new_bones, ref, out_path):
    seq = Smd(path)
    worlds_ref = ref.worlds(0)
    for name, parent, _world in new_bones:
        ri = ref.index(name)
        local = local_matrix(ref.frames[0][1][ri])
        p = seq.index(parent)
        values = matrix_to_smd(local)
        seq.nodes.append([name, p])
        index = len(seq.nodes) - 1
        for _t, bones in seq.frames:
            bones[index] = values
    seq.write(out_path)


def match_bones(shipping, weapon):
    """Give the shipping mesh's new bones exactly the decoded rig's bind pose.

    Both meshes are fitted independently (their vertex weights are their
    own), but the sequences exported from Blender carry the decoded rig's
    bind pose for these bones, so the shipping model must use the same one
    or its arms would sit a fraction of a unit off under those sequences."""
    decoded = weapon.ref.worlds(0)
    worst = 0.0
    for name, _parent, _world in shipping.new_bones:
        si = shipping.ref.index(name)
        di = weapon.ref.index(name)
        if di is None:
            continue
        current = shipping.ref.worlds(0)
        parent = shipping.ref.nodes[si][1]
        local = np.linalg.inv(current[parent]) @ decoded[di]
        worst = max(worst, float(np.abs(current[si] - decoded[di]).max()))
        shipping.ref.frames[0][1][si] = matrix_to_smd(local)
    return worst


def modelsrc_ref(weapon_name, root=MOD):
    path = os.path.join(root, "modelsrc", weapon_name, weapon_name + "_ref.smd")
    return path if os.path.exists(path) else None


def write_weapon(weapon, shipping=None, out_root=None):
    """Decoded ref + sequences in Blender/<weapon>/anims, and (if given) the
    shipping source mesh modelsrc/<weapon>/<weapon>_ref.smd, rigged the same
    way but without the decoder's bone marker triangles."""
    target_dir = weapon.dir if out_root is None else os.path.join(out_root, weapon.name)
    os.makedirs(os.path.join(target_dir, "anims"), exist_ok=True)
    if out_root is None:
        backup = os.path.join(weapon.root, "Blender", "_backup_before_arms", weapon.name, "anims")
        if not os.path.exists(backup):
            os.makedirs(backup)
            for f in os.listdir(os.path.join(weapon.dir, "anims")):
                shutil.copy2(os.path.join(weapon.dir, "anims", f), backup)
    weapon.ref.write(os.path.join(target_dir, "anims", "ref.smd"))
    for path in weapon.seq_paths:
        add_bones_to_sequence(path, weapon.new_bones, weapon.ref, os.path.join(target_dir, "anims", os.path.basename(path)))
    if shipping is not None:
        src = shipping.ref_path
        dst = src if out_root is None else os.path.join(out_root, weapon.name, os.path.basename(src))
        if out_root is None:
            keep = src[:-4] + ".before_arms.smd"
            if not os.path.exists(keep):
                shutil.copy2(src, keep)
        shipping.ref.write(dst)


def main(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    fbx = DEFAULT_FBX
    dry = False
    out_root = None
    names = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--fbx":
            fbx = args[i + 1]
            i += 2
            continue
        if a == "--out":
            out_root = args[i + 1]
            i += 2
            continue
        if a == "--dry-run":
            dry = True
        else:
            names.append(a)
        i += 1
    names = names or list(RECIPES)
    player = load_player(fbx)
    for name in names:
        weapon, changed = process(name, player)
        print("== %s" % name)
        for line in weapon.report:
            print("   " + line)
        if changed:
            print("   new bones: %d" % len(weapon.new_bones))
            shipping = None
            src = modelsrc_ref(name)
            if src:
                shipping, ok = process(name, player, ref_path=src)
                if not ok:
                    shipping = None
                else:
                    moved = match_bones(shipping, weapon)
                    print("   modelsrc mesh rigged the same way (bones matched to the decoded rig, moved up to %.3f)" % moved)
            if not dry:
                write_weapon(weapon, shipping, out_root)
                print("   written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
