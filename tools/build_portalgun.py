#!/usr/bin/env python3
"""Build portalshot: strip the hands off Portal Gun 3 and put the gun on HL2's
portalgun viewmodel skeleton.

Run with Blender (it needs numpy and the FBX importer):

    blender -b --python-exit-code 1 --python tools/build_portalgun.py -- \
        "/media/.../Portal Gun 3.fbx" \
        Blender/v_portalgun/anims/ref.smd \
        modelsrc/v_portalgun/v_portalgun_ref.smd

The FBX is a converted SMD: ValveBiped arms + the Portal 2-style gun
(Casing/Gyro/Mag/Dial bones) at 1:10 scale. The stock Portal viewmodel has the
older 45-bone rig with a different gun skeleton, so the gun is bound rigidly to
ValveBiped.Base on the stock skeleton and driven by the stock sequences.

Placement: the FBX bind pose is the artist's held pose, so scaling by 10 and
moving its Base bone onto the stock Base bone keeps the gun where it was
authored in the hand. Everything is in the same Y-forward/Z-up convention.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import bpy
import numpy as np

MARKER_SIZE = 0.4
BONE = "ValveBiped.Base"


def parse_smd(path: str):
    nodes: dict[int, tuple[str, int]] = {}
    skel: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
    tris: list[tuple[str, list]] = []
    mode = None
    material = None
    corners = []
    for line in open(path, errors="ignore"):
        s = line.strip()
        if not s:
            continue
        if s in ("nodes", "skeleton", "triangles"):
            mode = s
            continue
        if s == "end":
            if mode == "triangles" and corners and material:
                tris.append((material, corners))
            mode = None
            corners = []
            continue
        p = s.split()
        if mode == "nodes":
            nodes[int(p[0])] = (p[1].strip('"'), int(p[2]))
        elif mode == "skeleton":
            if p[0] != "time":
                skel[int(p[0])] = (tuple(map(float, p[1:4])), tuple(map(float, p[4:7])))
        elif mode == "triangles":
            if len(p) == 1:
                if corners and material:
                    tris.append((material, corners))
                corners = []
                material = p[0]
                continue
            if len(p) >= 12:
                # bone, position, normal, uv, link count, bone, weight
                corners.append((int(p[0]), *map(float, p[1:9]), int(p[10]), float(p[11])))
    return nodes, skel, tris


def angle_matrix(pos, rot):
    x, y, z = rot
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    m = np.eye(4)
    m[:3, :3] = np.array(
        [
            [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
            [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
            [-sy, sx * cy, cx * cy],
        ]
    )
    m[:3, 3] = pos
    return m


def world_matrices(nodes, skel):
    world = {}

    def get(i):
        if i in world:
            return world[i]
        local = angle_matrix(*skel[i])
        parent = nodes[i][1]
        world[i] = local if parent < 0 else get(parent) @ local
        return world[i]

    return {i: get(i) for i in nodes}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("fbx")
    ap.add_argument("stock_ref")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=10.0)
    ap.add_argument("--offset", type=float, nargs=3, default=[0.0, 0.0, 0.0])
    ap.add_argument("--material", default="portalgun")
    args = ap.parse_args(argv)

    nodes, skel, tris = parse_smd(args.stock_ref)
    world = world_matrices(nodes, skel)
    base_index = next(i for i, (name, _p) in nodes.items() if name == BONE)
    base_stock = world[base_index][:3, 3]

    # Every bone above Base in the chain needs geometry or studiomdl drops it,
    # and dropping it would apply Base's animated transform to the wrong parent.
    # UpperArm/Forearm/Hand etc. get one invisible marker triangle each.
    chain = []
    node = base_index
    while node >= 0:
        chain.append(node)
        node = nodes[node][1]
    world_pos = {i: world[i][:3, 3] for i in nodes}

    bpy.ops.import_scene.fbx(filepath=args.fbx)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    ob = next(o for o in bpy.data.objects if o.type == "MESH" and o.parent == arm)
    me = ob.data
    me.calc_loop_triangles()

    hands = [i for i, m in enumerate(me.materials) if m and "hands" in m.name.lower()]
    gun_mats = [i for i in range(len(me.materials)) if i not in hands]
    if not gun_mats:
        raise SystemExit("no gun material found")

    base_fbx = np.array(arm.matrix_world @ arm.data.bones[BONE].head_local)
    obj_mat = ob.matrix_world
    rot_q = obj_mat.to_quaternion()

    gun = []
    for tri in me.loop_triangles:
        if tri.material_index not in gun_mats:
            continue
        corners = []
        for li in tri.loops:
            v = obj_mat @ me.vertices[me.loops[li].vertex_index].co
            n = rot_q @ me.loops[li].normal
            uv = me.uv_layers.active.data[li].uv
            pos = (np.array(v) - base_fbx) * args.scale + base_stock + np.array(args.offset)
            corners.append((tuple(pos), (n.x, n.y, n.z), (uv[0], 1.0 - uv[1])))
        gun.append((args.material, corners))

    # geometry bounds for the report / muzzle
    verts = np.array([c[0] for _m, corners in gun for c in corners])
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    # muzzle: centre of the front-most ring of geometry (prongs sit beside it)
    base_local = np.linalg.inv(world[base_index])
    ymin = verts[:, 1].min()
    front = verts[verts[:, 1] < ymin + 1.5]
    muzzle = np.array([front[:, 0].mean(), ymin + 0.3, front[:, 2].mean()])
    tip_local = base_local @ np.append(muzzle, 1.0)

    lines = ["version 1", "nodes"]
    for i, (name, parent) in sorted(nodes.items()):
        lines.append(f'{i} "{name}" {parent}')
    lines += ["end", "skeleton", "time 0"]
    for i in sorted(skel):
        pos, rot = skel[i]
        lines.append(
            "%d %.6f %.6f %.6f %.6f %.6f %.6f"
            % (i, pos[0], pos[1], pos[2], rot[0], rot[1], rot[2])
        )
    lines += ["end", "triangles"]
    for bone in chain:
        if bone == base_index:
            continue
        x, y, z = world_pos[bone]
        lines.append("invisible")
        for corner in ((x + MARKER_SIZE, y, z), (x, y + MARKER_SIZE, z), (x, y, z + MARKER_SIZE)):
            lines.append(
                " %d %.4f %.4f %.4f 0.0000 0.0000 1.0000 0.0000 0.0000 1 %d 1.000000"
                % (bone, corner[0], corner[1], corner[2], bone)
            )
    for material, corners in gun:
        lines.append(material)
        for pos, normal, uv in corners:
            lines.append(
                " %d %.4f %.4f %.4f %.4f %.4f %.4f %.4f %.4f 1 %d 1.000000"
                % (base_index, pos[0], pos[1], pos[2], normal[0], normal[1], normal[2], uv[0], uv[1], base_index)
            )
    lines += ["end"]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n\n")

    print(f"REF: {args.out}")
    print(f"REF: gun triangles {len(gun)}  vertices {len(verts)}")
    print(f"REF: bbox min {np.round(lo, 2)} max {np.round(hi, 2)} dims {np.round(hi - lo, 2)}")
    print(f"REF: stock base {np.round(base_stock, 2)}")
    print(f"REF: gun centroid offset from stock base {np.round(verts.mean(axis=0) - base_stock, 2)}")
    print(f"REF: muzzle local to Base {np.round(tip_local[:3], 3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[sys.argv.index("--") + 1:]))
